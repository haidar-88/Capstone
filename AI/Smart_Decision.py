from AI.donor_scorer import score_candidate, get_max_dist_cost
from AI.donor_weights import load_weights


def pick_a_donor(head_vehicle, demand, exclude_id=None):
    """
    Select the best provider vehicle from the platoon using MCDA scoring.

    Called by MessageHandler.handle_charge_rqst when self.vehicle.is_leader.

    Args:
        head_vehicle: Platoon head Vehicle object (self.vehicle in the handler)
        demand:       kWh requested by the consumer
        exclude_id:   vehicle_id of the consumer — excluded from candidacy

    Returns:
        The best provider Vehicle object, or None if no eligible provider exists.
    """
    if head_vehicle.platoon is None:
        return None

    candidates = [
        v for v in head_vehicle.platoon.vehicles
        if v is not head_vehicle
        and (exclude_id is None or v.vehicle_id != exclude_id)
    ]

    if not candidates:
        return None

    weights = load_weights()
    max_cost = get_max_dist_cost(head_vehicle, candidates)

    best_vehicle = None
    best_score = float('-inf')
    for candidate in candidates:
        s = score_candidate(candidate, head_vehicle, demand, weights, max_cost)
        if s > best_score:
            best_score = s
            best_vehicle = candidate

    return best_vehicle  # None only if every candidate failed feasibility gates


def pick_a_charger(requestor, platoon, amount):
    """
    Deprecated — was never called; retained for API compatibility.
    Delegates to the same MCDA scorer used by pick_a_donor.

    Returns:
        vehicle_id of the chosen provider, or None.
    """
    candidates = [v for v in platoon.vehicles if v is not requestor]
    if not candidates:
        return None

    weights = load_weights()
    max_cost = get_max_dist_cost(requestor, candidates)

    best_id = None
    best_score = float('-inf')
    for candidate in candidates:
        s = score_candidate(candidate, requestor, amount, weights, max_cost)
        if s > best_score:
            best_score = s
            best_id = candidate.vehicle_id

    return best_id
