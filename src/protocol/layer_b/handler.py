from src.messages.messages import MessageType, PAMessage, GridStatusMessage, TLVType
from .provider_table import ProviderTable, ProviderType
from src.protocol.node_registry import get_node_name
import struct
import logging

logger = logging.getLogger('mvccp.layer_b')

class ProviderAnnouncementHandler:
    def __init__(self, context):
        self.context = context
        self.provider_table = ProviderTable(context)
        self.context.provider_table = self.provider_table  # Link back
        
        # Deduplication cache for flooding: { (sender_id, seq_num) : timestamp }
        self.seen_messages = {} 

    def handle_pa(self, message: PAMessage):
        # 1. Deduplication using (originator_id, seq_num) per Section 6.1
        # Note: sender_id is the originator under Option A contract
        msg_key = (message.header.sender_id, message.header.seq_num)
        if msg_key in self.seen_messages:
            my_name = get_node_name(self.context.node_id)
            sender_name = get_node_name(message.header.sender_id)
            logger.debug(f"[{my_name}] DROP PA (duplicate from {sender_name})")
            return  # Drop duplicate
        self.seen_messages[msg_key] = self.context.current_time

        # Track PA receive rate for adaptive TTL mode
        self._update_pa_counter()
        
        # 2. Extract Info & Update Table
        p_id = message.get_tlv_value(TLVType.PROVIDER_ID)
        p_type_bytes = message.get_tlv_value(TLVType.PROVIDER_TYPE)
        p_type = int.from_bytes(p_type_bytes, 'big') if p_type_bytes else 0
        
        # Deserialize Fields
        # Energy (!f)
        energy_bytes = message.get_tlv_value(TLVType.ENERGY_AVAILABLE)
        energy = 0.0
        if energy_bytes:
            try:
                energy = struct.unpack("!f", energy_bytes)[0]
            except struct.error:
                pass
            
        # Position (!ff)
        pos_bytes = message.get_tlv_value(TLVType.POSITION)
        position = (0.0, 0.0)
        if pos_bytes:
            try:
                position = struct.unpack("!ff", pos_bytes)
            except struct.error:
                pass
        
        # Destination (!ff)
        dest_bytes = message.get_tlv_value(TLVType.DESTINATION)
        destination = (0.0, 0.0)
        if dest_bytes:
            try:
                destination = struct.unpack("!ff", dest_bytes)
            except struct.error:
                pass
        
        # Direction (!ff) - normalized vector
        dir_bytes = message.get_tlv_value(TLVType.DIRECTION)
        direction = (0.0, 0.0)
        if dir_bytes:
            try:
                direction = struct.unpack("!ff", dir_bytes)
            except struct.error:
                pass
        
        # Platoon ID (6 bytes)
        platoon_id = message.get_tlv_value(TLVType.PLATOON_ID) or b""
        
        # Platoon size (!B)
        size_bytes = message.get_tlv_value(TLVType.PLATOON_SIZE)
        platoon_size = 0
        if size_bytes:
            try:
                platoon_size = struct.unpack("!B", size_bytes)[0]
            except struct.error:
                pass
        
        # Available slots (!B)
        slots_bytes = message.get_tlv_value(TLVType.AVAILABLE_SLOTS)
        available_slots = 6  # Default max
        if slots_bytes:
            try:
                available_slots = struct.unpack("!B", slots_bytes)[0]
            except struct.error:
                pass
        
        # Renewable fraction (!f) - for RREHs
        renewable_bytes = message.get_tlv_value(TLVType.RENEWABLE_FRACTION)
        renewable_fraction = 0.0
        if renewable_bytes:
            try:
                renewable_fraction = struct.unpack("!f", renewable_bytes)[0]
            except struct.error:
                pass

        info = {
            'type': p_type,
            'energy': energy, 
            'position': position,
            'destination': destination,
            'direction': direction,
            'platoon_id': platoon_id,
            'platoon_size': platoon_size,
            'available_slots': available_slots,
            'renewable_fraction': renewable_fraction,
        }
        
        if p_id:
            self.provider_table.update_provider(p_id, info)
            
            # Log PA reception
            my_name = get_node_name(self.context.node_id)
            provider_name = get_node_name(p_id)
            type_names = {0: 'UNKNOWN', 1: 'PLATOON_HEAD', 2: 'RREH'}
            type_name = type_names.get(p_type, f'TYPE_{p_type}')
            logger.debug(f"[{my_name}] RX PA from {provider_name}: type={type_name}, energy={energy:.1f}kWh")
            
        # 3. MPR Forwarding Logic (Section 6.1: use PREVIOUS_HOP for forwarding decision)
        if message.header.ttl > 0:
            # Extract previous hop from TLV (immediate transmitter of this hop)
            previous_hop_bytes = message.get_tlv_value(TLVType.PREVIOUS_HOP)
            
            # If PREVIOUS_HOP is missing, this is the first hop (originator)
            # Use sender_id (originator) as previous_hop for backward compatibility
            if previous_hop_bytes is None:
                previous_hop = message.header.sender_id
            else:
                previous_hop = previous_hop_bytes
            
            # Check if I am an MPR for the previous hop (immediate transmitter)
            if previous_hop in self.context.mpr_selector_set:
                self._forward_pa(message)

    def _forward_pa(self, message: PAMessage):
        """
        Forward PA message with updated TTL and PREVIOUS_HOP.
        
        Section 6.1: Forwarders MUST overwrite PREVIOUS_HOP with their own node_id
        before re-broadcasting. The originator ID (sender_id) remains unchanged.
        """
        # Decrement TTL
        message.header.ttl -= 1
        
        # Update or add PREVIOUS_HOP TLV with my node_id (I am the new immediate transmitter)
        # First, remove existing PREVIOUS_HOP TLV if present
        message.tlvs = [tlv for tlv in message.tlvs if tlv.type != TLVType.PREVIOUS_HOP]
        
        # Add new PREVIOUS_HOP TLV with my node_id
        from src.messages.messages import TLV
        message.tlvs.append(TLV(TLVType.PREVIOUS_HOP, self.context.node_id))
        
        # Re-encode with updated TTL and PREVIOUS_HOP
        # Note: header.sender_id remains the originator ID (unchanged across hops)
        encoded_msg = message.encode()
        
        if self.context.send_callback:
            self.context.send_callback(encoded_msg)
            
            # Log forwarding
            my_name = get_node_name(self.context.node_id)
            originator = get_node_name(message.header.sender_id)
            logger.debug(f"[{my_name}] FWD PA from {originator} (TTL={message.header.ttl})")

    def handle_grid_status(self, message: GridStatusMessage):
        """
        Handle GRID_STATUS message from an RREH.
        Updates the provider table with RREH-specific information.
        
        Args:
            message: The GRID_STATUS message
        """
        # Extract Hub ID (provider ID)
        hub_id = message.get_tlv_value(TLVType.HUB_ID)
        if hub_id is None:
            hub_id = message.header.sender_id
        
        # Renewable fraction (!f)
        renewable_bytes = message.get_tlv_value(TLVType.RENEWABLE_FRACTION)
        renewable_fraction = 1.0  # Default 100% renewable
        if renewable_bytes:
            try:
                renewable_fraction = struct.unpack("!f", renewable_bytes)[0]
            except struct.error:
                pass
        
        # Available power (!f) kW
        power_bytes = message.get_tlv_value(TLVType.AVAILABLE_POWER)
        available_power = 0.0
        if power_bytes:
            try:
                available_power = struct.unpack("!f", power_bytes)[0]
            except struct.error:
                pass
        
        # Max sessions (!B)
        max_sessions_bytes = message.get_tlv_value(TLVType.MAX_SESSIONS)
        max_sessions = 1
        if max_sessions_bytes:
            try:
                max_sessions = struct.unpack("!B", max_sessions_bytes)[0]
            except struct.error:
                pass
        
        # Queue time (!f) seconds
        queue_bytes = message.get_tlv_value(TLVType.QUEUE_TIME)
        queue_time = 0.0
        if queue_bytes:
            try:
                queue_time = struct.unpack("!f", queue_bytes)[0]
            except struct.error:
                pass
        
        # Operational state (!B) - decode from byte
        op_state_bytes = message.get_tlv_value(TLVType.OPERATIONAL_STATE)
        operational_state = 'normal'
        if op_state_bytes:
            try:
                op_code = struct.unpack("!B", op_state_bytes)[0]
                op_states = {0: 'normal', 1: 'congested', 2: 'limited', 3: 'offline'}
                operational_state = op_states.get(op_code, 'normal')
            except struct.error:
                pass
        
        # Get existing provider entry to preserve position if available
        existing = self.provider_table.get_provider(hub_id)
        position = existing.position if existing else (0.0, 0.0)
        
        info = {
            'type': ProviderType.RREH,
            'energy': available_power,  # Use available_power as energy metric
            'position': position,
            'renewable_fraction': renewable_fraction,
            'available_power': available_power,
            'max_sessions': max_sessions,
            'queue_time': queue_time,
            'operational_state': operational_state,
        }
        
        self.provider_table.update_provider(hub_id, info)
        
        # Log GRID_STATUS reception
        my_name = get_node_name(self.context.node_id)
        hub_name = get_node_name(hub_id)
        logger.debug(f"[{my_name}] RX GRID_STATUS from {hub_name}: power={available_power:.1f}kW, queue={queue_time:.1f}s")

    def _update_pa_counter(self):
        """
        Update PA receive counter for adaptive TTL mode.
        Resets counter every second.
        """
        current_time = self.context.current_time
        if current_time - self.context.pa_receive_window_start >= 1.0:
            # Reset counter for new window
            self.context.pa_receive_count = 0
            self.context.pa_receive_window_start = current_time
        self.context.pa_receive_count += 1

