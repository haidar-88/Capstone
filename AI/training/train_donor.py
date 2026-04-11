"""
Bayesian optimisation of MCDA donor-selection weights using Optuna.

Runs an Optuna study that searches the 5-dimensional weight space.  Each trial
evaluates a weight vector over N random platoon scenarios and returns the mean
enriched reward.  The best weights are saved to AI/donor_weights.json.

Run with:
    python -m AI.training.train_donor
"""

import math
import random
import statistics
import sys
import os

import optuna

# Allow running from the project root without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from vehicle.vehicle import Vehicle
from network.platoon import Platoon
from AI.donor_scorer import score_candidate, get_max_dist_cost
from AI.donor_weights import DEFAULT_WEIGHTS, save_weights


# ─────────────────────────── scenario factory ────────────────────────────────

def _make_scenario(n_vehicles=6, spacing_range=(5.0, 50.0)):
    """
    Build a randomised in-memory platoon with varied battery and position state.
    No threads are started — vehicles are used as pure data containers.

    Returns (head_vehicle, all_vehicles, platoon)
    """
    platoon = Platoon("TRAIN_PLATOON")
    vehicles = []

    for i in range(n_vehicles):
        is_leader = (i == 0)
        x_pos = sum(random.uniform(*spacing_range) for _ in range(i))

        capacity = 80.0
        min_energy = 10.0
        if is_leader:
            initial = random.uniform(50.0, 75.0)
        else:
            initial = random.uniform(12.0, 70.0)

        health = random.uniform(0.3, 1.0)

        v = Vehicle(
            vehicle_id=i,
            battery_capacity_kwh=capacity,
            initial_energy_kwh=initial,
            min_energy_kwh=min_energy,
            max_transfer_rate_in=50.0,
            max_transfer_rate_out=50.0,
            connection_range=100,
            latitude=x_pos,
            longitude=0.0,
            heading=0.0,
            velocity=10.0,
            platoon=None,
            is_leader=is_leader,
            battery_health=health,
        )
        platoon.add_vehicle(v)
        vehicles.append(v)

    head = vehicles[0]
    # No add_connection() calls — the scorer's _edge_features_from_gps()
    # fallback computes the same physics without spawning Edge threads.

    return head, vehicles, platoon


# ─────────────────────────── reward computation ──────────────────────────────

_MAX_EFF = 0.95
_DECAY   = 0.05
_HW_EFF  = 0.9


def _compute_reward(provider, head, demand, vehicles):
    """
    Enriched reward that captures three objectives:

        reward = 0.5 * delivery_fraction
               + 0.3 * donor_surplus_preserved
               + 0.2 * (1 - platoon_energy_cv)

    delivery_fraction   — fraction of demand the provider can actually deliver
    donor_surplus_preserved — provider's remaining usable energy / capacity after transfer
    platoon_energy_cv   — coefficient of variation of energy levels after the
                          virtual transfer (lower = more balanced = better)
    """
    distance_m = head.distance_to(provider)
    transfer_eff = _MAX_EFF * math.exp(-_DECAY * distance_m) * _HW_EFF

    surplus = provider.available_energy() - provider.min_energy()
    transferable = min(surplus * transfer_eff, demand)
    delivery_fraction = transferable / max(demand, 1e-9)

    # Energy the donor loses (gross, before efficiency)
    gross_given = transferable / max(transfer_eff, 1e-9)
    donor_remaining = provider.available_energy() - gross_given
    donor_surplus_preserved = max(donor_remaining - provider.min_energy(), 0.0) / max(
        provider.battery_capacity(), 1e-9
    )

    # Platoon energy balance after the virtual transfer
    energy_levels = []
    for v in vehicles:
        if v is provider:
            energy_levels.append(donor_remaining)
        else:
            energy_levels.append(v.available_energy())

    mean_e = statistics.mean(energy_levels) if energy_levels else 1.0
    std_e = statistics.pstdev(energy_levels) if len(energy_levels) > 1 else 0.0
    cv = std_e / max(mean_e, 1e-9)
    # Clamp CV contribution to [0, 1]
    balance_score = max(0.0, 1.0 - cv)

    return (
        0.5 * delivery_fraction
        + 0.3 * donor_surplus_preserved
        + 0.2 * balance_score
    )


# ─────────────────────────── Optuna objective ────────────────────────────────

N_EVAL_SCENARIOS = 200


def _pick_best_with_weights(head, candidates, demand, weights):
    """Score all candidates with the given weights, return the best one."""
    max_cost = get_max_dist_cost(head, candidates)

    best_vehicle = None
    best_score = float("-inf")
    for c in candidates:
        s = score_candidate(c, head, demand, weights, max_cost)
        if s > best_score:
            best_score = s
            best_vehicle = c
    return best_vehicle


def objective(trial):
    """Optuna objective: mean enriched reward over N random scenarios."""
    weights = {
        "surplus": trial.suggest_float("surplus", 0.1, 2.0),
        "health":  trial.suggest_float("health",  0.1, 2.0),
        "dist":    trial.suggest_float("dist",    0.1, 2.0),
        "eff":     trial.suggest_float("eff",     0.1, 2.0),
        "loss":    trial.suggest_float("loss",    0.1, 2.0),
    }

    rewards = []
    for _ in range(N_EVAL_SCENARIOS):
        head, vehicles, _platoon = _make_scenario()

        non_leaders = [v for v in vehicles if not v.is_leader]
        consumer = random.choice(non_leaders)
        demand = random.uniform(5.0, 25.0)

        candidates = [
            v for v in vehicles
            if v is not head and v.vehicle_id != consumer.vehicle_id
        ]

        provider = _pick_best_with_weights(head, candidates, demand, weights)

        if provider is None:
            rewards.append(0.0)
        else:
            rewards.append(_compute_reward(provider, head, demand, vehicles))

    return statistics.mean(rewards)


# ─────────────────────────── training entry point ────────────────────────────

def train(n_trials=300):
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    print(f"Starting Optuna optimisation: {n_trials} trials, "
          f"{N_EVAL_SCENARIOS} scenarios per trial")
    print(f"Default weights: {DEFAULT_WEIGHTS}\n")

    def _progress(study, trial):
        if trial.number % 50 == 0 and trial.number > 0:
            best = study.best_trial
            w = {k: round(best.params[k], 3) for k in DEFAULT_WEIGHTS}
            print(
                f"Trial {trial.number:>4} | "
                f"Best reward so far: {best.value:.4f} | "
                f"Weights: {w}"
            )

    study.optimize(objective, n_trials=n_trials, callbacks=[_progress])

    best = study.best_trial
    best_weights = {k: best.params[k] for k in DEFAULT_WEIGHTS}
    save_weights(best_weights)

    print(f"\nOptimisation complete.")
    print(f"Best trial: #{best.number}  reward: {best.value:.4f}")
    print(f"Best weights: { {k: round(v, 3) for k, v in best_weights.items()} }")
    print(f"Saved to AI/donor_weights.json")

    # Quick comparison with defaults
    study_default = optuna.create_study(direction="maximize")
    default_trial = optuna.trial.FixedTrial(DEFAULT_WEIGHTS)
    default_reward = objective(default_trial)
    improvement = best.value - default_reward
    print(f"\nDefault weights reward: {default_reward:.4f}")
    print(f"Improvement over defaults: {improvement:+.4f} "
          f"({improvement / max(default_reward, 1e-9) * 100:+.1f}%)")


if __name__ == "__main__":
    train()
