import math


# Constants mirroring edge.py defaults — kept here so the scorer
# can replicate edge physics without needing a live Edge thread.
_MAX_EFFICIENCY   = 0.95
_DECAY_FACTOR     = 0.05
_HW_EFFICIENCY    = 0.9
_EDGE_W_DIST      = 0.3
_EDGE_W_LOSS      = 0.5
_EDGE_W_EFF       = 0.2

# Fallback values used when no path to a candidate can be determined.
_FALLBACK_EFFICIENCY = 0.7
_FALLBACK_LOSS       = 0.3


def _edge_features_from_gps(head_vehicle, candidate):
    """
    Compute (edge_cost, transfer_efficiency, energy_loss) from raw GPS + battery
    hardware specs when no live Edge exists in connections_list.
    """
    distance_m = head_vehicle.distance_to(candidate)

    src_out = head_vehicle.battery.get_max_transfer_rate_out()
    dst_in  = candidate.battery.get_max_transfer_rate_in()
    transfer_efficiency = min(dst_in / max(src_out, dst_in, 1e-9), 1.0)

    total_eff = _MAX_EFFICIENCY * math.exp(-_DECAY_FACTOR * distance_m) * _HW_EFFICIENCY
    energy_loss = max(0.0, min(1.0 - total_eff, 1.0))

    edge_cost = (
        _EDGE_W_DIST * distance_m
        + _EDGE_W_LOSS * energy_loss
        + _EDGE_W_EFF  * transfer_efficiency
    )
    return edge_cost, transfer_efficiency, energy_loss


def _get_edge_features(head_vehicle, candidate):
    """
    Return (edge_cost, transfer_efficiency, energy_loss) for a candidate vehicle.
    Uses the live Edge from connections_list if present; falls back to GPS maths.
    """
    live_edge = head_vehicle.connections_list.get(candidate)
    if live_edge is not None:
        return live_edge.edge_cost, live_edge.transfer_efficiency, live_edge.energy_loss
    return _edge_features_from_gps(head_vehicle, candidate)


def get_max_dist_cost(head_vehicle, candidates):
    """
    Return the maximum edge_cost across all candidates.
    Used to normalise the distance term so it stays in [0, 1].
    """
    costs = [_get_edge_features(head_vehicle, c)[0] for c in candidates]
    return max(costs) if costs else 1.0


def score_candidate(candidate, head_vehicle, demand, weights, max_dist_cost=None):
    """
    Score a single candidate vehicle using Multi-Criteria Decision Analysis.

    Feasibility gates (returns -inf if any fail):
      - battery_health < 0.4
      - available_energy - demand < min_energy  (would drop below safety floor)

    Scoring formula:
      score = w_surplus * surplus_ratio
            + w_health  * health
            - w_dist    * normalised_edge_cost
            + w_eff     * transfer_efficiency
            - w_loss    * energy_loss

    Args:
        candidate:      Vehicle to evaluate
        head_vehicle:   Platoon head (source of edge data and Dijkstra)
        demand:         kWh the consumer is requesting
        weights:        dict from donor_weights.load_weights()
        max_dist_cost:  maximum edge_cost across all candidates (for normalisation);
                        pass None to skip normalisation

    Returns:
        float score, or float('-inf') if candidate is ineligible
    """
    # --- Feasibility gates ---
    if candidate.battery_health() < 0.4:
        return float('-inf')
    if candidate.available_energy() - demand < candidate.min_energy():
        return float('-inf')

    # --- Feature extraction ---
    surplus_ratio = (
        (candidate.available_energy() - candidate.min_energy())
        / max(candidate.battery_capacity(), 1e-9)
    )
    health = candidate.battery_health()

    edge_cost, transfer_efficiency, energy_loss = _get_edge_features(head_vehicle, candidate)

    if max_dist_cost and max_dist_cost > 0:
        norm_dist = edge_cost / max_dist_cost
    else:
        norm_dist = edge_cost

    # --- MCDA score ---
    score = (
        weights.get("surplus", 0.8) * surplus_ratio
        + weights.get("health",  0.4) * health
        - weights.get("dist",    0.5) * norm_dist
        + weights.get("eff",     0.2) * transfer_efficiency
        - weights.get("loss",    0.3) * energy_loss
    )
    return score
