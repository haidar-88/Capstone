from messages import MessageType, PAMessage, TLVType
from .provider_table import ProviderTable
import struct
from .provider_table import ProviderTable

class ProviderAnnouncementHandler:
    def __init__(self, context):
        self.context = context
        self.provider_table = ProviderTable(context)
        self.context.provider_table = self.provider_table # Link back
        
        # Deduplication cache for flooding: { (sender_id, seq_num) : timestamp }
        self.seen_messages = {} 

    def handle_pa(self, message: PAMessage):
        # 1. Deduplication
        msg_key = (message.header.sender_id, message.header.seq_num)
        if msg_key in self.seen_messages:
            return # Drop duplicate
        self.seen_messages[msg_key] = self.context.current_time
        
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
            except: pass
            
        # Position (!ff)
        pos_bytes = message.get_tlv_value(TLVType.POSITION)
        position = (0.0, 0.0)
        if pos_bytes:
            try:
                position = struct.unpack("!ff", pos_bytes)
            except: pass

        info = {
            'type': p_type,
            'energy': energy, 
            'position': position
        }
        
        if p_id:
            self.provider_table.update_provider(p_id, info)
            
        # 3. MPR Forwarding Logic
        if message.header.ttl > 0:
            previous_hop = message.header.sender_id 
            
            # Check if I am an MPR for the sender
            if previous_hop in self.context.mpr_selector_set:
                self._forward_pa(message)

    def _forward_pa(self, message: PAMessage):
        # Decrement TTL
        message.header.ttl -= 1
        
        # In multi-hop, usually we preserve Originator. 
        # Here we just re-flood the same object with decremented TTL.
        # We need to re-encode it because TTL changed.
        encoded_msg = message.encode()
        
        if self.context.send_callback:
            self.context.send_callback(encoded_msg)

