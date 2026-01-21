"""
Edge class for modeling wireless charging connections between nodes.

In a platoon, edges represent potential wireless charging links between
any two members. Edge efficiency follows an inverse-square model based
on physical distance, modeling real-world wireless power transfer.
"""

import math
from typing import Optional, TYPE_CHECKING

# Import ProtocolConfig for constants
try:
    from src.protocol.config import ProtocolConfig
except ImportError:
    # Fallback defaults if config not available
    class ProtocolConfig:
        EDGE_EFFICIENCY_SCALE = 0.1
        EDGE_MAX_RANGE_M = 10.0
        EDGE_MIN_EFFICIENCY = 0.1
        EDGE_WEIGHT_DISTANCE = 0.4
        EDGE_WEIGHT_ENERGY_LOSS = 0.3
        EDGE_WEIGHT_TIME = 0.3
        FLOAT_EPSILON = 1e-9

if TYPE_CHECKING:
    from src.core.node import Node


class Edge:
    """
    Represents a wireless charging connection between two Nodes.
    
    Used for modeling intra-platoon energy transfer where:
    - Any member can potentially charge any other member
    - Transfer efficiency degrades with distance (inverse-square)
    - Dijkstra uses edge costs to find optimal energy paths
    
    Efficiency Model:
        efficiency = hardware_efficiency * distance_efficiency
        distance_efficiency = 1 / (1 + SCALE * distance²)
    
    Cost Model:
        cost = w1*distance + w2*(1-efficiency) + w3*transfer_time
    """

    def __init__(self, source: 'Node', destination: 'Node', distance: float = 0.0):
        """
        Initialize an edge between two nodes.
        
        Args:
            source: Node providing energy
            destination: Node receiving energy
            distance: Physical distance between nodes in meters
        """
        self.source = source
        self.destination = destination
        self.distance = distance  # meters
        
        # Efficiency components
        self.hardware_efficiency = self._calculate_hardware_efficiency()
        self.distance_efficiency = self._calculate_distance_efficiency()
        self.transfer_efficiency = self.hardware_efficiency * self.distance_efficiency
        
        # Transfer tracking
        self.energy_loss = 0.0  # kWh lost in last transfer
        self.expected_transfer_time = 0.0  # seconds
        self.current_load = 0.0  # kW currently being transferred
        
        # Cost (computed after all components set)
        self.edge_cost = self.calculate_cost()
    
    def _calculate_hardware_efficiency(self) -> float:
        """
        Calculate efficiency based on node hardware limits.
        
        Returns ratio of destination input capacity vs source output capacity.
        """
        source_out = getattr(self.source, 'max_transfer_rate_out', 50.0)
        dest_in = getattr(self.destination, 'max_transfer_rate_in', 50.0)
        
        if source_out <= 0 or dest_in <= 0:
            return 0.0
        
        efficiency = dest_in / max(source_out, dest_in)
        return min(max(efficiency, 0.0), 1.0)
    
    def _calculate_distance_efficiency(self) -> float:
        """
        Calculate efficiency based on physical distance using inverse-square model.
        
        efficiency = 1 / (1 + SCALE * distance²)
        
        At distance=0: 100% efficiency
        At distance=3m (with scale=0.1): ~53% efficiency
        At distance=10m (with scale=0.1): ~9% efficiency
        """
        if self.distance <= 0:
            return 1.0
        
        if self.distance > ProtocolConfig.EDGE_MAX_RANGE_M:
            return 0.0  # Beyond max range
        
        scale = ProtocolConfig.EDGE_EFFICIENCY_SCALE
        efficiency = 1.0 / (1.0 + scale * self.distance * self.distance)
        
        # Clamp to minimum useful efficiency
        if efficiency < ProtocolConfig.EDGE_MIN_EFFICIENCY:
            return 0.0
        
        return efficiency
    
    def update_distance(self, new_distance: float) -> float:
        """
        Update the edge distance and recalculate efficiency.
        
        Called when platoon formation changes (vehicles reposition).
        
        Args:
            new_distance: New physical distance in meters
            
        Returns:
            Updated transfer efficiency
        """
        self.distance = new_distance
        self.distance_efficiency = self._calculate_distance_efficiency()
        self.transfer_efficiency = self.hardware_efficiency * self.distance_efficiency
        self.edge_cost = self.calculate_cost()
        return self.transfer_efficiency
    
    def update_expected_transfer_time(self, requested_energy_kwh: float) -> float:
        """
        Calculate expected transfer time for requested energy.
        
        Time = Energy / Power, accounting for efficiency losses.
        
        Args:
            requested_energy_kwh: Amount of energy to transfer
            
        Returns:
            Expected transfer time in seconds
        """
        source_out = getattr(self.source, 'max_transfer_rate_out', 50.0)
        dest_in = getattr(self.destination, 'max_transfer_rate_in', 50.0)
        
        max_power = min(source_out, dest_in)
        
        if max_power <= ProtocolConfig.FLOAT_EPSILON or self.transfer_efficiency <= 0:
            self.expected_transfer_time = float('inf')
            return self.expected_transfer_time
        
        # Effective power after efficiency losses
        effective_power = max_power * self.transfer_efficiency
        
        # Time in hours * 3600 = seconds
        self.expected_transfer_time = (requested_energy_kwh / effective_power) * 3600.0
        
        # Update energy loss estimate
        energy_delivered = requested_energy_kwh
        energy_required = requested_energy_kwh / max(self.transfer_efficiency, ProtocolConfig.FLOAT_EPSILON)
        self.energy_loss = energy_required - energy_delivered
        
        self.edge_cost = self.calculate_cost()
        return self.expected_transfer_time
    
    def calculate_cost(self) -> float:
        """
        Calculate weighted edge cost for Dijkstra pathfinding.
        
        Cost factors:
        - Distance (encourages close formations)
        - Efficiency loss (encourages efficient transfers)
        - Transfer time (encourages fast transfers)
        
        Lower cost = better edge for energy transfer.
        """
        w1 = ProtocolConfig.EDGE_WEIGHT_DISTANCE
        w2 = ProtocolConfig.EDGE_WEIGHT_ENERGY_LOSS
        w3 = ProtocolConfig.EDGE_WEIGHT_TIME
        
        # Normalize distance (0-10m range)
        normalized_distance = self.distance / max(ProtocolConfig.EDGE_MAX_RANGE_M, 1.0)
        
        # Efficiency penalty (1 - efficiency, so 0 = perfect, 1 = unusable)
        efficiency_penalty = 1.0 - self.transfer_efficiency
        
        # Normalize time (assume 300s = 5min is high)
        normalized_time = min(self.expected_transfer_time / 300.0, 1.0) if self.expected_transfer_time < float('inf') else 1.0
        
        cost = (w1 * normalized_distance + 
                w2 * efficiency_penalty + 
                w3 * normalized_time)
        
        return cost
    
    def is_usable(self) -> bool:
        """
        Check if this edge is usable for energy transfer.
        
        Returns:
            True if efficiency is above minimum threshold
        """
        return self.transfer_efficiency >= ProtocolConfig.EDGE_MIN_EFFICIENCY
    
    def get_max_transfer_rate(self) -> float:
        """
        Get maximum effective transfer rate through this edge.
        
        Returns:
            Effective power in kW, accounting for efficiency
        """
        source_out = getattr(self.source, 'max_transfer_rate_out', 50.0)
        dest_in = getattr(self.destination, 'max_transfer_rate_in', 50.0)
        
        max_power = min(source_out, dest_in)
        return max_power * self.transfer_efficiency
    
    def __repr__(self) -> str:
        src_id = getattr(self.source, 'node_id', b'???')
        dst_id = getattr(self.destination, 'node_id', b'???')
        src_hex = src_id.hex()[:6] if isinstance(src_id, bytes) else str(src_id)
        dst_hex = dst_id.hex()[:6] if isinstance(dst_id, bytes) else str(dst_id)
        return f"Edge({src_hex}→{dst_hex}, d={self.distance:.1f}m, η={self.transfer_efficiency:.2f})"
