import heapq
import energy_manager
from protocol import provider_table
from protocol import message_handler
from protocol import messages

class Vehicle:
    """
    Represents an autonomous vehicle / energy vehicle.
    Battery model uses REAL physical units only.
    """

    def __init__(
            self,
            vehicle_id,
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
        self.vehicle_id = vehicle_id

        self.battery = energy_manager.BatteryManager(
            battery_capacity_kwh,
            initial_energy_kwh,
            min_energy_kwh,
            max_transfer_rate_in,
            max_transfer_rate_out,
            battery_health
        )


        # GPS & motion
        self.latitude = latitude
        self.longitude = longitude
        self.velocity = velocity

        # Platoon info
        self.platoon = platoon
        self.is_leader = is_leader

        # --- MVCCP COMMUNICATION STATE ---
        self.provider_table = provider_table.ProviderTable()  # provider_id -> info dict
        self.inbox = []  # received messages (simulation queue)

        self.handler = message_handler.MessageHandler(self)

        # Connections
        self.connections_list = {}

    def join_platoon(self, platoon):
        if not self.platoon:
            self.platoon = platoon
            return True
        return False
    
    def leave_platoon(self):
        if self.platoon:
            self.platoon = None
            return True
        return False

    def receive_message(self, mssg):
        self.inbox.append(mssg)
        return True

    def process_messages(self):
        while True:
            if self.inbox:
                self.handler.handle(self.inbox.pop())
    
    def send_protocol_message(self, message_builder_func, *args, broadcast=True, target_id=None):
        """
        Generic method to call any message builder and send it.
        *args: extra parameters required by the specific message builder
        """
        # 1. Call the function from messages.py
        # We always pass 'self' first because your builders expect the sender vehicle
        msg = message_builder_func(self, *args)

        # 2. Direct the traffic via the Platoon
        if not self.platoon:
            print(f"Vehicle {self.node_id} has no platoon to send to!")
            return

        if broadcast:
            self.platoon.broadcast(sender=self, message=msg)
        elif target_id:
            self.platoon.send_to(target_id, message=msg)

    def available_energy(self):
        return self.battery.available_energy()

    def drain_power(self, power_kw, duration_s=1):
        return self.battery.drain(power_kw, duration_s)

    def charge_power(self, power_kw, duration_s=1):
        return self.battery.charge(power_kw, duration_s)

    def receive_message(self, msg):
        self.inbox.append(msg)
    
    # Zabet hal function later
    def request_power(self, power):
        self.platoon.update_total_energy_demand(power)
        return True

    def position(self):
        return (self.latitude, self.longitude)

    def add_connection(self, vehicle, edge):
        if vehicle not in self.connections_list:
            self.connections_list[vehicle] = edge
        return True

    def remove_connection(self, vehicle):
        if vehicle in self.connections_list:
            self.connections_list.remove(vehicle)
            return True
        return False
    
    def prepare_data_for_dijkstra(self):
        # 1. Determine how many vehicles we have
        V = self.platoon.vehicle_number + 1
        
        # 2. Create the empty 'adj' list structure
        adj = [[] for _ in range(V)]
        
        # 3. Fill 'adj' using your hashmaps
        for vehicle in self.platoon.vehicles:
            u = vehicle.vehicle_id
            # Iterate through your dict {vehicle: edge}
            for neighbor_vehicle, edge_obj in vehicle.connections_list.items():
                v = neighbor_vehicle.vehicle_id
                w = edge_obj.edge_cost # Your AI-calculated energy/distance cost
                
                adj[u].append((v, w))
                
        return adj

    def dijkstra(self):

        src = self.vehicle_id
        adj = self.prepare_data_for_dijkstra()

        V = len(adj)

        # Min-heap (priority queue) storing pairs of (distance, vehicle)
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
        temp = {x.vehicle_id : y.edge_cost for x,y in self.connections_list.items()}
        return (
            f"vehicle Status:\n"
            f"-----------\n"
            f"vehicle ID              : {self.vehicle_id}\n"
            f"Energy               : {self.battery.energy_kwh:.3f} / {self.battery.capacity_kwh:.3f} kWh\n"
            f"Minimum energy       : {self.battery.min_energy_kwh:.3f} kWh\n"
            f"Battery health       : {self.battery.battery_health:.2f}\n"
            f"Max charge rate      : {self.battery.max_transfer_rate_in:.1f} kW\n"
            f"Max discharge rate   : {self.battery.max_transfer_rate_out:.1f} kW\n"
            f"Position (lat, lon)  : ({self.latitude:.5f}, {self.longitude:.5f})\n"
            f"Velocity             : {self.velocity:.2f} m/s\n"
            f"Platoon              : {self.platoon.platoon_id}\n"
            f"Leader               : {self.is_leader}\n"
            f"Connections          : {temp}"
        )

