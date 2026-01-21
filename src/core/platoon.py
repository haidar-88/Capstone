import math
import uuid
import logging
import heapq
from typing import Dict, List, Tuple, Optional, TYPE_CHECKING

# Import ProtocolConfig for constants
try:
    from src.protocol.config import ProtocolConfig
except ImportError:
    # Fallback if config not available (shouldn't happen in normal usage)
    class ProtocolConfig:
        KM_PER_DEGREE = 111.0
        FLOAT_EPSILON = 1e-9
        EDGE_EFFICIENCY_SCALE = 0.1
        EDGE_MAX_RANGE_M = 10.0
        EDGE_MIN_EFFICIENCY = 0.1
        FORMATION_UPDATE_INTERVAL = 2.0

from src.core.edge import Edge

if TYPE_CHECKING:
    from src.core.node import Node

logger = logging.getLogger(__name__)


class Platoon:
    """
    Represents a Platoon of Nodes.
    A platoon is a group of up to 6 EVs traveling together, with one acting as
    the Platoon Head (PH) that provides energy to members.
    """

    def __init__(self, head_node=None, platoon_id: bytes = None):
        """
        Initialize a new platoon.
        
        Args:
            head_node: The node that will be the platoon head (optional)
            platoon_id: Unique identifier for this platoon (auto-generated if None)
        """
        # Unique platoon identifier (6 bytes like node IDs)
        if platoon_id is None:
            self.platoon_id = uuid.uuid4().bytes[:6]
        else:
            self.platoon_id = platoon_id
        
        # Platoon head reference
        self.head_node = head_node
        self.head_id = head_node.node_id if head_node else None
        
        # Member tracking
        self.nodes = []
        self.node_number = 0
        self.max_nodes = 6
        
        # If head is provided, add as first member
        if head_node:
            self.nodes.append(head_node)
            self.node_number = 1
        
        # Energy tracking
        self.total_energy_demand = 0.0
        self.available_charger_power = 0.0
        
        # Destination and route
        self.common_destination = None  # (lat, lon) tuple - shared destination
        
        # Mobility pattern (expected duration platoon stays together in seconds)
        self.platoon_mobility_pattern = 0.0
        
        # Member positions relative to head (for topology)
        # Maps node_id -> relative_index (0 = head, 1 = first follower, etc.)
        self.member_positions = {}
        
        # ==========================================================================
        # Edge Graph for Energy Path Optimization
        # ==========================================================================
        
        # 2D positions of members within platoon formation (x, y in meters)
        # x = lateral offset (positive = right), y = longitudinal offset (positive = behind head)
        self.member_2d_positions: Dict[bytes, Tuple[float, float]] = {}
        
        # Edge graph: key = (source_id, dest_id), value = Edge object
        # Contains edges between all pairs of members for Dijkstra
        self.edge_graph: Dict[Tuple[bytes, bytes], Edge] = {}
        
        # Target formation positions (computed by optimization)
        # Maps node_id -> target (x, y) position
        self.target_formation: Dict[bytes, Tuple[float, float]] = {}
        
        # Timestamp of last formation update
        self.last_formation_update: float = 0.0
    
    def can_add_node(self) -> bool:
        """Check if platoon has capacity for more members."""
        return self.node_number < self.max_nodes
    
    def available_slots(self) -> int:
        """Return number of available slots in the platoon."""
        return self.max_nodes - self.node_number

    def add_node(self, node) -> bool:
        """
        Add a node to the platoon.
        
        Args:
            node: Node to add as a member
            
        Returns:
            True if added successfully, False if platoon is full
        """
        if not self.can_add_node():
            return False
            
        if node not in self.nodes:
            self.nodes.append(node)
            self.node_number += 1
            self.member_positions[node.node_id] = self.node_number - 1
            
            # Link node back to platoon
            node.platoon = self
            
            self.update_total_energy_demand()
            self.update_available_charger_power()
        return True

    def remove_node(self, node) -> bool:
        """
        Remove a node from the platoon (deterministic, self-correcting).
        
        Behavior:
        - If node is head: automatically triggers handoff to best candidate
        - If no handoff candidate: marks platoon for disbandment
        - If node not in platoon: no-op (idempotent)
        
        Args:
            node: Node to remove
            
        Returns:
            True if removal completed or auto-corrected
            False only for invalid input (None or wrong type)
        
        State Changes:
        - Head removal → auto-handoff → old head removed
        - No candidates → platoon member count decreases
        - Normal member → immediate removal
        """
        if node is None or node not in self.nodes:
            return False  # Invalid input or not in platoon
        
        # HEAD REMOVAL: deterministic auto-correction
        if node == self.head_node:
            candidate = self.find_best_handoff_candidate()
            if candidate:
                # Auto-handoff preserves invariant
                logger.info(f"Auto-handoff: {node.node_id.hex()} → {candidate.node_id.hex()}")
                self.set_head(candidate)
                # Now remove old head (safe, no longer head)
                self._remove_member_internal(node)
                logger.info(f"Head {node.node_id.hex()} removed after auto-handoff")
            else:
                # No candidates → just remove head (platoon effectively disbanded)
                logger.warning(f"Removing head {node.node_id.hex()} with no handoff candidate")
                self._remove_member_internal(node)
                self.head_node = None
                self.head_id = None
                logger.info(f"Platoon {self.platoon_id.hex()} has no head (disbanded)")
            return True  # Operation handled deterministically
        
        # NORMAL MEMBER REMOVAL
        self._remove_member_internal(node)
        return True
    
    def _remove_member_internal(self, node):
        """
        Internal: remove member (assumes preconditions checked).
        Does not handle head removal logic - caller must ensure invariants.
        """
        if node in self.nodes:
            self.nodes.remove(node)
            self.node_number -= 1
            
            # Remove from positions and reindex
            if node.node_id in self.member_positions:
                del self.member_positions[node.node_id]
            self._reindex_positions()
            
            # Unlink node from platoon
            node.platoon = None
            
            self.update_total_energy_demand()
            self.update_available_charger_power()
    
    def _reindex_positions(self):
        """Reindex member positions after removal."""
        self.member_positions = {}
        for idx, node in enumerate(self.nodes):
            self.member_positions[node.node_id] = idx
    
    def get_member_by_id(self, node_id):
        """Find a member node by its ID."""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None
    
    def update_available_charger_power(self):
        """Update the total power available for charging from head."""
        if self.head_node:
            self.available_charger_power = self.head_node.max_transfer_rate_out
        else:
            self.available_charger_power = 0.0

    def update_total_energy_demand(self):
        """Calculate total energy demand from all non-head members."""
        total_demand = 0.0
        for node in self.nodes:
            if node != self.head_node:
                # Energy needed = energy_to_destination + min_reserve
                needed = node.energy_to_destination() + node.min_energy_kwh
                current = node.battery_energy_kwh
                if needed > current:
                    total_demand += (needed - current)
        self.total_energy_demand = total_demand
    
    def total_shareable_energy(self) -> float:
        """
        Calculate total shareable energy from all members.
        This is the sum of energy that can be shared (above what's needed for destination).
        
        Returns:
            Total shareable energy in kWh
        """
        total = 0.0
        for node in self.nodes:
            shareable = node.shareable_energy()
            if shareable > 0:
                total += shareable
        return total
    
    def head_shareable_energy(self) -> float:
        """
        Calculate shareable energy from the platoon head only.
        
        Returns:
            Head's shareable energy in kWh, or 0 if no head
        """
        if self.head_node:
            return max(0.0, self.head_node.shareable_energy())
        return 0.0
    
    def direction_vector(self) -> tuple:
        """
        Calculate the platoon's direction vector based on common destination.
        Uses head's position if available.
        
        Returns:
            Normalized (dx, dy) tuple, or (0.0, 0.0) if no destination
        """
        if self.head_node and self.common_destination:
            lat1, lon1 = self.head_node.position()
            lat2, lon2 = self.common_destination
            
            dx = (lon2 - lon1) * ProtocolConfig.KM_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
            dy = (lat2 - lat1) * ProtocolConfig.KM_PER_DEGREE
            
            magnitude = math.sqrt(dx ** 2 + dy ** 2)
            if magnitude < ProtocolConfig.FLOAT_EPSILON:
                return (0.0, 0.0)
            
            return (dx / magnitude, dy / magnitude)
        
        # Fallback: use head's direction if it has a destination
        if self.head_node:
            return self.head_node.direction_vector()
        
        return (0.0, 0.0)
    
    def head_position(self) -> tuple:
        """Get the position of the platoon head."""
        if self.head_node:
            return self.head_node.position()
        return (0.0, 0.0)
    
    def head_velocity(self) -> float:
        """Get the velocity of the platoon head in m/s."""
        if self.head_node:
            return self.head_node.velocity
        return 0.0
    
    def set_head(self, new_head) -> bool:
        """
        Change the platoon head to a new node.
        Used for handoff when current head's energy drops.
        
        Args:
            new_head: Node to become the new head (must be in platoon)
            
        Returns:
            True if handoff successful, False otherwise
        """
        if new_head not in self.nodes:
            return False
        
        # Update old head
        if self.head_node:
            self.head_node.is_leader = False
        
        # Set new head
        self.head_node = new_head
        self.head_id = new_head.node_id
        new_head.is_leader = True
        
        # Reorder nodes so head is first
        self.nodes.remove(new_head)
        self.nodes.insert(0, new_head)
        self._reindex_positions()
        
        self.update_available_charger_power()
        return True
    
    def find_best_handoff_candidate(self):
        """
        Find the best candidate to become the new platoon head.
        Chooses the member with highest shareable energy.
        
        Returns:
            Node with highest shareable energy, or None if no suitable candidate
        """
        best_candidate = None
        best_energy = 0.0
        
        for node in self.nodes:
            if node != self.head_node:
                shareable = node.shareable_energy()
                if shareable > best_energy:
                    best_energy = shareable
                    best_candidate = node
        
        return best_candidate
    
    def get_topology_vector(self) -> list:
        """
        Get the platoon topology as an ordered list of member IDs.
        
        Returns:
            List of (node_id, relative_index) tuples
        """
        return [(node.node_id, idx) for idx, node in enumerate(self.nodes)]
    
    def is_member(self, node) -> bool:
        """Check if a node is a member of this platoon."""
        return node in self.nodes
    
    def is_head(self, node) -> bool:
        """Check if a node is the head of this platoon."""
        return node == self.head_node
    
    # ==========================================================================
    # Edge Graph and Formation Methods
    # ==========================================================================
    
    def initialize_2d_positions(self, formation_type: str = 'convoy') -> None:
        """
        Initialize 2D positions for all members based on formation type.
        
        Args:
            formation_type: 'convoy' (single-file), 'staggered', or 'cluster'
        """
        if formation_type == 'convoy':
            # Single-file formation: all members behind each other
            # Head at (0, 0), each follower 3m behind
            spacing = 3.0  # meters between vehicles
            for idx, node in enumerate(self.nodes):
                x = 0.0
                y = idx * spacing  # positive y = behind head
                self.member_2d_positions[node.node_id] = (x, y)
                
        elif formation_type == 'staggered':
            # Staggered formation: alternate left/right
            longitudinal_spacing = 2.5
            lateral_offset = 1.5
            for idx, node in enumerate(self.nodes):
                x = lateral_offset * (1 if idx % 2 == 1 else -1) if idx > 0 else 0.0
                y = idx * longitudinal_spacing
                self.member_2d_positions[node.node_id] = (x, y)
                
        elif formation_type == 'cluster':
            # Clustered formation: minimize average distance
            # Arrange in a tight cluster around the head
            if len(self.nodes) <= 1:
                if self.nodes:
                    self.member_2d_positions[self.nodes[0].node_id] = (0.0, 0.0)
            else:
                # Head at center
                self.member_2d_positions[self.nodes[0].node_id] = (0.0, 0.0)
                # Others in a circle around head
                radius = 2.0
                for idx, node in enumerate(self.nodes[1:], start=1):
                    angle = (2 * math.pi * (idx - 1)) / (len(self.nodes) - 1)
                    x = radius * math.cos(angle)
                    y = radius * math.sin(angle)
                    self.member_2d_positions[node.node_id] = (x, y)
        
        # Set initial target formation to current positions
        self.target_formation = dict(self.member_2d_positions)
        
        # Build edge graph with new positions
        self.build_edge_graph()
    
    def update_member_position(self, node_id: bytes, position: Tuple[float, float]) -> None:
        """
        Update a single member's 2D position and recalculate affected edges.
        
        Args:
            node_id: ID of the member to update
            position: New (x, y) position in meters
        """
        if node_id not in [n.node_id for n in self.nodes]:
            return
        
        old_position = self.member_2d_positions.get(node_id)
        self.member_2d_positions[node_id] = position
        
        # Update all edges involving this node
        for other_node in self.nodes:
            if other_node.node_id == node_id:
                continue
            
            other_pos = self.member_2d_positions.get(other_node.node_id)
            if other_pos is None:
                continue
            
            new_distance = self._calculate_distance(position, other_pos)
            
            # Update both directions
            edge_key_1 = (node_id, other_node.node_id)
            edge_key_2 = (other_node.node_id, node_id)
            
            if edge_key_1 in self.edge_graph:
                self.edge_graph[edge_key_1].update_distance(new_distance)
            if edge_key_2 in self.edge_graph:
                self.edge_graph[edge_key_2].update_distance(new_distance)
    
    def build_edge_graph(self) -> None:
        """
        Build the complete edge graph between all pairs of members.
        
        Creates N*(N-1) directed edges (both directions for each pair)
        since energy can flow either direction.
        """
        self.edge_graph.clear()
        
        # Ensure all members have positions
        for node in self.nodes:
            if node.node_id not in self.member_2d_positions:
                # Default position based on index
                idx = self.member_positions.get(node.node_id, 0)
                self.member_2d_positions[node.node_id] = (0.0, idx * 3.0)
        
        # Create edges between all pairs
        for i, src_node in enumerate(self.nodes):
            src_pos = self.member_2d_positions.get(src_node.node_id, (0.0, 0.0))
            
            for j, dst_node in enumerate(self.nodes):
                if i == j:
                    continue
                
                dst_pos = self.member_2d_positions.get(dst_node.node_id, (0.0, 0.0))
                distance = self._calculate_distance(src_pos, dst_pos)
                
                edge = Edge(src_node, dst_node, distance)
                edge_key = (src_node.node_id, dst_node.node_id)
                self.edge_graph[edge_key] = edge
        
        logger.debug(f"Built edge graph with {len(self.edge_graph)} edges for {len(self.nodes)} members")
    
    def update_edge_distances(self) -> None:
        """
        Recalculate all edge distances based on current 2D positions.
        Called when formation changes.
        """
        for (src_id, dst_id), edge in self.edge_graph.items():
            src_pos = self.member_2d_positions.get(src_id)
            dst_pos = self.member_2d_positions.get(dst_id)
            
            if src_pos and dst_pos:
                new_distance = self._calculate_distance(src_pos, dst_pos)
                edge.update_distance(new_distance)
    
    def _calculate_distance(self, pos1: Tuple[float, float], pos2: Tuple[float, float]) -> float:
        """Calculate Euclidean distance between two 2D positions."""
        dx = pos2[0] - pos1[0]
        dy = pos2[1] - pos1[1]
        return math.sqrt(dx * dx + dy * dy)
    
    def get_edge(self, src_id: bytes, dst_id: bytes) -> Optional[Edge]:
        """
        Get the edge between two nodes.
        
        Args:
            src_id: Source node ID
            dst_id: Destination node ID
            
        Returns:
            Edge object or None if not found
        """
        return self.edge_graph.get((src_id, dst_id))
    
    def get_usable_edges(self) -> List[Edge]:
        """
        Get all edges with efficiency above the minimum threshold.
        
        Returns:
            List of usable Edge objects
        """
        return [edge for edge in self.edge_graph.values() if edge.is_usable()]
    
    # ==========================================================================
    # Dijkstra Energy Path Finding
    # ==========================================================================
    
    def get_energy_surplus_nodes(self) -> List['Node']:
        """
        Get nodes with energy surplus (shareable_energy > 0).
        
        Returns:
            List of nodes that can provide energy
        """
        surplus_nodes = []
        for node in self.nodes:
            if node.shareable_energy() > 0:
                surplus_nodes.append(node)
        return surplus_nodes
    
    def get_energy_deficit_nodes(self) -> List['Node']:
        """
        Get nodes with energy deficit (need charging).
        
        A node has deficit if it doesn't have enough energy to reach
        its destination plus minimum reserve.
        
        Returns:
            List of nodes that need energy
        """
        deficit_nodes = []
        for node in self.nodes:
            needed = node.energy_to_destination() + node.min_energy_kwh
            current = node.battery_energy_kwh
            if needed > current:
                deficit_nodes.append(node)
        return deficit_nodes
    
    def dijkstra_energy_paths(self) -> Dict[bytes, Tuple[List[bytes], float, float]]:
        """
        Find optimal energy transfer paths from surplus to deficit nodes.
        
        Uses Dijkstra's algorithm where edge cost considers:
        - Transfer efficiency (inverse-square with distance)
        - Available energy at source nodes
        
        Returns:
            Dict mapping deficit_node_id -> (path, total_cost, deliverable_energy)
            path: List of node_ids from source to destination
            total_cost: Cumulative edge cost
            deliverable_energy: Energy that can be delivered accounting for losses
        """
        if not self.edge_graph:
            self.build_edge_graph()
        
        surplus_nodes = self.get_energy_surplus_nodes()
        deficit_nodes = self.get_energy_deficit_nodes()
        
        if not surplus_nodes or not deficit_nodes:
            return {}
        
        result = {}
        
        for deficit_node in deficit_nodes:
            # Run Dijkstra from this deficit node to find best surplus source
            best_path, best_cost, best_energy = self._dijkstra_to_sources(
                deficit_node.node_id, 
                [n.node_id for n in surplus_nodes]
            )
            
            if best_path:
                result[deficit_node.node_id] = (best_path, best_cost, best_energy)
        
        return result
    
    def _dijkstra_to_sources(
        self, 
        target_id: bytes, 
        source_ids: List[bytes]
    ) -> Tuple[Optional[List[bytes]], float, float]:
        """
        Run Dijkstra from target (deficit node) backwards to find best source.
        
        We run "backwards" because we want to find the path FROM sources TO target,
        but it's equivalent to finding the shortest path from target to any source.
        
        Args:
            target_id: ID of the node needing energy
            source_ids: List of node IDs that can provide energy
            
        Returns:
            (path from source to target, total_cost, deliverable_energy)
        """
        # Priority queue: (cost, node_id, path, cumulative_efficiency)
        pq = [(0.0, target_id, [target_id], 1.0)]
        visited = set()
        
        source_set = set(source_ids)
        
        while pq:
            cost, current_id, path, cum_efficiency = heapq.heappop(pq)
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            # If we reached a source, calculate deliverable energy
            if current_id in source_set:
                source_node = self.get_member_by_id(current_id)
                if source_node:
                    # Energy that can be delivered = source's shareable * cumulative efficiency
                    deliverable = source_node.shareable_energy() * cum_efficiency
                    # Reverse path so it goes source -> target
                    return (list(reversed(path)), cost, deliverable)
            
            # Explore neighbors (all nodes that can transfer TO current)
            # This means we look at edges where current is the destination
            for (src_id, dst_id), edge in self.edge_graph.items():
                if dst_id != current_id:
                    continue
                if src_id in visited:
                    continue
                if not edge.is_usable():
                    continue
                
                new_cost = cost + edge.edge_cost
                new_efficiency = cum_efficiency * edge.transfer_efficiency
                new_path = path + [src_id]
                
                heapq.heappush(pq, (new_cost, src_id, new_path, new_efficiency))
        
        return (None, float('inf'), 0.0)
    
    def find_best_energy_path(
        self, 
        source_id: bytes, 
        target_id: bytes
    ) -> Tuple[Optional[List[bytes]], float, float]:
        """
        Find the optimal path for energy transfer between two specific nodes.
        
        Args:
            source_id: ID of the energy-providing node
            target_id: ID of the energy-receiving node
            
        Returns:
            (path, total_cost, efficiency) where efficiency is cumulative
        """
        if source_id == target_id:
            return ([source_id], 0.0, 1.0)
        
        if not self.edge_graph:
            self.build_edge_graph()
        
        # Priority queue: (cost, node_id, path, cumulative_efficiency)
        pq = [(0.0, source_id, [source_id], 1.0)]
        visited = set()
        
        while pq:
            cost, current_id, path, cum_efficiency = heapq.heappop(pq)
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            # Reached target
            if current_id == target_id:
                return (path, cost, cum_efficiency)
            
            # Explore outgoing edges
            for (src_id, dst_id), edge in self.edge_graph.items():
                if src_id != current_id:
                    continue
                if dst_id in visited:
                    continue
                if not edge.is_usable():
                    continue
                
                new_cost = cost + edge.edge_cost
                new_efficiency = cum_efficiency * edge.transfer_efficiency
                new_path = path + [dst_id]
                
                heapq.heappush(pq, (new_cost, dst_id, new_path, new_efficiency))
        
        return (None, float('inf'), 0.0)
    
    def calculate_energy_distribution_plan(self) -> Dict[bytes, Dict[str, any]]:
        """
        Calculate a complete energy distribution plan for the platoon.
        
        Returns:
            Dict mapping each deficit node to its distribution plan:
            {
                deficit_node_id: {
                    'source_id': bytes,
                    'path': List[bytes],
                    'energy_needed': float,
                    'energy_deliverable': float,
                    'efficiency': float
                }
            }
        """
        paths = self.dijkstra_energy_paths()
        
        plan = {}
        for deficit_id, (path, cost, deliverable) in paths.items():
            deficit_node = self.get_member_by_id(deficit_id)
            if not deficit_node:
                continue
            
            needed = deficit_node.energy_to_destination() + deficit_node.min_energy_kwh
            current = deficit_node.battery_energy_kwh
            energy_needed = max(0.0, needed - current)
            
            # Calculate cumulative efficiency from path
            cumulative_eff = 1.0
            for i in range(len(path) - 1):
                edge = self.get_edge(path[i], path[i + 1])
                if edge:
                    cumulative_eff *= edge.transfer_efficiency
            
            plan[deficit_id] = {
                'source_id': path[0] if path else None,
                'path': path,
                'energy_needed': energy_needed,
                'energy_deliverable': deliverable,
                'efficiency': cumulative_eff
            }
        
        return plan
    
    # ==========================================================================
    # Formation Optimization
    # ==========================================================================
    
    def compute_optimal_formation(
        self, 
        current_time: float,
        constraints: Optional[Dict] = None
    ) -> Dict[bytes, Tuple[float, float]]:
        """
        Compute optimal 2D positions for platoon members to maximize energy transfer efficiency.
        
        The algorithm:
        1. Identify surplus and deficit nodes
        2. Position deficit nodes closer to their best energy sources
        3. Maintain minimum safe distances between vehicles
        4. Respect physical constraints (lane width, following distance)
        
        Args:
            current_time: Current simulation time
            constraints: Optional dict with 'min_distance', 'max_lateral', 'max_longitudinal'
            
        Returns:
            Dict mapping node_id -> target (x, y) position
        """
        # Rate limiting: don't recompute too frequently
        if (current_time - self.last_formation_update) < ProtocolConfig.FORMATION_UPDATE_INTERVAL:
            return self.target_formation
        
        self.last_formation_update = current_time
        
        # Default constraints
        if constraints is None:
            constraints = {
                'min_distance': 2.0,       # Minimum distance between any two vehicles (m)
                'max_lateral': 3.5,        # Max lateral offset from center (m) - lane width
                'max_longitudinal': 20.0,  # Max distance from head (m)
            }
        
        surplus_nodes = self.get_energy_surplus_nodes()
        deficit_nodes = self.get_energy_deficit_nodes()
        
        if not surplus_nodes or not deficit_nodes:
            # No optimization needed, keep current formation
            return self.target_formation
        
        # Start with head at origin
        new_formation = {}
        if self.head_node:
            new_formation[self.head_node.node_id] = (0.0, 0.0)
        
        # Sort deficit nodes by urgency (lowest battery first)
        deficit_sorted = sorted(
            deficit_nodes, 
            key=lambda n: n.battery_energy_kwh / max(n.battery_capacity_kwh, 0.01)
        )
        
        # Sort surplus nodes by available energy (highest first)
        surplus_sorted = sorted(
            surplus_nodes,
            key=lambda n: n.shareable_energy(),
            reverse=True
        )
        
        # Position surplus nodes close to head (they should be stable)
        surplus_positions = {}
        for idx, surplus_node in enumerate(surplus_sorted):
            if surplus_node.node_id == (self.head_node.node_id if self.head_node else None):
                continue  # Head already positioned
            
            # Place surplus nodes in a line behind head, slightly staggered
            y_offset = (idx + 1) * 3.0  # Behind head
            x_offset = 1.0 if idx % 2 == 0 else -1.0  # Alternate sides
            
            surplus_positions[surplus_node.node_id] = (x_offset, y_offset)
            new_formation[surplus_node.node_id] = (x_offset, y_offset)
        
        # Position deficit nodes close to their best source
        for deficit_node in deficit_sorted:
            if deficit_node.node_id in new_formation:
                continue  # Already positioned (might be surplus too)
            
            # Find best source for this deficit node
            best_source_id = None
            best_energy = 0.0
            
            for surplus_node in surplus_sorted:
                if surplus_node.shareable_energy() > best_energy:
                    best_energy = surplus_node.shareable_energy()
                    best_source_id = surplus_node.node_id
            
            if best_source_id and best_source_id in new_formation:
                # Position close to best source
                source_pos = new_formation[best_source_id]
                
                # Try positions around the source
                best_pos = self._find_optimal_position_near(
                    source_pos, 
                    new_formation, 
                    constraints
                )
                new_formation[deficit_node.node_id] = best_pos
            else:
                # Fallback: position at end of convoy
                y_offset = len(new_formation) * 3.0
                new_formation[deficit_node.node_id] = (0.0, y_offset)
        
        # Validate and adjust for constraint violations
        new_formation = self._adjust_for_constraints(new_formation, constraints)
        
        self.target_formation = new_formation
        return new_formation
    
    def _find_optimal_position_near(
        self,
        source_pos: Tuple[float, float],
        existing_positions: Dict[bytes, Tuple[float, float]],
        constraints: Dict
    ) -> Tuple[float, float]:
        """
        Find the best position near a source that doesn't violate constraints.
        
        Uses a simple grid search around the source position.
        """
        min_dist = constraints.get('min_distance', 2.0)
        max_lateral = constraints.get('max_lateral', 3.5)
        
        # Search in expanding rings around source
        best_pos = None
        best_score = float('inf')
        
        # Grid search offsets
        for dy in [min_dist, min_dist * 1.5, min_dist * 2.0]:
            for dx in [0.0, min_dist, -min_dist]:
                candidate = (source_pos[0] + dx, source_pos[1] + dy)
                
                # Check lateral constraint
                if abs(candidate[0]) > max_lateral:
                    continue
                
                # Check minimum distance from all existing positions
                valid = True
                min_existing_dist = float('inf')
                
                for existing_pos in existing_positions.values():
                    dist = self._calculate_distance(candidate, existing_pos)
                    min_existing_dist = min(min_existing_dist, dist)
                    if dist < min_dist:
                        valid = False
                        break
                
                if valid:
                    # Score: prefer closer to source
                    dist_to_source = self._calculate_distance(candidate, source_pos)
                    if dist_to_source < best_score:
                        best_score = dist_to_source
                        best_pos = candidate
        
        if best_pos is None:
            # Fallback: just put behind source
            best_pos = (source_pos[0], source_pos[1] + min_dist * 2)
        
        return best_pos
    
    def _adjust_for_constraints(
        self,
        formation: Dict[bytes, Tuple[float, float]],
        constraints: Dict
    ) -> Dict[bytes, Tuple[float, float]]:
        """
        Adjust formation to satisfy all constraints.
        
        Uses iterative relaxation to resolve conflicts.
        """
        min_dist = constraints.get('min_distance', 2.0)
        max_lateral = constraints.get('max_lateral', 3.5)
        max_longitudinal = constraints.get('max_longitudinal', 20.0)
        
        adjusted = dict(formation)
        
        # Clamp to bounds
        for node_id, (x, y) in adjusted.items():
            x = max(-max_lateral, min(max_lateral, x))
            y = max(0.0, min(max_longitudinal, y))
            adjusted[node_id] = (x, y)
        
        # Resolve minimum distance violations (simple iterative push)
        max_iterations = 10
        for _ in range(max_iterations):
            violations = 0
            
            node_ids = list(adjusted.keys())
            for i, id1 in enumerate(node_ids):
                for id2 in node_ids[i+1:]:
                    pos1 = adjusted[id1]
                    pos2 = adjusted[id2]
                    dist = self._calculate_distance(pos1, pos2)
                    
                    if dist < min_dist and dist > ProtocolConfig.FLOAT_EPSILON:
                        violations += 1
                        # Push apart
                        overlap = min_dist - dist
                        dx = pos2[0] - pos1[0]
                        dy = pos2[1] - pos1[1]
                        magnitude = dist
                        
                        # Normalize and push
                        push_x = (dx / magnitude) * overlap * 0.5
                        push_y = (dy / magnitude) * overlap * 0.5
                        
                        # Move both nodes apart
                        adjusted[id1] = (pos1[0] - push_x, pos1[1] - push_y)
                        adjusted[id2] = (pos2[0] + push_x, pos2[1] + push_y)
            
            if violations == 0:
                break
        
        return adjusted
    
    def apply_formation(self) -> None:
        """
        Apply the target formation to member 2D positions and update edges.
        
        Called after optimization to actually move members to target positions.
        """
        for node_id, target_pos in self.target_formation.items():
            if node_id in self.member_2d_positions:
                self.member_2d_positions[node_id] = target_pos
        
        # Recalculate all edge distances
        self.update_edge_distances()
        
        logger.debug(f"Applied formation, updated {len(self.edge_graph)} edges")
    
    def get_formation_message_data(self) -> bytes:
        """
        Serialize the target formation for transmission in PLATOON_BEACON.
        
        Format: For each member:
            - node_id: 6 bytes
            - x position: 4 bytes (float, big-endian)
            - y position: 4 bytes (float, big-endian)
        
        Returns:
            Serialized formation data
        """
        import struct
        
        data = bytearray()
        
        for node_id, (x, y) in self.target_formation.items():
            # Ensure node_id is exactly 6 bytes
            if len(node_id) >= 6:
                data.extend(node_id[:6])
            else:
                data.extend(node_id.ljust(6, b'\x00'))
            
            # Pack positions as big-endian floats
            data.extend(struct.pack('>f', x))
            data.extend(struct.pack('>f', y))
        
        return bytes(data)
    
    @staticmethod
    def parse_formation_message_data(data: bytes) -> Dict[bytes, Tuple[float, float]]:
        """
        Parse formation data received in PLATOON_BEACON.
        
        Args:
            data: Serialized formation data
            
        Returns:
            Dict mapping node_id -> (x, y) position
        """
        import struct
        
        formation = {}
        entry_size = 6 + 4 + 4  # node_id + x + y
        
        offset = 0
        while offset + entry_size <= len(data):
            node_id = data[offset:offset + 6]
            x = struct.unpack('>f', data[offset + 6:offset + 10])[0]
            y = struct.unpack('>f', data[offset + 10:offset + 14])[0]
            
            formation[node_id] = (x, y)
            offset += entry_size
        
        return formation
    
    def _check_invariants(self) -> bool:
        """
        Check platoon invariants for diagnostics/logging.
        Does NOT prevent operations - they self-correct.
        
        Returns:
            True if all invariants hold
            False if violations detected (logged for diagnostics)
        """
        valid = True
        
        # Invariant: head must be in nodes list
        if self.head_node and self.head_node not in self.nodes:
            logger.error(f"Invariant violation: head {self.head_id.hex() if self.head_id else 'None'} not in nodes list")
            valid = False
        
        # Invariant: node_number must match len(nodes)
        if len(self.nodes) != self.node_number:
            logger.error(f"Invariant violation: node_number {self.node_number} != len(nodes) {len(self.nodes)}")
            valid = False
        
        # Invariant: head should be first in list
        if self.head_node and len(self.nodes) > 0 and self.nodes[0] != self.head_node:
            logger.warning(f"Invariant: head should be first in nodes list")
            valid = False
        
        # Invariant: no duplicates
        if len(self.nodes) != len(set(self.nodes)):
            logger.error(f"Invariant violation: duplicate nodes in list")
            valid = False
        
        return valid
    
    def disband(self) -> bool:
        """
        Safely disband the platoon (deterministic cleanup).
        Removes all members and clears references.
        
        Returns:
            True when disbandment complete
        """
        logger.info(f"Disbanding platoon {self.platoon_id.hex()}")
        
        # Copy nodes list to avoid modification during iteration
        members = list(self.nodes)
        
        # Remove all members
        for node in members:
            self._remove_member_internal(node)
        
        # Clear head references
        self.head_node = None
        self.head_id = None
        
        # Verify empty
        assert len(self.nodes) == 0, "Platoon should be empty after disband"
        assert self.node_number == 0, "Node count should be 0 after disband"
        
        logger.info(f"Platoon {self.platoon_id.hex()} disbanded successfully")
        return True