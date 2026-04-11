# AI-Based Donor Selection for MVCCP Platoon Charging

## 1. Problem Statement

When an electric vehicle (EV) joins an MVCCP platoon and requests wireless energy,
the **platoon head** must decide which member vehicle should serve as the energy
**donor**. The decision is non-trivial because it involves competing objectives:

- **Maximise delivery** -- choose a donor that can actually supply the requested kWh.
- **Preserve donor health** -- avoid draining a donor below its safety floor.
- **Minimise transfer losses** -- wireless power transfer efficiency decays
  exponentially with distance; a far-away donor wastes energy in transit.
- **Maintain platoon balance** -- repeatedly picking the same high-surplus donor
  leaves the platoon with one depleted vehicle and several idle ones.

The decision must be made in real time (sub-second) with only local information
available to the platoon head through DSRC beacons.

## 2. Approach: Multi-Criteria Decision Analysis (MCDA)

We model the donor selection as a **single-shot, fully-observable
Multi-Criteria Decision Analysis** problem. The platoon head evaluates every
candidate vehicle against five criteria, computes a weighted linear score, and
selects the candidate with the highest score.

### 2.1 Why MCDA and Not Reinforcement Learning

Reinforcement learning (RL) excels at **sequential** decision problems where
actions have **delayed, uncertain consequences** and the agent must learn to
sacrifice immediate reward for long-term value (e.g., game playing, robotic
control). The donor selection problem has none of these properties:

| Property | Donor Selection | RL Sweet Spot |
|----------|----------------|---------------|
| Decision horizon | Single step | Multi-step trajectory |
| State observability | Full (all battery/GPS/health data available) | Partial or learned |
| Action space | ~5 discrete candidates | Large or continuous |
| Reward delay | Immediate (transfer physics are deterministic) | Delayed and stochastic |
| Sample efficiency need | High (limited platoon scenarios) | Low (millions of episodes typical) |

A weighted linear model over physics-informed features is therefore both
**more interpretable** and **more sample-efficient** than a policy-gradient or
Q-learning approach. We reserve learning for the meta-problem of finding the
optimal weights (Section 4).

### 2.2 Feature Set

Each candidate vehicle *c* is described by five features, computed from data
already available in the platoon head's neighbor table and edge graph:

| Feature | Symbol | Definition | Range |
|---------|--------|-----------|-------|
| Surplus ratio | *S(c)* | (available_energy - min_energy) / battery_capacity | [0, 1] |
| Battery health | *H(c)* | State-of-health fraction reported by the BMS | [0, 1] |
| Normalised edge cost | *D(c)* | edge_cost(head, c) / max(edge_cost) across all candidates | [0, 1] |
| Transfer efficiency | *E(c)* | min(dst_max_in / max(src_max_out, dst_max_in), 1) | [0, 1] |
| Energy loss | *L(c)* | 1 - eta_max * exp(-lambda * d) * eta_hw | [0, 1] |

where eta_max = 0.95, lambda = 0.05 m^-1, and eta_hw = 0.90 are hardware
constants derived from the wireless power transfer model in `vehicle/edge.py`.

### 2.3 Feasibility Gates

Before scoring, each candidate must pass two hard constraints. Candidates that
fail are assigned a score of negative infinity and are never selected:

1. **Health gate**: battery_health(c) >= 0.4
2. **Safety floor gate**: available_energy(c) - demand >= min_energy(c)

These gates guarantee that no donor is selected whose transfer would compromise
its own operational safety.

### 2.4 Scoring Formula

For all candidates that pass the feasibility gates, the MCDA score is:

```
score(c) = w_s * S(c) + w_h * H(c) - w_d * D(c) + w_e * E(c) - w_l * L(c)
```

The signs encode the direction of preference: surplus, health, and efficiency
are benefits (higher is better); distance cost and energy loss are costs (lower
is better). The weight vector **w** = (w_s, w_h, w_d, w_e, w_l) determines
the relative importance of each criterion.

## 3. Reward Function for Weight Optimisation

To optimise the weight vector, we need a reward signal that captures the quality
of a donor selection decision. We define a **composite reward** over three
objectives:

```
R = 0.5 * R_delivery + 0.3 * R_preservation + 0.2 * R_balance
```

| Component | Definition | Rationale |
|-----------|-----------|-----------|
| R_delivery | min(transferable, demand) / demand | Fraction of the consumer's request that the selected donor can actually fulfil. A donor that can only supply 60% of the demand scores 0.6. |
| R_preservation | max(donor_remaining - min_energy, 0) / capacity | Fraction of the donor's battery that remains usable after the transfer. Penalises selections that drain the donor to its safety floor. |
| R_balance | max(0, 1 - CV(E_post)) | One minus the coefficient of variation of all platoon members' energy levels after the virtual transfer. A perfectly balanced platoon scores 1.0; a highly skewed one scores near 0. |

The component weights (0.5, 0.3, 0.2) reflect the priority ordering:
fulfilling the consumer's request is the primary objective, preserving the donor
is secondary, and platoon-wide balance is a tertiary fairness objective.

### 3.1 Transfer Physics

The transferable energy is computed from the same wireless power transfer model
used by the simulation's Edge class:

```
eta(d) = eta_max * exp(-lambda * d) * eta_hw

transferable = min(surplus * eta(d), demand)
gross_given  = transferable / eta(d)
```

where *d* is the Euclidean distance between head and provider, and *surplus* is
the provider's available energy above its minimum safety floor.

## 4. Weight Optimisation via Bayesian Optimisation (Optuna)

Rather than hand-tuning the five MCDA weights, we treat weight selection as a
**black-box optimisation** problem and solve it with the Tree-structured Parzen
Estimator (TPE) algorithm implemented in Optuna.

### 4.1 Why Bayesian Optimisation

The objective function (mean reward over randomised scenarios) is:

- **Expensive to evaluate** -- each evaluation runs 200 platoon scenarios.
- **Noisy** -- randomised battery states and positions introduce variance.
- **Low-dimensional** -- only 5 continuous parameters.
- **Non-differentiable** -- the scorer contains hard feasibility gates (negative
  infinity scores) that create discontinuities.

These properties make Bayesian optimisation (specifically TPE) a natural fit:
it builds a probabilistic surrogate of the objective surface and allocates
evaluations where improvement is most likely, requiring far fewer trials than
grid search or random search.

### 4.2 Search Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Search range (all weights) | [0.1, 2.0] | Wide enough to explore non-obvious regimes; lower bound prevents degenerate zero-weight solutions |
| Scenarios per trial | 200 | Balances evaluation noise vs. computation time; empirically yields stable mean rewards |
| Total trials | 300 | TPE typically converges in 100-200 trials for 5D problems; 300 provides a safety margin |
| Sampler | TPE (seed=42) | Reproducible; TPE is Optuna's default and well-suited to low-dimensional continuous search |

### 4.3 Training Procedure

Each of the 300 trials proceeds as follows:

1. Optuna's TPE sampler proposes a weight vector **w** in [0.1, 2.0]^5.
2. 200 random platoon scenarios are generated, each with:
   - 6 vehicles (1 leader, 5 members)
   - Randomised inter-vehicle spacing: U(5, 50) metres cumulative
   - Leader energy: U(50, 75) kWh; member energy: U(12, 70) kWh
   - Battery health: U(0.3, 1.0)
   - Random consumer (non-leader) and demand: U(5, 25) kWh
3. For each scenario, the scorer ranks all eligible candidates using **w**,
   selects the highest-scoring donor, and computes the composite reward R.
4. The trial's objective value is the mean of R across all 200 scenarios.
5. Optuna records the result and updates the TPE surrogate model.

After all trials, the weight vector from the best trial is saved to
`donor_weights.json`.

## 5. Results

### 5.1 Optimised Weights

| Weight | Domain-Expert Default | Optuna Optimised | Change |
|--------|----------------------|------------------|--------|
| w_surplus | 0.80 | **0.40** | -50% |
| w_health | 0.40 | **0.21** | -48% |
| w_dist | 0.50 | **1.75** | +250% |
| w_eff | 0.20 | **1.24** | +520% |
| w_loss | 0.30 | **1.45** | +383% |

### 5.2 Performance Comparison

| Metric | Default Weights | Optimised Weights | Improvement |
|--------|----------------|-------------------|-------------|
| Mean composite reward (200 scenarios) | 0.2980 | **0.3476** | **+16.6%** |

### 5.3 Interpretation

The optimisation reveals a clear and physically meaningful shift in priorities:

**Distance and loss dominate.** The three transfer-physics criteria (w_dist,
w_eff, w_loss) were all increased by 250-520% relative to the expert defaults,
while the two battery-state criteria (w_surplus, w_health) were halved.

This result has a direct physical interpretation: **in a platoon where vehicles
are spaced 5-50 metres apart, the exponential decay of wireless transfer
efficiency (eta = 0.95 * e^{-0.05d} * 0.90) means that a donor 40 metres away
loses ~37% of transmitted energy to transfer losses, while a donor 10 metres
away loses only ~14%.** The energy wasted in transit from a distant high-surplus
donor often exceeds the surplus advantage that made it attractive in the first
place.

Concretely, this means:

- **A nearby donor with moderate surplus is preferable to a distant donor with
  high surplus.** The 23 percentage-point difference in transfer loss at
  10m vs. 40m outweighs a surplus advantage unless the distant donor has
  dramatically more energy.

- **Battery health is a gatekeeper, not a differentiator.** The feasibility gate
  already eliminates donors with health below 0.4. Among the remaining
  candidates (health 0.4-1.0), the health difference matters less than
  proximity. The optimiser confirmed this by reducing w_health by 48%.

- **Platoon balance is served indirectly.** By preferring nearby, efficient
  transfers, the optimised weights tend to spread donations across multiple
  vehicles (since the nearest donor changes as vehicles shift positions) rather
  than always draining the single highest-surplus vehicle.

### 5.4 Limitations

- **Static scenarios.** The training generates independent single-transfer
  scenarios. It does not model sequential charge requests where today's donor
  selection affects tomorrow's available surplus. A multi-step formulation could
  capture this but would require a fundamentally different optimisation approach
  (e.g., reinforcement learning over episode trajectories).

- **Fixed platoon size.** All training scenarios use 6-vehicle platoons. The
  optimised weights may not generalise to significantly larger or smaller
  platoons where the distance distribution and candidate pool change.

- **Reward component weights.** The reward weightings (0.5, 0.3, 0.2) were set
  by domain judgement, not optimised. A nested optimisation over both reward
  weights and MCDA weights is possible but risks overfitting to the scenario
  distribution.

## 6. Integration with the Simulation

The AI scorer is already wired into the MVCCP protocol stack. No additional
configuration is needed -- running the simulation uses the optimised weights
automatically.

### 6.1 Call Chain

```
Vehicle sends CHARGE_RQST message
    --> protocol/message_handler.py :: handle_charge_rqst()
        --> AI/Smart_Decision.py :: pick_a_donor(head_vehicle, demand, exclude_id)
            --> AI/donor_weights.py :: load_weights()  -- reads donor_weights.json
            --> AI/donor_scorer.py :: score_candidate() -- for each candidate
        <-- returns best Vehicle
    --> protocol/messages.py :: CHARGE_RSP_message(provider_id, consumer_id, demand)
```

When a consumer vehicle sends a `CHARGE_RQST`, the platoon head's message
handler calls `pick_a_donor()`, which loads the current weight vector from
`donor_weights.json`, scores every eligible platoon member, and returns the
highest-scoring donor. The handler then broadcasts a `CHARGE_RSP` to initiate
the energy transfer handshake.

### 6.2 Running the Simulation

```bash
python -m simulation.traci_runner
```

Each successful donor match prints:
```
Car <donor_id> will send <consumer_id> <demand>kwh of energy
```

### 6.3 Comparing Optimised vs. Default Weights

To observe the effect of the optimised weights, run the simulation twice with
different weight files:

```bash
# 1. Run with optimised weights (current state)
python -m simulation.traci_runner

# 2. Swap to defaults and re-run
cp AI/donor_weights.json AI/donor_weights_optimised.json
python -c "from AI.donor_weights import DEFAULT_WEIGHTS, save_weights; save_weights(DEFAULT_WEIGHTS)"
python -m simulation.traci_runner

# 3. Restore optimised weights
cp AI/donor_weights_optimised.json AI/donor_weights.json
```

With optimised weights, the simulation should prefer nearer donors over distant
high-surplus ones, resulting in less energy lost to transfer inefficiency.

## 7. Module Reference

| File | Purpose |
|------|---------|
| `Smart_Decision.py` | Entry point: iterates platoon candidates, applies scorer, returns best donor |
| `donor_scorer.py` | Feasibility gates and MCDA scoring formula |
| `donor_weights.py` | Load/save weight vectors from `donor_weights.json` |
| `donor_weights.json` | Persisted optimised weight vector |
| `training/train_donor.py` | Optuna-based weight optimisation harness |

## 7. Reproducing the Optimisation

```bash
pip install optuna>=4.0.0
python -m AI.training.train_donor
```

Output: optimised weights saved to `AI/donor_weights.json`, with a summary of
the best trial reward and comparison against default weights.
