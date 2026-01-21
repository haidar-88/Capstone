def pick_a_charger(requestor, platoon, amount):
    w1 = 0.8
    w2 = 0.5
    dist, path_to = requestor.dijkstra()
    proba = [0] * (platoon.node_number + 1)
    for node in platoon.nodes:
        if node == requestor:
            continue
        if ((node.battery_health < 0.4) and (node.battery_energy_kwh/node.battery_capacity_kwh < 0.8)) or (node.battery_energy_kwh-amount < node.min_energy_kwh):
            continue
        #proba[node.node_id] = w1 * dist[node.node_id] + w2 * node.battery_energy_kwh
        proba[node.node_id] = w2 * node.battery_energy_kwh - w1 * dist[node.node_id]

    print(f"Distance: {dist}\nPath To: {path_to}\nProbability: {proba}")
    return proba.index(max(proba))
