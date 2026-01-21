import heapq
import math

# Import ProtocolConfig for defaults (avoiding circular dependency by importing here)
try:
    from src.protocol.config import ProtocolConfig
    _USE_CONFIG_DEFAULTS = True
except ImportError:
    # Fallback if ProtocolConfig not available (shouldn't happen in normal usage)
    ProtocolConfig = None  # type: ignore
    _USE_CONFIG_DEFAULTS = False


class Node:
    """
    Represents an autonomous vehicle / energy node.
    Battery model uses REAL physical units only.
    """
    
    # Route provider for SUMO integration (injected at simulation start)
    # Set this to a RouteProvider instance to use real road network distances
    route_provider = None

    def __init__(
            self,
            node_id,
            battery_capacity_kwh=None,    # Total battery capacity (kWh) - defaults from ProtocolConfig
            battery_energy_kwh=None,       # Current energy (kWh) - defaults from ProtocolConfig
            min_energy_kwh=None,           # Minimum allowed energy (kWh) - defaults from ProtocolConfig
            max_transfer_rate_in=None,     # Max charge power (kW) - defaults from ProtocolConfig
            max_transfer_rate_out=None,    # Max discharge power (kW) - defaults from ProtocolConfig
            latitude=None,
            longitude=None,
            velocity=None,                 # m/s - defaults from ProtocolConfig
            destination=None,              # (lat, lon) tuple - final destination
            platoon=None,
            is_leader=False,
            battery_health=None,           # 0.0 → 1.0 - defaults from ProtocolConfig
            etx=None,
            delay=0.0,
            willingness=None,
            lane_weight=None,
            link_stability=None,
            link_status="SYM"
        ):

        
        # Get defaults from ProtocolConfig if available
        if _USE_CONFIG_DEFAULTS and ProtocolConfig is not None:
            defaults = ProtocolConfig.NODE_DEFAULTS
        else:
            # Fallback defaults (shouldn't be used in normal operation)
            defaults = {
                'battery_capacity_kwh': 100.0,
                'battery_energy_kwh': 50.0,
                'min_energy_kwh': 10.0,
                'max_transfer_rate_in': 50.0,
                'max_transfer_rate_out': 50.0,
                'latitude': 0.0,
                'longitude': 0.0,
                'velocity': 0.0,
                'battery_health': 1.0,
                'etx': 1.0,
                'willingness': 3,
                'lane_weight': 0.5,
                'link_stability': 1.0,
            }
        
        # Identity - Validate node_id first
        if node_id is None:
            raise ValueError("node_id cannot be None")
        self.node_id = node_id

        # Battery (REAL units) - use defaults if None provided
        self.battery_capacity_kwh = battery_capacity_kwh if battery_capacity_kwh is not None else defaults['battery_capacity_kwh']
        battery_energy = battery_energy_kwh if battery_energy_kwh is not None else defaults['battery_energy_kwh']
        self.battery_energy_kwh = min(battery_energy, self.battery_capacity_kwh)
        self.min_energy_kwh = min_energy_kwh if min_energy_kwh is not None else defaults['min_energy_kwh']

        self.max_transfer_rate_in = max_transfer_rate_in if max_transfer_rate_in is not None else defaults['max_transfer_rate_in']
        self.max_transfer_rate_out = max_transfer_rate_out if max_transfer_rate_out is not None else defaults['max_transfer_rate_out']
        self.battery_health = battery_health if battery_health is not None else defaults['battery_health']

        # GPS & motion
        self.latitude = latitude if latitude is not None else defaults['latitude']
        self.longitude = longitude if longitude is not None else defaults['longitude']
        self.velocity = velocity if velocity is not None else defaults['velocity']
        
        # Destination (lat, lon tuple)
        self.destination = destination  # None means no destination set

        # Platoon info
        self.platoon = platoon
        self.is_leader = is_leader

        # Connections (Physical/Platoon)
        self.connections_list = {}

        # --- Network / MVCCP Layer Info ---
        # These fields are used when this Node object represents a remote neighbor
        self.ip_address = "0.0.0.0"
        self.last_seen = 0.0
        
        # QoS Metrics
        self.etx = etx if etx is not None else defaults['etx']
        self.delay = delay
        self.willingness = willingness if willingness is not None else defaults['willingness']
        self.lane_weight = lane_weight if lane_weight is not None else defaults['lane_weight']
        self.link_stability = link_stability if link_stability is not None else defaults['link_stability']
        
        # Topology
        self.two_hop_neighbors = set()
        self.link_status = link_status
        
        # Validate critical values after defaults are applied
        self._validate_parameters()

        # Internal Protocol Tables
        # These are managed by the Protocol Context/Handlers.


    def _validate_parameters(self):
        """Validate critical parameters after initialization."""
        # Battery capacity must be positive (avoid division by zero in QoS)
        if self.battery_capacity_kwh <= 0:
            raise ValueError(
                f"battery_capacity_kwh must be positive, got {self.battery_capacity_kwh}"
            )
        
        # Battery energy cannot be negative
        if self.battery_energy_kwh < 0:
            raise ValueError(
                f"battery_energy_kwh cannot be negative, got {self.battery_energy_kwh}"
            )
        
        # Min energy cannot be negative
        if self.min_energy_kwh < 0:
            raise ValueError(
                f"min_energy_kwh cannot be negative, got {self.min_energy_kwh}"
            )
        
        # Transfer rates cannot be negative
        if self.max_transfer_rate_in < 0 or self.max_transfer_rate_out < 0:
            raise ValueError(
                "Transfer rates cannot be negative"
            )
    
    # Note: current_time removed - use context.current_time instead
    # This prevents backdoor access to wall-clock time and enforces
    # simulation-time-only discipline throughout the protocol.

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
        """Returns current position as (lat, lon) tuple."""
        return (self.latitude, self.longitude)
    
    # --- Route and Energy Calculation Methods ---
    
    def distance_to(self, target_position: tuple) -> float:
        """
        Calculate distance to a target position in km.
        Uses SUMO route provider if available, otherwise falls back to Euclidean.
        
        Args:
            target_position: (lat, lon) tuple
            
        Returns:
            Distance in kilometers
        """
        if target_position is None:
            return 0.0
            
        if Node.route_provider is not None:
            # Use SUMO TraCI for real road network distance
            return Node.route_provider.get_route_distance(self.position(), target_position)
        else:
            # Fallback to Euclidean distance (approximate conversion)
            return self._euclidean_distance_km(self.position(), target_position)
    
    def _euclidean_distance_km(self, pos1: tuple, pos2: tuple) -> float:
        """
        Calculate approximate Euclidean distance between two lat/lon points.
        Uses simple conversion from ProtocolConfig.KM_PER_DEGREE.
        """
        if pos1 is None or pos2 is None:
            return 0.0
        lat1, lon1 = pos1
        lat2, lon2 = pos2
        
        # Approximate conversion for lat/lon to km
        # More accurate than pure Euclidean, less complex than Haversine
        lat_diff = (lat2 - lat1) * ProtocolConfig.KM_PER_DEGREE  # km per degree latitude
        lon_diff = (lon2 - lon1) * ProtocolConfig.KM_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
        
        return math.sqrt(lat_diff ** 2 + lon_diff ** 2)
    
    def distance_to_destination(self) -> float:
        """
        Calculate distance to this node's destination in km.
        
        Returns:
            Distance in kilometers, or 0.0 if no destination set
        """
        if self.destination is None:
            return 0.0
        return self.distance_to(self.destination)
    
    def energy_to(self, target_position: tuple) -> float:
        """
        Calculate energy required to reach a target position.
        
        Args:
            target_position: (lat, lon) tuple
            
        Returns:
            Energy in kWh
        """
        distance_km = self.distance_to(target_position)
        return distance_km * ProtocolConfig.ENERGY_CONSUMPTION_RATE
    
    def energy_to_destination(self) -> float:
        """
        Calculate energy required to reach this node's destination.
        
        Returns:
            Energy in kWh, or 0.0 if no destination set
        """
        if self.destination is None:
            return 0.0
        return self.energy_to(self.destination)
    
    def shareable_energy(self) -> float:
        """
        Calculate energy available to share with other nodes.
        
        shareable = battery_energy - energy_to_destination - min_energy
        
        Returns:
            Energy in kWh that can be shared (may be negative if critically low)
        """
        return self.battery_energy_kwh - self.energy_to_destination() - self.min_energy_kwh
    
    def direction_vector(self) -> tuple:
        """
        Calculate normalized direction vector from current position to destination.
        Used for route alignment calculations (dot product).
        
        Returns:
            Normalized (dx, dy) tuple, or (0.0, 0.0) if no destination
        """
        if self.destination is None:
            return (0.0, 0.0)
        
        lat1, lon1 = self.position()
        lat2, lon2 = self.destination
        
        # Calculate direction in km space
        dx = (lon2 - lon1) * ProtocolConfig.KM_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
        dy = (lat2 - lat1) * ProtocolConfig.KM_PER_DEGREE
        
        # Normalize
        magnitude = math.sqrt(dx ** 2 + dy ** 2)
        if magnitude < ProtocolConfig.FLOAT_EPSILON:  # Avoid division by zero
            return (0.0, 0.0)
        
        return (dx / magnitude, dy / magnitude)
    
    def can_reach_destination(self) -> bool:
        """
        Check if this node has enough energy to reach its destination.
        
        Returns:
            True if battery_energy >= energy_to_destination + min_energy
        """
        required = self.energy_to_destination() + self.min_energy_kwh
        return self.battery_energy_kwh >= required

    # --- Connection Management ---

    def add_connection(self, node, edge):
        if node not in self.connections_list:
            self.connections_list[node] = edge
        return True

    def remove_connection(self, node):
        if node in self.connections_list:
            del self.connections_list[node]
            return True
        return False
    
    def prepare_data_for_dijkstra(self):

        # 1. Determine how many nodes we have
        V = self.platoon.node_number
        
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

        dist = [float('inf')] * V

        # Distance from source to itself is 0
        dist[src] = 0
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
                    heapq.heappush(pq, (dist[v], v))

        # Return the final shortest distances from the source
        return dist
