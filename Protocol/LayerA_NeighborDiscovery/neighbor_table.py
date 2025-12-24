from typing import Dict, Set
from Node import Node
import time

class NeighborTable:
    def __init__(self, context):
        self.context = context
        self.neighbors: Dict[bytes, Node] = {}
        self.NEIGHBOR_TIMEOUT = 5.0 # seconds

    def update_neighbor(self, node_id: bytes, attrs: dict, two_hop_list: list):
        current_time = self.context.current_time
        
        if node_id not in self.neighbors:
            self.neighbors[node_id] = Node(
                node_id=node_id, 
                battery_capacity_kwh=attrs.get('battery_capacity_kwh', 100.0),
                battery_energy_kwh=attrs.get('battery_energy_kwh', 50.0),
                min_energy_kwh=attrs.get('min_energy_kwh', 10.0),
                max_transfer_rate_in=attrs.get('max_transfer_rate_in', 50.0),
                max_transfer_rate_out=attrs.get('max_transfer_rate_out', 50.0),
                latitude=attrs.get('latitude', 0.0),
                longitude=attrs.get('longitude', 0.0),
                velocity=attrs.get('velocity', 0.0),
                battery_health=attrs.get('battery_health', 1.0),
                # QoS Metrics
                etx=attrs.get('etx', 1.0),
                willingness=attrs.get('willingness', 3),
                lane_weight=attrs.get('lane_weight', 0.5),
                link_stability=attrs.get('link_stability', 1.0)
            )
            
        node = self.neighbors[node_id]
        node.last_seen = current_time
        
        # Update fields dynamically
        for key, val in attrs.items():
            if hasattr(node, key):
                setattr(node, key, val)
        
        # Update Topology
        node.two_hop_neighbors = set(two_hop_list)
        node.link_status = "SYM" 

    def get_one_hop_set(self) -> Set[bytes]:
        self._clean_stale()
        return set(self.neighbors.keys())

    def get_two_hop_set(self) -> Set[bytes]:
        self._clean_stale()
        two_hops = set()
        for node in self.neighbors.values():
            two_hops.update(node.two_hop_neighbors)
        
        # Remove self and direct neighbors
        two_hops.discard(self.context.node_id)
        two_hops.difference_update(self.neighbors.keys())
        return two_hops

    def _clean_stale(self):
        current_time = self.context.current_time
        to_remove = []
        for nid, node in self.neighbors.items():
            if current_time - node.last_seen > self.NEIGHBOR_TIMEOUT:
                to_remove.append(nid)
        for nid in to_remove:
            del self.neighbors[nid]
