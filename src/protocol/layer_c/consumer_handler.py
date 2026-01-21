"""
Consumer Handler for Layer C Charging Coordination.

Implements the Consumer state machine for discovering providers,
evaluating options, and negotiating charging sessions.

Extended with inter-platoon discovery via PlatoonTable to find
the best platoon based on direction, energy, and available slots.
"""

import struct
import random
import logging
from typing import Optional, Dict, Tuple, TYPE_CHECKING

from src.protocol.layer_c.states import ConsumerState, NodeRole
from src.protocol.layer_c.efficiency_calc import EfficiencyCalculator, ProviderEvaluation
from src.protocol.layer_c.platoon_table import PlatoonTable, PlatoonEntry
from src.protocol.node_registry import get_node_name
from src.messages.messages import (
    MessageType, JoinOfferMessage, JoinAcceptMessage, 
    AckMessage, AckAckMessage, PlatoonAnnounceMessage, TLVType
)
from src.protocol.config import ProtocolConfig

if TYPE_CHECKING:
    from src.protocol.context import MVCCPContext

logger = logging.getLogger('mvccp.consumer')


class ConsumerHandler:
    """
    Handles the Consumer state machine for charging coordination.
    
    State Machine Flow:
    DISCOVER -> EVALUATE -> SEND_OFFER -> WAIT_ACCEPT -> SEND_ACK -> 
    WAIT_ACKACK -> ALLOCATED -> TRAVEL -> CHARGE -> LEAVE
    """
    
    # Timeout values (seconds)
    ACCEPT_TIMEOUT = 5.0
    ACKACK_TIMEOUT = 3.0
    MAX_RETRIES = ProtocolConfig.RETRY_MAX_RETRIES
    
    def __init__(self, context: 'MVCCPContext'):
        """
        Initialize the consumer handler.
        
        Args:
            context: MVCCP protocol context
        """
        self.context = context
        self.efficiency_calc = EfficiencyCalculator(context)
        
        # Inter-platoon discovery table
        self.platoon_table = PlatoonTable()
        
        # Session tracking
        self.current_session = {
            'provider_id': None,
            'provider_type': None,
            'meeting_point': None,
            'start_time': 0.0,
            'timeout_time': 0.0,
            'retries': 0,
            'evaluation': None,
            'next_retry_time': None,  # For exponential backoff
            'backoff_delay': 0.0,     # Current backoff delay
        }
        
        # Provider blacklist: {provider_id: blacklist_until_time}
        self.blacklisted_providers: Dict[bytes, float] = {}
        
        # Selected platoon from inter-platoon discovery (if any)
        self.selected_platoon_entry: Optional[PlatoonEntry] = None
        
        # Initialize state
        if context.consumer_state is None:
            context.consumer_state = ConsumerState.DISCOVER
    
    def _transition_state(self, new_state: ConsumerState, reason: str = ""):
        """
        Transition to a new state and record metrics (A6).
        
        Args:
            new_state: Target state
            reason: Optional reason for transition
        """
        old_state = self.context.consumer_state
        self.context.consumer_state = new_state
        self.context.metrics.increment('consumer_state', new_state.name)
        
        my_name = get_node_name(self.context.node_id)
        reason_str = f" ({reason})" if reason else ""
        logger.info(f"[{my_name}] State: {old_state.name} → {new_state.name}{reason_str}")
        
        self.context.metrics.log_event(
            'state_transition',
            f"Consumer {my_name}: {old_state.name} -> {new_state.name}" + reason_str,
            level='debug'
        )
    
    def tick(self, timestamp: float):
        """
        Process a protocol tick. Handle timeouts and state transitions.
        
        Args:
            timestamp: Current simulation time
        """
        # Only process if we're in consumer role
        if not self.context.is_consumer():
            return
        
        state = self.context.consumer_state
        
        if state == ConsumerState.DISCOVER:
            self._process_discover()
        elif state == ConsumerState.EVALUATE:
            self._process_evaluate()
        elif state == ConsumerState.WAIT_ACCEPT:
            # Check if we're in backoff waiting period
            if self.current_session.get('next_retry_time') is not None:
                self._check_backoff_timeout(timestamp, 'ACCEPT')
            else:
                self._check_accept_timeout(timestamp)
        elif state == ConsumerState.WAIT_ACKACK:
            # Check if we're in backoff waiting period
            if self.current_session.get('next_retry_time') is not None:
                self._check_backoff_timeout(timestamp, 'ACKACK')
            else:
                self._check_ackack_timeout(timestamp)
    
    def _process_discover(self):
        """
        DISCOVER state: Look for available providers.
        
        Enhanced with inter-platoon discovery:
        1. First checks PlatoonTable for discovered platoons
        2. Falls back to ProviderTable for RREHs and other providers
        
        Transitions to EVALUATE when providers are found.
        """
        # Prune stale entries from platoon table
        self.platoon_table.prune_stale(self.context.current_time)
        
        # Check inter-platoon discovery first
        best_platoon = self._find_best_platoon_from_table()
        if best_platoon:
            self.selected_platoon_entry = best_platoon
            logger.info(f"[Consumer {self.context.node_id}] Found platoon via discovery: "
                       f"{best_platoon.platoon_id.hex()[:8]} with score {best_platoon.score:.3f}")
        
        if self.context.provider_table is None:
            return
        
        # Update efficiency calculations for all providers
        self.efficiency_calc.update_provider_costs()
        
        # Check if we have any providers (excluding blacklisted ones)
        all_providers = self.context.provider_table.get_providers_with_capacity()
        
        # Filter out blacklisted providers
        available_providers = [
            p for p in all_providers 
            if not self._is_provider_blacklisted(p.provider_id)
        ]
        
        if available_providers:
            my_name = get_node_name(self.context.node_id)
            blacklisted_count = len(all_providers) - len(available_providers)
            if blacklisted_count > 0:
                logger.debug(f"[{my_name}] Found {len(available_providers)} providers "
                             f"(skipping {blacklisted_count} blacklisted)")
            else:
                logger.debug(f"[{my_name}] Found {len(available_providers)} providers")
            self.context.consumer_state = ConsumerState.EVALUATE
        elif all_providers:
            # All providers are blacklisted
            my_name = get_node_name(self.context.node_id)
            logger.debug(f"[{my_name}] All {len(all_providers)} providers are blacklisted")
    
    def _process_evaluate(self):
        """
        EVALUATE state: Select the best provider and send offer.
        Filters out blacklisted providers before selection.
        """
        # Create filter function to exclude blacklisted providers
        def not_blacklisted(provider):
            return not self._is_provider_blacklisted(provider.provider_id)
        
        # Use efficiency calculator to find best provider (with blacklist filter)
        evaluation = self.efficiency_calc.select_best_provider(filter_func=not_blacklisted)
        
        if evaluation is None:
            # No suitable provider found, go back to discover
            self.context.consumer_state = ConsumerState.DISCOVER
            return
        
        # Store the evaluation
        self.current_session['evaluation'] = evaluation
        
        # A6: Track provider selection metrics
        if evaluation.is_rreh:
            self.context.metrics.rreh_selections += 1
        else:
            self.context.metrics.platoon_selections += 1
        self.context.metrics.record_timing('detour', evaluation.detour_cost)
        self.context.metrics.record_timing('urgency', evaluation.urgency_ratio)
        self.context.metrics.record_timing('queue_penalty', evaluation.queue_penalty)
        
        # Log the decision
        my_name = get_node_name(self.context.node_id)
        reason = self.efficiency_calc.get_recommendation_reason(evaluation)
        logger.info(f"[{my_name}] {reason}")
        self.context.metrics.log_event('provider_selected', 
                                       f"Consumer {my_name}: {reason}",
                                       level='info')
        
        # Transition to SEND_OFFER and send
        self.context.consumer_state = ConsumerState.SEND_OFFER
        self._send_offer(evaluation)
    
    def _send_offer(self, evaluation: ProviderEvaluation):
        """
        Send JOIN_OFFER to the selected provider.
        
        Args:
            evaluation: The selected provider evaluation
        """
        provider = evaluation.provider
        
        # Store session info
        self.current_session['provider_id'] = provider.provider_id
        self.current_session['provider_type'] = 'RREH' if evaluation.is_rreh else 'PLATOON'
        self.current_session['start_time'] = self.context.current_time
        self.current_session['timeout_time'] = self.context.current_time + self.ACCEPT_TIMEOUT
        
        # Calculate energy required
        # Energy needed = energy_to_destination + buffer - current_battery
        node = self.context.node
        energy_needed = node.energy_to_destination() + node.min_energy_kwh
        energy_deficit = max(0, energy_needed - node.battery_energy_kwh)
        
        # Add some buffer for charging
        energy_required = energy_deficit + 5.0  # 5 kWh buffer
        
        # Prepare message fields
        energy_req_bytes = struct.pack("!f", energy_required)
        
        # Current position
        lat, lon = node.position()
        pos_bytes = struct.pack("!ff", lat, lon)
        
        # Trajectory (direction vector as destination point)
        if node.destination:
            dest_lat, dest_lon = node.destination
            trajectory_bytes = struct.pack("!ff", dest_lat, dest_lon)
        else:
            trajectory_bytes = b""
        
        # Meeting point (suggest provider's position for now)
        mp_lat, mp_lon = provider.position
        meeting_point_bytes = struct.pack("!ff", mp_lat, mp_lon)
        
        # Create and send message
        msg = JoinOfferMessage(
            ttl=self.context.get_effective_ttl(),
            seq_num=int(self.context.current_time * 1000),  # Use ms for uniqueness
            sender_id=self._get_node_id_bytes(),
            consumer_id=self._get_node_id_bytes(),
            energy_req=energy_req_bytes,
            position=pos_bytes,
            trajectory=trajectory_bytes,
            meeting_point=meeting_point_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
        
        # Transition to WAIT_ACCEPT
        self.context.consumer_state = ConsumerState.WAIT_ACCEPT
        
        my_name = get_node_name(self.context.node_id)
        provider_name = get_node_name(provider.provider_id)
        logger.info(f"[{my_name}] TX JOIN_OFFER to {provider_name} for {energy_required:.1f} kWh")
    
    def handle_join_accept(self, message: JoinAcceptMessage):
        """
        Handle incoming JOIN_ACCEPT message.
        
        Args:
            message: The JOIN_ACCEPT message received
        """
        if self.context.consumer_state != ConsumerState.WAIT_ACCEPT:
            return  # Not expecting accept
        
        provider_id = message.get_tlv_value(TLVType.PROVIDER_ID)
        
        # Verify it's from our selected provider
        if provider_id != self.current_session.get('provider_id'):
            print(f"[Consumer {self.context.node_id}] Received ACCEPT from wrong provider")
            return
        
        # Extract meeting point
        mp_bytes = message.get_tlv_value(TLVType.MEETING_POINT)
        if mp_bytes:
            try:
                meeting_point = struct.unpack("!ff", mp_bytes)
                self.current_session['meeting_point'] = meeting_point
            except struct.error:
                pass
        
        # Extract other info
        bandwidth_bytes = message.get_tlv_value(TLVType.BANDWIDTH)
        if bandwidth_bytes:
            try:
                self.current_session['bandwidth'] = struct.unpack("!f", bandwidth_bytes)[0]
            except struct.error:
                pass
        
        duration_bytes = message.get_tlv_value(TLVType.DURATION)
        if duration_bytes:
            try:
                self.current_session['duration'] = struct.unpack("!f", duration_bytes)[0]
            except struct.error:
                pass
        
        my_name = get_node_name(self.context.node_id)
        provider_name = get_node_name(provider_id)
        logger.info(f"[{my_name}] RX JOIN_ACCEPT from {provider_name}")
        
        # Transition to SEND_ACK
        self.context.consumer_state = ConsumerState.SEND_ACK
        self._send_ack()
    
    def _send_ack(self):
        """Send ACK to provider."""
        msg = AckMessage(
            ttl=self.context.get_effective_ttl(),
            seq_num=int(self.context.current_time * 1000),
            sender_id=self._get_node_id_bytes(),
            consumer_id=self._get_node_id_bytes()
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
        
        my_name = get_node_name(self.context.node_id)
        logger.debug(f"[{my_name}] TX ACK")
        
        # Transition to WAIT_ACKACK
        self.context.consumer_state = ConsumerState.WAIT_ACKACK
        self.current_session['timeout_time'] = self.context.current_time + self.ACKACK_TIMEOUT
    
    def handle_ackack(self, message: AckAckMessage):
        """
        Handle incoming ACKACK message.
        
        Args:
            message: The ACKACK message received
        """
        if self.context.consumer_state != ConsumerState.WAIT_ACKACK:
            return
        
        provider_id = message.get_tlv_value(TLVType.PROVIDER_ID)
        
        if provider_id != self.current_session.get('provider_id'):
            return
        
        my_name = get_node_name(self.context.node_id)
        provider_name = get_node_name(provider_id)
        logger.info(f"[{my_name}] RX ACKACK from {provider_name} - Session BOOKED!")
        
        # Transition to ALLOCATED
        self.context.consumer_state = ConsumerState.ALLOCATED
        
        # Store selected provider info in context
        self.context.selected_provider = self.current_session['provider_id']
        self.context.selected_provider_type = self.current_session['provider_type']
        
        # If joining a platoon, update role
        if self.current_session['provider_type'] == 'PLATOON':
            # Note: Full platoon joining is handled by PlatoonHeadHandler
            # For now, just mark as allocated
            pass
    
    def _check_accept_timeout(self, timestamp: float):
        """Check for JOIN_ACCEPT timeout."""
        if timestamp > self.current_session.get('timeout_time', float('inf')):
            self._handle_timeout('ACCEPT')
    
    def _check_ackack_timeout(self, timestamp: float):
        """Check for ACKACK timeout."""
        if timestamp > self.current_session.get('timeout_time', float('inf')):
            self._handle_timeout('ACKACK')
    
    def _check_backoff_timeout(self, timestamp: float, timeout_type: str):
        """
        Check if backoff period has elapsed and retry should be sent.
        
        Args:
            timestamp: Current simulation time
            timeout_type: Type of timeout ('ACCEPT' or 'ACKACK')
        """
        next_retry_time = self.current_session.get('next_retry_time')
        
        if next_retry_time is None:
            return
        
        if timestamp >= next_retry_time:
            # Backoff period elapsed, send retry
            print(f"[Consumer {self.context.node_id}] Backoff elapsed, sending retry")
            
            # Clear backoff state
            self.current_session['next_retry_time'] = None
            
            if timeout_type == 'ACCEPT':
                # Re-send offer
                evaluation = self.current_session.get('evaluation')
                if evaluation:
                    self._send_offer(evaluation)
            else:
                # Re-send ACK
                self._send_ack()
    
    def _handle_timeout(self, timeout_type: str):
        """
        Handle message timeout with exponential backoff.
        
        Args:
            timeout_type: Type of timeout ('ACCEPT' or 'ACKACK')
        """
        retries = self.current_session.get('retries', 0)
        
        if retries < self.MAX_RETRIES:
            # Calculate backoff delay for this attempt
            backoff_delay = self._calculate_backoff(retries)
            self.current_session['retries'] = retries + 1
            self.current_session['backoff_delay'] = backoff_delay
            self.current_session['next_retry_time'] = self.context.current_time + backoff_delay
            
            # A6: Track retry metrics
            self.context.metrics.total_retries += 1
            self.context.metrics.record_timing('backoff', backoff_delay)
            
            print(f"[Consumer {self.context.node_id}] {timeout_type} timeout, "
                  f"retry {retries + 1}/{self.MAX_RETRIES} with backoff {backoff_delay:.2f}s")
            self.context.metrics.log_event('retry', 
                                          f"Consumer {self.context.node_id}: {timeout_type} timeout, "
                                          f"retry {retries + 1}/{self.MAX_RETRIES}",
                                          level='warning')
            
            # Don't resend immediately - wait for backoff
            # The retry will be triggered in _check_backoff_timeout()
        else:
            # Max retries reached, blacklist provider and re-evaluate
            provider_id = self.current_session.get('provider_id')
            
            if provider_id:
                # Add to blacklist
                blacklist_until = self.context.current_time + ProtocolConfig.BLACKLIST_DURATION
                self.blacklisted_providers[provider_id] = blacklist_until
                
                # A6: Track blacklist metrics
                self.context.metrics.total_blacklist_events += 1
                
                print(f"[Consumer {self.context.node_id}] Max retries reached, "
                      f"provider {provider_id.hex()[:8]} blacklisted until "
                      f"t={blacklist_until:.1f}s")
                self.context.metrics.log_event('blacklist', 
                                              f"Consumer {self.context.node_id}: "
                                              f"Provider {provider_id.hex()[:8]} blacklisted",
                                              level='warning')
                
                # Remove from provider table
                if self.context.provider_table:
                    self.context.provider_table.remove_provider(provider_id)
            
            self._reset_session()
            self.context.consumer_state = ConsumerState.DISCOVER
    
    def _reset_session(self):
        """Reset the current session state."""
        self.current_session = {
            'provider_id': None,
            'provider_type': None,
            'meeting_point': None,
            'start_time': 0.0,
            'timeout_time': 0.0,
            'retries': 0,
            'evaluation': None,
            'next_retry_time': None,
            'backoff_delay': 0.0,
        }
    
    def _calculate_backoff(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay with jitter.
        
        Formula: base_delay * (2^attempt) + random_jitter
        
        Args:
            attempt: The retry attempt number (0-indexed)
            
        Returns:
            Backoff delay in seconds (minimum 0.1s)
        """
        base_delay = ProtocolConfig.RETRY_BASE_DELAY * (2 ** attempt)
        jitter = random.uniform(-ProtocolConfig.RETRY_MAX_JITTER, 
                               ProtocolConfig.RETRY_MAX_JITTER)
        return max(0.1, base_delay + jitter)  # Minimum 0.1s to avoid zero delay
    
    def _is_provider_blacklisted(self, provider_id: bytes) -> bool:
        """
        Check if a provider is currently blacklisted.
        
        Automatically removes expired blacklist entries.
        
        Args:
            provider_id: The provider ID to check
            
        Returns:
            True if provider is blacklisted, False otherwise
        """
        if provider_id in self.blacklisted_providers:
            if self.context.current_time < self.blacklisted_providers[provider_id]:
                return True
            else:
                # Blacklist expired, remove it
                del self.blacklisted_providers[provider_id]
        return False
    
    def start_travel(self):
        """
        Transition to TRAVEL state.
        Called when consumer should start moving toward meeting point.
        """
        if self.context.consumer_state == ConsumerState.ALLOCATED:
            self.context.consumer_state = ConsumerState.TRAVEL
            print(f"[Consumer {self.context.node_id}] Starting travel to meeting point")
    
    def start_charging(self):
        """
        Transition to CHARGE state.
        Called when consumer arrives at meeting point and charging begins.
        """
        if self.context.consumer_state == ConsumerState.TRAVEL:
            self.context.consumer_state = ConsumerState.CHARGE
            print(f"[Consumer {self.context.node_id}] Charging started")
    
    def finish_charging(self):
        """
        Transition to LEAVE state.
        Called when charging session completes.
        """
        if self.context.consumer_state == ConsumerState.CHARGE:
            self.context.consumer_state = ConsumerState.LEAVE
            print(f"[Consumer {self.context.node_id}] Charging complete, leaving")
            
            # Reset for next session
            self._reset_session()
            self.context.selected_provider = None
            self.context.selected_provider_type = None
            
            # Clear blacklist when starting fresh discovery cycle
            self.blacklisted_providers.clear()
            
            # Return to DISCOVER for potential future needs
            self.context.consumer_state = ConsumerState.DISCOVER
    
    def _get_node_id_bytes(self) -> bytes:
        """Get node ID as 6 bytes for message sender_id field."""
        node_id = self.context.node_id
        if isinstance(node_id, bytes):
            return node_id[:6].ljust(6, b'\x00')
        elif isinstance(node_id, int):
            return node_id.to_bytes(6, 'big')
        else:
            return str(node_id).encode()[:6].ljust(6, b'\x00')
    
    def get_state(self) -> ConsumerState:
        """Get current consumer state."""
        return self.context.consumer_state
    
    def is_active(self) -> bool:
        """Check if consumer is in an active session."""
        active_states = {
            ConsumerState.SEND_OFFER,
            ConsumerState.WAIT_ACCEPT,
            ConsumerState.SEND_ACK,
            ConsumerState.WAIT_ACKACK,
            ConsumerState.ALLOCATED,
            ConsumerState.TRAVEL,
            ConsumerState.CHARGE
        }
        return self.context.consumer_state in active_states
    
    # ==========================================================================
    # Inter-Platoon Discovery Methods
    # ==========================================================================
    
    def handle_platoon_announce(self, message: PlatoonAnnounceMessage):
        """
        Handle incoming PLATOON_ANNOUNCE message.
        
        Updates the PlatoonTable with the announced platoon's info.
        
        Args:
            message: The PLATOON_ANNOUNCE message received
        """
        # Extract platoon info from TLVs
        platoon_id = message.get_tlv_value(TLVType.PLATOON_ID)
        head_id = message.get_tlv_value(TLVType.HEAD_ID)
        
        if not platoon_id or not head_id:
            return  # Invalid announce
        
        # Extract position
        pos_bytes = message.get_tlv_value(TLVType.POSITION)
        if pos_bytes:
            try:
                position = struct.unpack("!ff", pos_bytes)
            except struct.error:
                position = (0.0, 0.0)
        else:
            position = (0.0, 0.0)
        
        # Extract destination
        dest_bytes = message.get_tlv_value(TLVType.DESTINATION)
        if dest_bytes:
            try:
                destination = struct.unpack("!ff", dest_bytes)
            except struct.error:
                destination = (0.0, 0.0)
        else:
            destination = (0.0, 0.0)
        
        # Extract direction vector
        dir_bytes = message.get_tlv_value(TLVType.DIRECTION_VECTOR)
        if dir_bytes:
            try:
                direction = struct.unpack("!ff", dir_bytes)
            except struct.error:
                direction = (0.0, 0.0)
        else:
            direction = (0.0, 0.0)
        
        # Extract available slots
        slots_bytes = message.get_tlv_value(TLVType.AVAILABLE_SLOTS)
        if slots_bytes:
            try:
                available_slots = struct.unpack("!B", slots_bytes)[0]
            except struct.error:
                available_slots = 0
        else:
            available_slots = 0
        
        # Extract surplus energy
        energy_bytes = message.get_tlv_value(TLVType.SURPLUS_ENERGY)
        if energy_bytes:
            try:
                surplus_energy = struct.unpack("!f", energy_bytes)[0]
            except struct.error:
                surplus_energy = 0.0
        else:
            surplus_energy = 0.0
        
        # Extract formation efficiency
        eff_bytes = message.get_tlv_value(TLVType.FORMATION_EFFICIENCY)
        if eff_bytes:
            try:
                formation_efficiency = struct.unpack("!f", eff_bytes)[0]
            except struct.error:
                formation_efficiency = 0.0
        else:
            formation_efficiency = 0.0
        
        # Update platoon table
        self.platoon_table.update_from_announce(
            platoon_id=platoon_id,
            head_id=head_id,
            position=position,
            direction=direction,
            destination=destination,
            surplus_energy=surplus_energy,
            available_slots=available_slots,
            formation_efficiency=formation_efficiency,
            timestamp=self.context.current_time
        )
        
        logger.debug(f"[Consumer {self.context.node_id}] Updated platoon entry: "
                    f"{platoon_id.hex()[:8]} with {surplus_energy:.1f}kWh, {available_slots} slots")
    
    def _find_best_platoon_from_table(self) -> Optional[PlatoonEntry]:
        """
        Find the best platoon from the PlatoonTable using virtual edge scoring.
        
        Returns:
            Best matching PlatoonEntry, or None if no suitable platoons
        """
        node = self.context.node
        
        # Get consumer's position and direction
        consumer_position = node.position()
        consumer_direction = node.direction_vector()
        
        # Calculate energy needed
        energy_needed = node.energy_to_destination() + node.min_energy_kwh
        energy_deficit = max(0, energy_needed - node.battery_energy_kwh)
        
        if energy_deficit <= 0:
            return None  # No charging needed
        
        # Find best platoon
        return self.platoon_table.find_best_platoon(
            consumer_position=consumer_position,
            consumer_direction=consumer_direction,
            energy_needed=energy_deficit
        )
    
    def get_discovered_platoons(self) -> int:
        """Get number of platoons discovered via inter-platoon discovery."""
        return len(self.platoon_table)
    
    def get_platoon_table(self) -> PlatoonTable:
        """Get the PlatoonTable for external inspection."""
        return self.platoon_table



