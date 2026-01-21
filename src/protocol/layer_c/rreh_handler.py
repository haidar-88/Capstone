"""
RREH Handler for Layer C Charging Coordination.

Implements the Roadside Renewable Energy Hub state machine for
stationary charging stations.
"""

import struct
from typing import Optional, List, Dict, TYPE_CHECKING
from dataclasses import dataclass

from src.protocol.layer_c.states import RREHState, NodeRole
from src.protocol.config import ProtocolConfig
from src.messages.messages import (
    MessageType, JoinOfferMessage, JoinAcceptMessage,
    AckMessage, AckAckMessage, GridStatusMessage, TLVType
)

if TYPE_CHECKING:
    from src.protocol.context import MVCCPContext


@dataclass
class QueuedConsumer:
    """A consumer waiting in the RREH queue."""
    consumer_id: bytes
    energy_required: float
    position: tuple
    timestamp: float
    state: str = 'waiting'  # waiting, accepted, charging, done


class RREHHandler:
    """
    Handles the RREH (Roadside Renewable Energy Hub) state machine.
    
    RREHs are stationary and predetermined - they don't switch roles dynamically.
    
    State Machine Flow:
    GRID_ANNOUNCE -> WAIT_OFFERS -> EVALUATE_QUEUE -> SEND_ACCEPT ->
    WAIT_ACK -> SEND_ACKACK -> CHARGE_SESSION -> IDLE
    """
    
    # Timing constants
    GRID_STATUS_INTERVAL = 10.0  # seconds between GRID_STATUS broadcasts
    OFFER_WINDOW = 5.0           # seconds to collect offers
    ACK_TIMEOUT = 5.0            # seconds to wait for ACK
    
    def __init__(self, context: 'MVCCPContext'):
        """
        Initialize the RREH handler.
        
        Args:
            context: MVCCP protocol context (should have is_rreh=True)
        """
        self.context = context
        
        # Queue management
        self.consumer_queue: List[QueuedConsumer] = []
        self.active_sessions: Dict[bytes, QueuedConsumer] = {}
        
        # Timing
        self.last_grid_status_time = 0.0
        self.offer_window_start = 0.0
        
        # Current negotiation
        self.current_target: Optional[bytes] = None
        self.current_target_timeout = 0.0
        
        # Initialize state
        if context.rreh_state is None:
            context.rreh_state = RREHState.GRID_ANNOUNCE
    
    def tick(self, timestamp: float):
        """
        Process a protocol tick.
        
        Args:
            timestamp: Current simulation time
        """
        if not self.context.is_rreh():
            return
        
        state = self.context.rreh_state
        
        if state == RREHState.GRID_ANNOUNCE:
            self._process_grid_announce(timestamp)
        elif state == RREHState.WAIT_OFFERS:
            self._process_wait_offers(timestamp)
        elif state == RREHState.EVALUATE_QUEUE:
            self._process_evaluate_queue()
        elif state == RREHState.WAIT_ACK:
            self._check_ack_timeout(timestamp)
        elif state == RREHState.CHARGE_SESSION:
            self._process_charge_session(timestamp)
        elif state == RREHState.IDLE:
            self._process_idle(timestamp)
    
    def _process_grid_announce(self, timestamp: float):
        """
        GRID_ANNOUNCE state: Broadcast GRID_STATUS periodically.
        """
        if timestamp - self.last_grid_status_time >= self.GRID_STATUS_INTERVAL:
            self._send_grid_status()
            self.last_grid_status_time = timestamp
        
        # Transition to WAIT_OFFERS if we have capacity
        if self._has_capacity():
            self.context.rreh_state = RREHState.WAIT_OFFERS
            self.offer_window_start = timestamp
    
    def _send_grid_status(self):
        """Send GRID_STATUS message."""
        # Hub ID
        hub_id = self._get_node_id_bytes()
        
        # Renewable fraction (0.0 to 1.0)
        renewable = getattr(self.context, 'rreh_renewable_fraction', 1.0)
        renewable_bytes = struct.pack("!f", renewable)
        
        # Available power (kW)
        available_power = getattr(self.context, 'rreh_available_power', 150.0)
        power_bytes = struct.pack("!f", available_power)
        
        # Max sessions
        max_sessions = getattr(self.context, 'rreh_max_sessions', 4)
        max_sessions_bytes = struct.pack("!B", max_sessions)
        
        # Queue time estimate
        queue_time = self._estimate_queue_time()
        queue_time_bytes = struct.pack("!f", queue_time)
        
        # Operational state
        op_state = getattr(self.context, 'rreh_operational_state', 'normal')
        op_state_bytes = self._encode_op_state(op_state)
        
        msg = GridStatusMessage(
            ttl=self.context.get_effective_ttl(),
            seq_num=int(self.context.current_time * 1000),
            sender_id=hub_id,
            hub_id=hub_id,
            renewable_fraction=renewable_bytes,
            available_power=power_bytes,
            max_sessions=max_sessions_bytes,
            queue_time=queue_time_bytes,
            operational_state=op_state_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
    
    def _encode_op_state(self, state: str) -> bytes:
        """Encode operational state as byte."""
        states = {'normal': 0, 'congested': 1, 'limited': 2, 'offline': 3}
        return struct.pack("!B", states.get(state, 0))
    
    def calculate_queue_time(self) -> float:
        """
        Calculate estimated wait time for new consumer (P7).
        
        Formula: active_sessions * avg_session_duration
        - Wait time only (excludes charging duration for new consumer)
        - If capacity available, returns 0
        
        Returns:
            Estimated wait time in seconds
        """
        active_count = len(self.active_sessions)
        max_sessions = getattr(self.context, 'rreh_max_sessions', 4)
        
        if active_count < max_sessions:
            # Capacity available - can serve immediately
            return 0.0
        
        # P7: Simple model - active sessions * average session duration
        avg_session_duration = ProtocolConfig.RREH_AVG_SESSION_DURATION
        queue_time = active_count * avg_session_duration
        
        return min(queue_time, ProtocolConfig.MAX_ACCEPTABLE_QUEUE_TIME)
    
    def _estimate_queue_time(self) -> float:
        """
        Estimate wait time for new consumer in queue (legacy wrapper).
        
        Returns:
            Estimated wait time in seconds
        """
        return self.calculate_queue_time()
    
    def _has_capacity(self) -> bool:
        """Check if RREH has capacity for new sessions."""
        max_sessions = getattr(self.context, 'rreh_max_sessions', 4)
        active_count = len(self.active_sessions)
        op_state = getattr(self.context, 'rreh_operational_state', 'normal')
        
        return active_count < max_sessions and op_state in ('normal', 'congested')
    
    def _process_wait_offers(self, timestamp: float):
        """
        WAIT_OFFERS state: Collect JOIN_OFFER messages.
        """
        if timestamp - self.offer_window_start >= self.OFFER_WINDOW:
            if self.consumer_queue:
                self.context.rreh_state = RREHState.EVALUATE_QUEUE
            else:
                self.context.rreh_state = RREHState.IDLE
    
    def handle_join_offer(self, message: JoinOfferMessage):
        """
        Handle incoming JOIN_OFFER from a consumer.
        
        Args:
            message: The JOIN_OFFER message
        """
        # Accept offers in most states
        if self.context.rreh_state == RREHState.CHARGE_SESSION:
            if not self._has_capacity():
                return  # Full, queue for later
        
        # Extract consumer info
        consumer_id = message.get_tlv_value(TLVType.CONSUMER_ID)
        if consumer_id is None:
            consumer_id = message.header.sender_id
        
        # Check for duplicates
        if any(c.consumer_id == consumer_id for c in self.consumer_queue):
            return
        if consumer_id in self.active_sessions:
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
        
        # Add to queue
        queued = QueuedConsumer(
            consumer_id=consumer_id,
            energy_required=energy_req,
            position=position,
            timestamp=self.context.current_time
        )
        self.consumer_queue.append(queued)
        
        print(f"[RREH {self.context.node_id}] Received JOIN_OFFER from {consumer_id}, "
              f"queue position: {len(self.consumer_queue)}")
        
        # If idle, start processing
        if self.context.rreh_state == RREHState.IDLE:
            self.context.rreh_state = RREHState.EVALUATE_QUEUE
    
    def _process_evaluate_queue(self):
        """
        EVALUATE_QUEUE state: Select next consumer from queue.
        """
        if not self.consumer_queue or not self._has_capacity():
            self.context.rreh_state = RREHState.IDLE
            return
        
        # FIFO queue - take first
        consumer = self.consumer_queue[0]
        self.current_target = consumer.consumer_id
        consumer.state = 'accepted'
        
        self.context.rreh_state = RREHState.SEND_ACCEPT
        self._send_accept(consumer)
    
    def _send_accept(self, consumer: QueuedConsumer):
        """
        Send JOIN_ACCEPT to a consumer.
        """
        # Meeting point is RREH location
        lat, lon = self.context.node.position()
        mp_bytes = struct.pack("!ff", lat, lon)
        
        # Bandwidth (charging rate)
        available_power = getattr(self.context, 'rreh_available_power', 150.0)
        bandwidth_bytes = struct.pack("!f", available_power)
        
        # Duration estimate
        if available_power > 0:
            duration = (consumer.energy_required / available_power) * 3600
        else:
            duration = 0.0
        duration_bytes = struct.pack("!f", duration)
        
        msg = JoinAcceptMessage(
            ttl=self.context.get_effective_ttl(),
            seq_num=int(self.context.current_time * 1000),
            sender_id=self._get_node_id_bytes(),
            provider_id=self._get_node_id_bytes(),
            meeting_point=mp_bytes,
            bandwidth=bandwidth_bytes,
            duration=duration_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
        
        self.context.rreh_state = RREHState.WAIT_ACK
        self.current_target_timeout = self.context.current_time + self.ACK_TIMEOUT
        
        print(f"[RREH {self.context.node_id}] Sent JOIN_ACCEPT to {consumer.consumer_id}")
    
    def handle_ack(self, message: AckMessage):
        """
        Handle ACK from consumer.
        """
        if self.context.rreh_state != RREHState.WAIT_ACK:
            return
        
        consumer_id = message.get_tlv_value(TLVType.CONSUMER_ID)
        if consumer_id is None:
            consumer_id = message.header.sender_id
        
        if consumer_id != self.current_target:
            return
        
        print(f"[RREH {self.context.node_id}] Received ACK from {consumer_id}, sending ACKACK")
        
        self.context.rreh_state = RREHState.SEND_ACKACK
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
        
        # Move from queue to active sessions
        consumer = None
        for i, c in enumerate(self.consumer_queue):
            if c.consumer_id == consumer_id:
                consumer = self.consumer_queue.pop(i)
                break
        
        if consumer:
            consumer.state = 'charging'
            self.active_sessions[consumer_id] = consumer
            
            # Update RREH state
            active_count = len(self.active_sessions)
            setattr(self.context, 'rreh_active_sessions', active_count)
        
        self.current_target = None
        
        # Transition to CHARGE_SESSION or process more queue
        if self.active_sessions:
            self.context.rreh_state = RREHState.CHARGE_SESSION
        elif self.consumer_queue:
            self.context.rreh_state = RREHState.EVALUATE_QUEUE
        else:
            self.context.rreh_state = RREHState.IDLE
        
        print(f"[RREH {self.context.node_id}] Sent ACKACK, session started")
    
    def _check_ack_timeout(self, timestamp: float):
        """Check for ACK timeout."""
        if timestamp > self.current_target_timeout:
            print(f"[RREH {self.context.node_id}] ACK timeout for {self.current_target}")
            
            # Remove from queue
            for i, c in enumerate(self.consumer_queue):
                if c.consumer_id == self.current_target:
                    self.consumer_queue.pop(i)
                    break
            
            self.current_target = None
            
            # Process next in queue
            if self.consumer_queue:
                self.context.rreh_state = RREHState.EVALUATE_QUEUE
            else:
                self.context.rreh_state = RREHState.IDLE
    
    def _process_charge_session(self, timestamp: float):
        """
        CHARGE_SESSION state: Manage active charging sessions.
        """
        # Send periodic GRID_STATUS
        if timestamp - self.last_grid_status_time >= self.GRID_STATUS_INTERVAL:
            self._send_grid_status()
            self.last_grid_status_time = timestamp
        
        # Check if we can accept more while charging
        if self._has_capacity() and self.consumer_queue:
            self.context.rreh_state = RREHState.EVALUATE_QUEUE
    
    def _process_idle(self, timestamp: float):
        """
        IDLE state: No active sessions, waiting for offers.
        """
        # Send periodic GRID_STATUS
        if timestamp - self.last_grid_status_time >= self.GRID_STATUS_INTERVAL:
            self._send_grid_status()
            self.last_grid_status_time = timestamp
        
        # Check queue
        if self.consumer_queue and self._has_capacity():
            self.context.rreh_state = RREHState.EVALUATE_QUEUE
    
    def complete_session(self, consumer_id: bytes):
        """
        Mark a charging session as complete.
        Called by simulation when charging is done.
        
        Args:
            consumer_id: ID of the consumer that finished
        """
        if consumer_id in self.active_sessions:
            consumer = self.active_sessions.pop(consumer_id)
            consumer.state = 'done'
            
            active_count = len(self.active_sessions)
            setattr(self.context, 'rreh_active_sessions', active_count)
            
            print(f"[RREH {self.context.node_id}] Session complete for {consumer_id}")
            
            # Check for queued consumers
            if self.consumer_queue and self._has_capacity():
                self.context.rreh_state = RREHState.EVALUATE_QUEUE
    
    def set_operational_state(self, state: str):
        """
        Set the RREH operational state.
        
        Args:
            state: One of 'normal', 'congested', 'limited', 'offline'
        """
        valid_states = ('normal', 'congested', 'limited', 'offline')
        if state in valid_states:
            self.context.rreh_operational_state = state
    
    def _get_node_id_bytes(self) -> bytes:
        """Get node ID as 6 bytes."""
        node_id = self.context.node_id
        if isinstance(node_id, bytes):
            return node_id[:6].ljust(6, b'\x00')
        elif isinstance(node_id, int):
            return node_id.to_bytes(6, 'big')
        else:
            return str(node_id).encode()[:6].ljust(6, b'\x00')
    
    def get_state(self) -> RREHState:
        """Get current RREH state."""
        return self.context.rreh_state
    
    def get_status(self) -> dict:
        """Get current RREH status."""
        return {
            'state': self.context.rreh_state.name if self.context.rreh_state else 'UNKNOWN',
            'queue_length': len(self.consumer_queue),
            'active_sessions': len(self.active_sessions),
            'max_sessions': getattr(self.context, 'rreh_max_sessions', 4),
            'available_power': getattr(self.context, 'rreh_available_power', 150.0),
            'renewable_fraction': getattr(self.context, 'rreh_renewable_fraction', 1.0),
            'operational_state': getattr(self.context, 'rreh_operational_state', 'normal'),
            'estimated_queue_time': self._estimate_queue_time(),
        }



