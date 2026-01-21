"""
Layer D: Platoon Coordination Handler

Handles ongoing platoon management including:
- PLATOON_BEACON reception and processing
- PLATOON_STATUS updates from members
- Formation maintenance and member tracking
- Edge-based formation optimization for energy transfer

Works in conjunction with Layer C's PlatoonHeadHandler which handles
JOIN negotiation and member acceptance.
"""

import struct
import logging
from typing import Dict, Optional, Tuple, TYPE_CHECKING

from src.messages.messages import (
    MessageType, PlatoonBeaconMessage, PlatoonStatusMessage, TLVType
)
from src.protocol.layer_c.states import NodeRole
from src.protocol.node_registry import get_node_name
from src.core.platoon import Platoon

if TYPE_CHECKING:
    from src.protocol.context import MVCCPContext

logger = logging.getLogger('mvccp.layer_d')


class MemberStatus:
    """Tracks status of a platoon member."""
    def __init__(self, node_id: bytes):
        self.node_id = node_id
        self.battery_level: float = 0.0
        self.relative_index: int = 0
        self.receive_rate: float = 0.0
        self.last_update: float = 0.0
        self.position: tuple = (0.0, 0.0)  # GPS position (lat, lon)
        self.formation_position: Tuple[float, float] = (0.0, 0.0)  # 2D position in platoon (x, y meters)
        self.target_formation_position: Optional[Tuple[float, float]] = None  # Target from PH


class PlatoonCoordinationHandler:
    """
    Handles Layer D platoon coordination.
    
    For Platoon Heads:
    - Receives PLATOON_STATUS from members
    - Tracks member battery levels and positions
    - Computes optimal formation using edge-based Dijkstra
    - Broadcasts formation positions in PLATOON_BEACON
    - Coordinates with Layer C PlatoonHeadHandler for beacons
    
    For Platoon Members:
    - Receives PLATOON_BEACON from head
    - Extracts target formation position from beacon
    - Sends PLATOON_STATUS to head
    - Adjusts position toward target for optimal energy transfer
    """
    
    # Timing constants
    STATUS_INTERVAL = 1.0  # seconds between status updates
    BEACON_TIMEOUT = 5.0   # seconds before considering head lost
    
    def __init__(self, context: 'MVCCPContext'):
        """
        Initialize the platoon coordination handler.
        
        Args:
            context: MVCCP protocol context
        """
        self.context = context
        
        # Member tracking (for platoon heads)
        self.platoon_members: Dict[bytes, MemberStatus] = {}
        
        # Beacon tracking (for members)
        self.last_beacon_time: float = 0.0
        self.current_head_id: Optional[bytes] = None
        self.last_status_time: float = 0.0
        
        # Formation tracking (for members)
        self.target_formation_position: Optional[Tuple[float, float]] = None
        self.current_formation_position: Tuple[float, float] = (0.0, 0.0)
        
        # Last computed formation (for heads)
        self.last_formation: Dict[bytes, Tuple[float, float]] = {}
    
    def tick(self, timestamp: float):
        """
        Process a protocol tick.
        
        Args:
            timestamp: Current simulation time
        """
        if self.context.current_platoon is None:
            return
        
        if self.context.is_platoon_head():
            self._tick_as_head(timestamp)
        elif self.context.is_platoon_member():
            self._tick_as_member(timestamp)
    
    def _tick_as_head(self, timestamp: float):
        """
        Tick processing for platoon head.
        
        Responsibilities:
        - Clean up stale members
        - Update energy calculations
        - Compute optimal formation using edge-based Dijkstra
        - Prepare formation data for beacon (sent by Layer C)
        """
        # Clean up stale member entries
        self._clean_stale_members(timestamp)
        
        # Update platoon energy calculations
        self._update_platoon_energy()
        
        # Compute optimal formation for energy transfer
        self._compute_and_update_formation(timestamp)
    
    def _tick_as_member(self, timestamp: float):
        """
        Tick processing for platoon members.
        """
        # Check for beacon timeout
        if self.current_head_id is not None:
            if timestamp - self.last_beacon_time > self.BEACON_TIMEOUT:
                my_name = get_node_name(self.context.node_id)
                logger.warning(f"[{my_name}] Beacon timeout, head may be lost")
                self._handle_beacon_timeout()
                return
        
        # Send periodic status to head
        if timestamp - self.last_status_time >= self.STATUS_INTERVAL:
            self._send_status()
            self.last_status_time = timestamp
    
    def handle_beacon(self, message: PlatoonBeaconMessage):
        """
        Handle incoming PLATOON_BEACON message.
        
        For members: Extract formation positions and update target.
        
        Args:
            message: The PLATOON_BEACON message
        """
        # Extract beacon info
        head_id = message.get_tlv_value(TLVType.HEAD_ID)
        if head_id is None:
            head_id = message.header.sender_id
        
        platoon_id = message.get_tlv_value(TLVType.PLATOON_ID)
        
        # If we're a member, update our tracking
        if self.context.is_platoon_member():
            # Verify this is our platoon
            if self.context.current_platoon_id != platoon_id:
                return  # Different platoon
            
            self.current_head_id = head_id
            self.last_beacon_time = self.context.current_time
            
            # Extract head position for formation
            pos_bytes = message.get_tlv_value(TLVType.HEAD_POSITION)
            if pos_bytes:
                try:
                    head_pos = struct.unpack("!ff", pos_bytes)
                    # Update local knowledge of head position
                except struct.error:
                    pass
            
            # Extract velocity for speed matching
            vel_bytes = message.get_tlv_value(TLVType.VELOCITY)
            if vel_bytes:
                try:
                    head_velocity = struct.unpack("!f", vel_bytes)[0]
                except struct.error:
                    pass
            
            # Extract formation positions (edge-based optimization)
            formation_bytes = message.get_tlv_value(TLVType.FORMATION_POSITIONS)
            if formation_bytes:
                self._process_formation_positions(formation_bytes)
        
        # If we're the head, this shouldn't happen (own beacon reflected)
        # but log it for debugging
        elif self.context.is_platoon_head():
            if head_id == self._get_node_id_bytes():
                return  # Our own beacon
            my_name = get_node_name(self.context.node_id)
            other_name = get_node_name(head_id)
            logger.warning(f"[{my_name}] Received beacon from another head: {other_name}")
    
    def handle_status(self, message: PlatoonStatusMessage):
        """
        Handle incoming PLATOON_STATUS message (as head).
        
        Args:
            message: The PLATOON_STATUS message
        """
        if not self.context.is_platoon_head():
            return  # Only heads process status
        
        # Verify platoon ID
        platoon_id = message.get_tlv_value(TLVType.PLATOON_ID)
        if platoon_id != self.context.current_platoon_id:
            return  # Different platoon
        
        # Extract member info
        vehicle_id = message.get_tlv_value(TLVType.NODE_ID)
        if vehicle_id is None:
            vehicle_id = message.header.sender_id
        
        # Get or create member status
        if vehicle_id not in self.platoon_members:
            self.platoon_members[vehicle_id] = MemberStatus(vehicle_id)
        
        status = self.platoon_members[vehicle_id]
        status.last_update = self.context.current_time
        
        # Extract battery level
        battery_bytes = message.get_tlv_value(TLVType.BATTERY_LEVEL)
        if battery_bytes:
            try:
                status.battery_level = struct.unpack("!f", battery_bytes)[0]
            except struct.error as e:
                logger.warning(f"Failed to unpack battery level: {e}")
        
        # Extract relative index
        index_bytes = message.get_tlv_value(TLVType.RELATIVE_INDEX)
        if index_bytes:
            try:
                status.relative_index = struct.unpack("!B", index_bytes)[0]
            except struct.error:
                pass
        
        # Extract receive rate
        rate_bytes = message.get_tlv_value(TLVType.RECEIVE_RATE)
        if rate_bytes:
            try:
                status.receive_rate = struct.unpack("!f", rate_bytes)[0]
            except struct.error:
                pass
        
        # Forward to Layer C handler if available
        from src.protocol.layer_c.platoon_head_handler import PlatoonHeadHandler
        # (Layer C handler would be instantiated elsewhere and could be accessed via context)
    
    def _send_status(self):
        """
        Send PLATOON_STATUS to the platoon head.
        """
        if self.current_head_id is None:
            return
        
        node = self.context.node
        
        # Platoon ID
        platoon_id = self.context.current_platoon_id or b""
        
        # Vehicle ID
        vehicle_id = self._get_node_id_bytes()
        
        # Battery level (as percentage)
        battery_pct = (node.battery_energy_kwh / node.battery_capacity_kwh) * 100.0
        battery_bytes = struct.pack("!f", battery_pct)
        
        # Relative index
        platoon = self.context.current_platoon
        if platoon and node.node_id in platoon.member_positions:
            index = platoon.member_positions[node.node_id]
        else:
            index = 0
        index_bytes = struct.pack("!B", index)
        
        # Receive rate (placeholder - would come from link layer)
        receive_rate = 1.0  # 100% for now
        rate_bytes = struct.pack("!f", receive_rate)
        
        msg = PlatoonStatusMessage(
            ttl=1,  # Single hop to head
            seq_num=int(self.context.current_time * 1000),
            sender_id=vehicle_id,
            platoon_id=platoon_id,
            vehicle_id=vehicle_id,
            battery=battery_bytes,
            relative_index=index_bytes,
            receive_rate=rate_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
    
    def _clean_stale_members(self, timestamp: float):
        """
        Remove members that haven't sent status in a while.
        """
        stale_timeout = 10.0  # seconds
        stale = [
            vid for vid, status in self.platoon_members.items()
            if timestamp - status.last_update > stale_timeout
        ]
        
        for vid in stale:
            my_name = get_node_name(self.context.node_id)
            member_name = get_node_name(vid)
            logger.warning(f"[{my_name}] Removing stale member: {member_name}")
            del self.platoon_members[vid]
            
            # Also remove from platoon if we have reference
            platoon = self.context.current_platoon
            if platoon:
                for node in list(platoon.nodes):
                    if hasattr(node, 'node_id') and node.node_id == vid:
                        platoon.remove_node(node)
                        break
    
    def _update_platoon_energy(self):
        """
        Update platoon energy calculations based on member status.
        """
        platoon = self.context.current_platoon
        if platoon is None:
            return
        
        platoon.update_total_energy_demand()
        platoon.update_available_charger_power()
    
    def _handle_beacon_timeout(self):
        """
        Handle loss of beacon from platoon head.
        """
        my_name = get_node_name(self.context.node_id)
        logger.warning(f"[{my_name}] Lost contact with head, leaving platoon")
        
        # Leave platoon
        platoon = self.context.current_platoon
        if platoon:
            platoon.remove_node(self.context.node)
        
        self.context.current_platoon = None
        self.context.current_platoon_id = None
        self.current_head_id = None
        
        # Transition back to consumer role
        self.context.set_role(NodeRole.CONSUMER)
    
    def _get_node_id_bytes(self) -> bytes:
        """Get node ID as 6 bytes."""
        node_id = self.context.node_id
        if isinstance(node_id, bytes):
            return node_id[:6].ljust(6, b'\x00')
        elif isinstance(node_id, int):
            return node_id.to_bytes(6, 'big')
        else:
            return str(node_id).encode()[:6].ljust(6, b'\x00')
    
    def get_member_count(self) -> int:
        """Get number of tracked members."""
        return len(self.platoon_members)
    
    def get_member_batteries(self) -> Dict[bytes, float]:
        """Get battery levels of all tracked members."""
        return {vid: status.battery_level for vid, status in self.platoon_members.items()}
    
    def is_member_active(self, member_id: bytes) -> bool:
        """Check if a member is actively reporting."""
        if member_id not in self.platoon_members:
            return False
        status = self.platoon_members[member_id]
        return (self.context.current_time - status.last_update) < 5.0
    
    # ==========================================================================
    # Formation Optimization Methods (Edge-Based)
    # ==========================================================================
    
    def _compute_and_update_formation(self, timestamp: float):
        """
        Compute optimal formation for the platoon using edge-based Dijkstra.
        
        Called by head on each tick. Updates platoon's target formation
        which will be included in the next PLATOON_BEACON.
        """
        platoon = self.context.current_platoon
        if platoon is None:
            return
        
        if len(platoon.nodes) < 2:
            return  # No formation needed for single vehicle
        
        # Ensure platoon has edge graph initialized
        if not platoon.edge_graph:
            platoon.initialize_2d_positions('convoy')
        
        # Compute optimal formation
        new_formation = platoon.compute_optimal_formation(timestamp)
        
        if new_formation:
            self.last_formation = new_formation
            my_name = get_node_name(self.context.node_id)
            logger.debug(f"[{my_name}] Computed formation for {len(new_formation)} members")
    
    def _process_formation_positions(self, formation_bytes: bytes):
        """
        Process formation positions received in PLATOON_BEACON.
        
        Extracts this node's target position and stores it for mobility adjustment.
        
        Args:
            formation_bytes: Serialized formation data from beacon
        """
        # Parse the formation data
        formation = Platoon.parse_formation_message_data(formation_bytes)
        
        # Find our position in the formation
        my_id = self._get_node_id_bytes()
        
        if my_id in formation:
            self.target_formation_position = formation[my_id]
            my_name = get_node_name(self.context.node_id)
            logger.debug(f"[{my_name}] Target position: {self.target_formation_position}")
            
            # Update the platoon's target if we have reference
            platoon = self.context.current_platoon
            if platoon:
                platoon.target_formation[my_id] = self.target_formation_position
    
    def get_formation_for_beacon(self) -> bytes:
        """
        Get serialized formation data to include in PLATOON_BEACON.
        
        Called by Layer C PlatoonHeadHandler when constructing beacons.
        
        Returns:
            Serialized formation positions, or empty bytes if no formation
        """
        platoon = self.context.current_platoon
        if platoon is None or not platoon.target_formation:
            return b""
        
        return platoon.get_formation_message_data()
    
    def get_target_position(self) -> Optional[Tuple[float, float]]:
        """
        Get this node's target formation position (for members).
        
        Can be used by SUMO integration to adjust vehicle position.
        
        Returns:
            Target (x, y) position in meters relative to platoon, or None
        """
        return self.target_formation_position
    
    def get_energy_distribution_plan(self) -> Dict:
        """
        Get the current energy distribution plan (for heads).
        
        Returns Dijkstra-computed optimal paths for energy transfer.
        
        Returns:
            Dict with distribution plan, or empty dict if not head
        """
        if not self.context.is_platoon_head():
            return {}
        
        platoon = self.context.current_platoon
        if platoon is None:
            return {}
        
        return platoon.calculate_energy_distribution_plan()
    
    def get_formation_efficiency(self) -> float:
        """
        Calculate the overall efficiency of the current formation.
        
        Returns average edge efficiency across all usable edges.
        
        Returns:
            Average efficiency (0.0 - 1.0)
        """
        platoon = self.context.current_platoon
        if platoon is None or not platoon.edge_graph:
            return 0.0
        
        usable_edges = platoon.get_usable_edges()
        if not usable_edges:
            return 0.0
        
        total_efficiency = sum(e.transfer_efficiency for e in usable_edges)
        return total_efficiency / len(usable_edges)