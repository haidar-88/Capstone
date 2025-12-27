import heapq

class Node:
    """
    Represents an autonomous vehicle / energy node.
    Battery model uses REAL physical units only.
    """

    def __init__(
            self,
            node_id,
            battery_capacity_kwh,          # Total battery capacity (kWh)
            initial_energy_kwh,            # Current energy (kWh)
            min_energy_kwh,                # Minimum allowed energy (kWh)
            max_transfer_rate_in=50.0,     # Max charge power (kW)
            max_transfer_rate_out=50.0,    # Max discharge power (kW)
            latitude=0.0,
            longitude=0.0,
            velocity=0.0,                  # m/s
            platoon=None,
            is_leader=False,
            battery_health=1.0             # 0.0 → 1.0
        ):
        
        # Identity
        self.node_id = node_id

        # Battery (REAL units)
        self.battery_capacity_kwh = battery_capacity_kwh
        self.battery_energy_kwh = min(initial_energy_kwh, battery_capacity_kwh)
        self.min_energy_kwh = min_energy_kwh

        self.max_transfer_rate_in = max_transfer_rate_in
        self.max_transfer_rate_out = max_transfer_rate_out
        self.battery_health = battery_health

        # GPS & motion
        self.latitude = latitude
        self.longitude = longitude
        self.velocity = velocity

        # Platoon info
        self.platoon = platoon
        self.is_leader = is_leader

        # Connections
        self.connections_list = {}

    def available_energy(self):
        """Energy currently available (kWh)."""
        return self.battery_energy_kwh
    
    def can_transfer(self, power_kw):
        """
        Check if discharge is allowed (1 second assumed).
        """

        if self.battery_health <= 0.0:
            return False

        power_kw = min(power_kw, self.max_transfer_rate_out)

        energy_required = power_kw / 3600.0  # kWh for 1 second

        return (self.battery_energy_kwh - energy_required) >= self.min_energy_kwh
    
    def request_power(self, power):
        self.platoon.update_total_energy_demand(power)
        return True
    
    def drain_power(self, power_kw):
        """
        Drain battery assuming EXACTLY 1 second per call.
        power_kw : discharge power (kW)
        """

        if not self.can_transfer(power_kw):
            self.battery_energy_kwh = self.min_energy_kwh
            return False

        power_kw = min(power_kw, self.max_transfer_rate_out)

        energy_used = power_kw / 3600.0  # kWh per second

        self.battery_energy_kwh -= energy_used
        return True

    def charge_power(self, power_kw):
        """
        Charge battery assuming EXACTLY 1 second per call.
        """

        power_kw = min(power_kw, self.max_transfer_rate_in)

        energy_added = power_kw / 3600.0  # kWh

        self.battery_energy_kwh = min(
            self.battery_energy_kwh + energy_added,
            self.battery_capacity_kwh
        )
        return True

    def position(self):
        return (self.latitude, self.longitude)

    def add_connection(self, node, edge):
        if node not in self.connections_list:
            self.connections_list[node] = edge
        return True

    def remove_connection(self, node):
        if node in self.connections_list:
            self.connections_list.remove(node)
            return True
        return False
    
    def prepare_data_for_dijkstra(self):
        # 1. Determine how many nodes we have
        V = self.platoon.node_number + 1
        
        # 2. Create the empty 'adj' list structure
        adj = [[] for _ in range(V)]
        
        # 3. Fill 'adj' using your hashmaps
        for node in self.platoon.nodes:
            u = node.node_id
            # Iterate through your dict {node: edge}
            for neighbor_node, edge_obj in node.connections_list.items():
                v = neighbor_node.node_id
                w = edge_obj.edge_cost # Your AI-calculated energy/distance cost
                
                adj[u].append((v, w))
                
        return adj

    def dijkstra(self):

        src = self.node_id
        adj = self.prepare_data_for_dijkstra()

        V = len(adj)

        # Min-heap (priority queue) storing pairs of (distance, node)
        pq = []

        path_to = [-1] * (V + 1)
        dist = [float('inf')] * (V + 1)

        # Distance from source to itself is 0
        dist[src] = 0
        path_to[src] = src
        heapq.heappush(pq, (0, src))

        # Process the queue until all reachable vertices are finalized
        while pq:
            d, u = heapq.heappop(pq)

            # If this distance not the latest shortest one, skip it
            if d > dist[u]:
                continue

            # Explore all neighbors of the current vertex
            for v, w in adj[u]:

                # If we found a shorter path to v through u, update it
                if dist[u] + w < dist[v]:
                    dist[v] = dist[u] + w
                    path_to[v] = u
                    heapq.heappush(pq, (dist[v], v))

        # Return the final shortest distances from the source
        return dist, path_to
    
    def __str__(self):
        temp = {x.node_id : y.edge_cost for x,y in self.connections_list.items()}
        return (
            f"Node Status:\n"
            f"-----------\n"
            f"Node ID              : {self.node_id}\n"
            f"Energy               : {self.battery_energy_kwh:.3f} / {self.battery_capacity_kwh:.3f} kWh\n"
            f"Minimum energy       : {self.min_energy_kwh:.3f} kWh\n"
            f"Battery health       : {self.battery_health:.2f}\n"
            f"Max charge rate      : {self.max_transfer_rate_in:.1f} kW\n"
            f"Max discharge rate   : {self.max_transfer_rate_out:.1f} kW\n"
            f"Battery Health       : {self.battery_health:.1f}\n"
            f"Position (lat, lon)  : ({self.latitude:.5f}, {self.longitude:.5f})\n"
            f"Velocity             : {self.velocity:.2f} m/s\n"
            f"Platoon              : {self.platoon.platoon_id}\n"
            f"Leader               : {self.is_leader}\n"
            f"Connections          : {temp}"
        )

