"""
Platoon Head Handler for Layer C Charging Coordination.

Implements the Platoon Head state machine for managing platoons,
accepting members, and coordinating charging.

Extended with inter-platoon discovery via PLATOON_ANNOUNCE messages
that broadcast platoon capabilities to enable consumer routing.
"""

import struct
import logging
from typing import Optional, List, Dict, TYPE_CHECKING

from src.protocol.layer_c.states import PlatoonHeadState, NodeRole
from src.protocol.node_registry import get_node_name
from src.core.platoon import Platoon
from src.messages.messages import (
    MessageType, JoinOfferMessage, JoinAcceptMessage,
    AckMessage, AckAckMessage, PlatoonBeaconMessage, 
    PlatoonStatusMessage, PlatoonAnnounceMessage, TLVType, TLV
)
from src.protocol.config import ProtocolConfig

if TYPE_CHECKING:
    from src.protocol.context import MVCCPContext

logger = logging.getLogger('mvccp.platoon_head')


class PendingMember:
    """Tracks a pending member join request."""
    def __init__(self, consumer_id: bytes, energy_required: float, 
                 position: tuple, trajectory: tuple, timestamp: float):
        self.consumer_id = consumer_id
        self.energy_required = energy_required
        self.position = position
        self.trajectory = trajectory  # Destination
        self.timestamp = timestamp
        self.accepted = False
        self.ack_received = False


class PlatoonHeadHandler:
    """
    Handles the Platoon Head state machine.
    
    State Machine Flow:
    BEACON -> WAIT_OFFERS -> EVALUATE_OFFERS -> SEND_ACCEPT -> 
    WAIT_ACK -> SEND_ACKACK -> COORDINATE -> (HANDOFF)
    """
    
    # Timing constants
    BEACON_INTERVAL = 2.0  # seconds between beacons
    OFFER_WINDOW = 3.0     # seconds to collect offers
    ACK_TIMEOUT = 3.0      # seconds to wait for ACK
    MAX_PENDING = 5        # Max pending offers to track
    
    def __init__(self, context: 'MVCCPContext'):
        """
        Initialize the platoon head handler.
        
        Args:
            context: MVCCP protocol context
        """
        self.context = context
        
        # Pending member tracking
        self.pending_members: Dict[bytes, PendingMember] = {}
        
        # State timing
        self.last_beacon_time = 0.0
        self.offer_window_start = 0.0
        self.last_state_change = 0.0
        
        # Inter-platoon discovery timing (PLATOON_ANNOUNCE)
        self.last_announce_time = 0.0
        
        # Current negotiation target
        self.current_target: Optional[bytes] = None
        self.current_target_timeout = 0.0
        
        # Initialize state if needed
        if context.platoon_head_state is None:
            context.platoon_head_state = PlatoonHeadState.BEACON
    
    def tick(self, timestamp: float):
        """
        Process a protocol tick.
        
        Args:
            timestamp: Current simulation time
        """
        if not self.context.is_platoon_head():
            return
        
        state = self.context.platoon_head_state
        
        if state == PlatoonHeadState.BEACON:
            self._process_beacon(timestamp)
        elif state == PlatoonHeadState.WAIT_OFFERS:
            self._process_wait_offers(timestamp)
        elif state == PlatoonHeadState.EVALUATE_OFFERS:
            self._process_evaluate_offers()
        elif state == PlatoonHeadState.WAIT_ACK:
            self._check_ack_timeout(timestamp)
        elif state == PlatoonHeadState.COORDINATE:
            self._process_coordinate(timestamp)
        elif state == PlatoonHeadState.HANDOFF:
            self._process_handoff()
    
    def _process_beacon(self, timestamp: float):
        """
        BEACON state: Send periodic PLATOON_BEACON messages.
        Also sends PLATOON_ANNOUNCE for inter-platoon discovery.
        """
        if timestamp - self.last_beacon_time >= self.BEACON_INTERVAL:
            self._send_beacon()
            self.last_beacon_time = timestamp
        
        # Send PLATOON_ANNOUNCE for inter-platoon discovery (slower interval)
        if timestamp - self.last_announce_time >= ProtocolConfig.PLATOON_ANNOUNCE_INTERVAL:
            self._send_platoon_announce()
            self.last_announce_time = timestamp
        
        # Check if we have capacity and should accept offers
        platoon = self.context.current_platoon
        if platoon and platoon.available_slots() > 0:
            self.context.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
            self.offer_window_start = timestamp
    
    def _send_beacon(self):
        """Send a PLATOON_BEACON message."""
        platoon = self.context.current_platoon
        if platoon is None:
            return
        
        # Prepare beacon fields
        platoon_id = platoon.platoon_id
        head_id = self._get_node_id_bytes()
        
        # Timestamp
        timestamp_bytes = struct.pack("!d", self.context.current_time)
        
        # Head position
        lat, lon = platoon.head_position()
        position_bytes = struct.pack("!ff", lat, lon)
        
        # Velocity
        velocity_bytes = struct.pack("!f", platoon.head_velocity())
        
        # Available slots
        slots_bytes = struct.pack("!B", platoon.available_slots())
        
        # Topology (list of member IDs with positions)
        topology = platoon.get_topology_vector()
        topology_bytes = self._encode_topology(topology)
        
        # Route (common destination)
        route_bytes = b""
        if platoon.common_destination:
            route_bytes = struct.pack("!ff", 
                platoon.common_destination[0], 
                platoon.common_destination[1])
        
        msg = PlatoonBeaconMessage(
            ttl=self.context.get_effective_ttl(),
            seq_num=int(self.context.current_time * 1000),
            sender_id=head_id,
            platoon_id=platoon_id,
            head_id=head_id,
            timestamp=timestamp_bytes,
            head_position=position_bytes,
            velocity=velocity_bytes,
            available_slots=slots_bytes,
            topology=topology_bytes,
            route=route_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
    
    def _send_platoon_announce(self):
        """
        Send PLATOON_ANNOUNCE message for inter-platoon discovery.
        
        Broadcasts platoon capabilities so consumers can find and compare
        platoons based on direction, energy, and available slots.
        """
        platoon = self.context.current_platoon
        if platoon is None:
            return
        
        # Basic identification
        platoon_id = platoon.platoon_id
        head_id = self._get_node_id_bytes()
        
        # Position
        lat, lon = platoon.head_position()
        position_bytes = struct.pack("!ff", lat, lon)
        
        # Destination
        dest_bytes = b""
        if platoon.common_destination:
            dest_bytes = struct.pack("!ff", 
                platoon.common_destination[0],
                platoon.common_destination[1])
        
        # Available slots
        slots_bytes = struct.pack("!B", platoon.available_slots())
        
        # Surplus energy (total shareable from all members)
        surplus = platoon.total_shareable_energy()
        surplus_bytes = struct.pack("!f", surplus)
        
        # Direction vector (normalized)
        direction = platoon.direction_vector()
        direction_bytes = struct.pack("!ff", direction[0], direction[1])
        
        # Formation efficiency (from edge-based optimization)
        efficiency = 0.0
        if hasattr(platoon, 'edge_graph') and platoon.edge_graph:
            usable_edges = platoon.get_usable_edges()
            if usable_edges:
                efficiency = sum(e.transfer_efficiency for e in usable_edges) / len(usable_edges)
        efficiency_bytes = struct.pack("!f", efficiency)
        
        msg = PlatoonAnnounceMessage(
            ttl=ProtocolConfig.PLATOON_ANNOUNCE_TTL,
            seq_num=int(self.context.current_time * 1000),
            sender_id=head_id,
            platoon_id=platoon_id,
            head_id=head_id,
            position=position_bytes,
            destination=dest_bytes,
            available_slots=slots_bytes,
            surplus_energy=surplus_bytes,
            direction_vector=direction_bytes,
            formation_efficiency=efficiency_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
        
        my_name = get_node_name(self.context.node_id)
        logger.debug(f"[{my_name}] TX PLATOON_ANNOUNCE: "
                    f"energy={surplus:.1f}kWh, slots={platoon.available_slots()}")
    
    def _encode_topology(self, topology: list) -> bytes:
        """
        Encode platoon topology as bytes.
        Format: count (1 byte) + [node_id (6 bytes) + index (1 byte)] * count
        """
        result = struct.pack("!B", len(topology))
        for node_id, idx in topology:
            if isinstance(node_id, int):
                node_bytes = node_id.to_bytes(6, 'big')
            elif isinstance(node_id, bytes):
                node_bytes = node_id[:6].ljust(6, b'\x00')
            else:
                node_bytes = str(node_id).encode()[:6].ljust(6, b'\x00')
            result += node_bytes + struct.pack("!B", idx)
        return result
    
    def _process_wait_offers(self, timestamp: float):
        """
        WAIT_OFFERS state: Collect JOIN_OFFER messages for a window period.
        """
        if timestamp - self.offer_window_start >= self.OFFER_WINDOW:
            # Window closed, evaluate offers
            if self.pending_members:
                self.context.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
            else:
                # No offers, go back to BEACON
                self.context.platoon_head_state = PlatoonHeadState.BEACON
    
    def handle_join_offer(self, message: JoinOfferMessage):
        """
        Handle incoming JOIN_OFFER from a consumer.
        
        Args:
            message: The JOIN_OFFER message
        """
        # Accept offers in WAIT_OFFERS or BEACON state
        if self.context.platoon_head_state not in (
            PlatoonHeadState.WAIT_OFFERS, 
            PlatoonHeadState.BEACON,
            PlatoonHeadState.COORDINATE
        ):
            return
        
        # Check capacity
        platoon = self.context.current_platoon
        if platoon is None or platoon.available_slots() == 0:
            return
        
        # Extract offer details
        consumer_id = message.get_tlv_value(TLVType.CONSUMER_ID)
        if consumer_id is None:
            consumer_id = message.header.sender_id
        
        # Don't accept duplicate offers
        if consumer_id in self.pending_members:
            return
        
        # Check pending limit
        if len(self.pending_members) >= self.MAX_PENDING:
            return
        
        # Extract energy required
        energy_req = 0.0
        req_bytes = message.get_tlv_value(TLVType.ENERGY_REQUIRED)
        if req_bytes:
            try:
                energy_req = struct.unpack("!f", req_bytes)[0]
            except struct.error:
                pass
        
        # Extract position
        position = (0.0, 0.0)
        pos_bytes = message.get_tlv_value(TLVType.POSITION)
        if pos_bytes:
            try:
                position = struct.unpack("!ff", pos_bytes)
            except struct.error:
                pass
        
        # Extract trajectory/destination
        trajectory = (0.0, 0.0)
        traj_bytes = message.get_tlv_value(TLVType.TRAJECTORY)
        if traj_bytes:
            try:
                trajectory = struct.unpack("!ff", traj_bytes)
            except struct.error:
                pass
        
        # Create pending member
        pending = PendingMember(
            consumer_id=consumer_id,
            energy_required=energy_req,
            position=position,
            trajectory=trajectory,
            timestamp=self.context.current_time
        )
        
        self.pending_members[consumer_id] = pending
        
        my_name = get_node_name(self.context.node_id)
        consumer_name = get_node_name(consumer_id)
        logger.info(f"[{my_name}] RX JOIN_OFFER from {consumer_name}")
        
        # If in COORDINATE state, evaluate immediately
        if self.context.platoon_head_state == PlatoonHeadState.COORDINATE:
            self.context.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
    
    def _process_evaluate_offers(self):
        """
        EVALUATE_OFFERS state: Decide which offers to accept.
        """
        platoon = self.context.current_platoon
        if platoon is None:
            self.pending_members.clear()
            self.context.platoon_head_state = PlatoonHeadState.BEACON
            return
        
        available_slots = platoon.available_slots()
        if available_slots == 0 or not self.pending_members:
            self.pending_members.clear()
            self.context.platoon_head_state = PlatoonHeadState.COORDINATE
            return
        
        # Score and rank pending members
        scored = []
        for consumer_id, pending in self.pending_members.items():
            score = self._score_offer(pending)
            scored.append((score, consumer_id, pending))
        
        # Sort by score (higher is better)
        scored.sort(reverse=True, key=lambda x: x[0])
        
        # Accept top offers up to available slots
        accepted_count = 0
        for score, consumer_id, pending in scored:
            if accepted_count >= available_slots:
                break
            
            if score > 0:  # Only accept positive scores
                pending.accepted = True
                self.current_target = consumer_id
                accepted_count += 1
                break  # Process one at a time
        
        if self.current_target:
            self.context.platoon_head_state = PlatoonHeadState.SEND_ACCEPT
            self._send_accept(self.pending_members[self.current_target])
        else:
            # No acceptable offers
            self.pending_members.clear()
            self.context.platoon_head_state = PlatoonHeadState.COORDINATE
    
    def _score_offer(self, pending: PendingMember) -> float:
        """
        Score a pending join offer.
        Higher score = better match.
        
        Factors:
        - Route alignment with platoon destination
        - Energy availability to serve the request
        """
        platoon = self.context.current_platoon
        if platoon is None:
            return 0.0
        
        score = 100.0  # Base score
        
        # Route alignment bonus
        if platoon.common_destination and pending.trajectory != (0.0, 0.0):
            # Calculate direction similarity
            platoon_dir = platoon.direction_vector()
            
            # Consumer direction from their position to their destination
            dx = pending.trajectory[0] - pending.position[0]
            dy = pending.trajectory[1] - pending.position[1]
            mag = (dx**2 + dy**2) ** 0.5
            if mag > 0:
                consumer_dir = (dx / mag, dy / mag)
                alignment = platoon_dir[0] * consumer_dir[0] + platoon_dir[1] * consumer_dir[1]
                score += alignment * 50  # -50 to +50 based on alignment
        
        # Check if we can provide the energy
        shareable = platoon.head_shareable_energy()
        if pending.energy_required > shareable:
            score -= 50  # Penalty for not having enough energy
        
        return score
    
    def _send_accept(self, pending: PendingMember):
        """
        Send JOIN_ACCEPT to a consumer.
        """
        platoon = self.context.current_platoon
        if platoon is None:
            return
        
        # Meeting point (current head position)
        lat, lon = platoon.head_position()
        mp_bytes = struct.pack("!ff", lat, lon)
        
        # Bandwidth (charging rate)
        bandwidth = self.context.node.max_transfer_rate_out
        bandwidth_bytes = struct.pack("!f", bandwidth)
        
        # Duration estimate
        if bandwidth > 0:
            duration = (pending.energy_required / bandwidth) * 3600  # seconds
        else:
            duration = 0.0
        duration_bytes = struct.pack("!f", duration)
        
        # Platoon members
        members_bytes = self._encode_topology(platoon.get_topology_vector())
        
        msg = JoinAcceptMessage(
            ttl=self.context.get_effective_ttl(),
            seq_num=int(self.context.current_time * 1000),
            sender_id=self._get_node_id_bytes(),
            provider_id=self._get_node_id_bytes(),
            meeting_point=mp_bytes,
            bandwidth=bandwidth_bytes,
            duration=duration_bytes,
            platoon_members=members_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
        
        # Set timeout for ACK
        self.context.platoon_head_state = PlatoonHeadState.WAIT_ACK
        self.current_target_timeout = self.context.current_time + self.ACK_TIMEOUT
        
        my_name = get_node_name(self.context.node_id)
        consumer_name = get_node_name(pending.consumer_id)
        logger.info(f"[{my_name}] TX JOIN_ACCEPT to {consumer_name}")
    
    def handle_ack(self, message: AckMessage):
        """
        Handle ACK from consumer.
        """
        if self.context.platoon_head_state != PlatoonHeadState.WAIT_ACK:
            return
        
        consumer_id = message.get_tlv_value(TLVType.CONSUMER_ID)
        if consumer_id is None:
            consumer_id = message.header.sender_id
        
        if consumer_id != self.current_target:
            return
        
        pending = self.pending_members.get(consumer_id)
        if pending:
            pending.ack_received = True
        
        my_name = get_node_name(self.context.node_id)
        consumer_name = get_node_name(consumer_id)
        logger.info(f"[{my_name}] RX ACK from {consumer_name}")
        
        # Send ACKACK
        self.context.platoon_head_state = PlatoonHeadState.SEND_ACKACK
        self._send_ackack(consumer_id)
    
    def _send_ackack(self, consumer_id: bytes):
        """Send ACKACK to confirm session."""
        msg = AckAckMessage(
            ttl=self.context.get_effective_ttl(),
            seq_num=int(self.context.current_time * 1000),
            sender_id=self._get_node_id_bytes(),
            provider_id=self._get_node_id_bytes()
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
        
        # Add member to platoon
        pending = self.pending_members.get(consumer_id)
        if pending:
            self._add_member_to_platoon(pending)
        
        # Clean up and move to COORDINATE
        if consumer_id in self.pending_members:
            del self.pending_members[consumer_id]
        self.current_target = None
        
        # Check for more pending offers
        if self.pending_members:
            self.context.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        else:
            self.context.platoon_head_state = PlatoonHeadState.COORDINATE
        
        my_name = get_node_name(self.context.node_id)
        logger.info(f"[{my_name}] TX ACKACK, member added to platoon")
    
    def _add_member_to_platoon(self, pending: PendingMember):
        """
        Add a confirmed member to the platoon.
        Note: In a real system, we'd need to get the actual Node object.
        For now, we just update tracking.
        """
        platoon = self.context.current_platoon
        if platoon is None:
            return
        
        # Add to context tracking
        if pending.consumer_id not in self.context.platoon_members:
            self.context.platoon_members.append(pending.consumer_id)
        
        # Note: The actual Node object would be added by the simulation
        # when the consumer's context is updated
    
    def _check_ack_timeout(self, timestamp: float):
        """Check for ACK timeout."""
        if timestamp > self.current_target_timeout:
            my_name = get_node_name(self.context.node_id)
            target_name = get_node_name(self.current_target)
            logger.warning(f"[{my_name}] ACK timeout for {target_name}")
            
            # Remove pending member
            if self.current_target in self.pending_members:
                del self.pending_members[self.current_target]
            self.current_target = None
            
            # Continue with other offers or coordinate
            if self.pending_members:
                self.context.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
            else:
                self.context.platoon_head_state = PlatoonHeadState.COORDINATE
    
    def _process_coordinate(self, timestamp: float):
        """
        COORDINATE state: Maintain platoon and process status updates.
        Also send periodic beacons and PLATOON_ANNOUNCE messages.
        """
        # Send beacon periodically
        if timestamp - self.last_beacon_time >= self.BEACON_INTERVAL:
            self._send_beacon()
            self.last_beacon_time = timestamp
        
        # Send PLATOON_ANNOUNCE for inter-platoon discovery
        if timestamp - self.last_announce_time >= ProtocolConfig.PLATOON_ANNOUNCE_INTERVAL:
            self._send_platoon_announce()
            self.last_announce_time = timestamp
        
        # Check for handoff need
        from src.protocol.layer_c.role_manager import RoleManager
        role_manager = RoleManager(self.context)
        if role_manager.should_handoff():
            self.context.platoon_head_state = PlatoonHeadState.HANDOFF
    
    def handle_platoon_status(self, message: PlatoonStatusMessage):
        """
        Handle PLATOON_STATUS from a member.
        Used to track member state and battery levels.
        """
        platoon = self.context.current_platoon
        if platoon is None:
            return
        
        # Extract member info
        vehicle_id = message.get_tlv_value(TLVType.NODE_ID)
        
        battery_bytes = message.get_tlv_value(TLVType.BATTERY_LEVEL)
        battery_level = 0.0
        if battery_bytes:
            try:
                battery_level = struct.unpack("!f", battery_bytes)[0]
            except struct.error:
                pass
        
        # Update member tracking (in real system, update Node object)
        my_name = get_node_name(self.context.node_id)
        member_name = get_node_name(vehicle_id)
        logger.debug(f"[{my_name}] RX PLATOON_STATUS from {member_name}: battery {battery_level:.1f}%")
    
    def _process_handoff(self):
        """
        HANDOFF state: Transfer PH role to another member.
        """
        from src.protocol.layer_c.role_manager import RoleManager
        role_manager = RoleManager(self.context)
        
        success = role_manager.perform_handoff()
        
        if success:
            my_name = get_node_name(self.context.node_id)
            logger.info(f"[{my_name}] Handoff successful")
            # Role manager handles state transition
        else:
            my_name = get_node_name(self.context.node_id)
            logger.warning(f"[{my_name}] Handoff failed, continuing as PH")
            self.context.platoon_head_state = PlatoonHeadState.COORDINATE
    
    def _get_node_id_bytes(self) -> bytes:
        """Get node ID as 6 bytes."""
        node_id = self.context.node_id
        if isinstance(node_id, bytes):
            return node_id[:6].ljust(6, b'\x00')
        elif isinstance(node_id, int):
            return node_id.to_bytes(6, 'big')
        else:
            return str(node_id).encode()[:6].ljust(6, b'\x00')
    
    def get_state(self) -> PlatoonHeadState:
        """Get current PH state."""
        return self.context.platoon_head_state
    
    def get_platoon_info(self) -> dict:
        """Get current platoon information."""
        platoon = self.context.current_platoon
        if platoon is None:
            return {}
        
        return {
            'platoon_id': platoon.platoon_id,
            'head_id': platoon.head_id,
            'member_count': platoon.node_number,
            'available_slots': platoon.available_slots(),
            'total_shareable_energy': platoon.total_shareable_energy(),
            'common_destination': platoon.common_destination,
        }



