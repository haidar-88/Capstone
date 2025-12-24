from messages import (
    MessageType, JoinOfferMessage, JoinAcceptMessage, AckMessage, AckAckMessage, TLVType
)
from .states import ConsumerState, ProviderState
import time
import struct

class ChargingCoordinationHandler:
    def __init__(self, context):
        self.context = context
        self.context.consumer_state = ConsumerState.DISCOVER
        self.context.provider_state = ProviderState.ANNOUNCE
        
        self.current_session = {} # Stores session info (provider_id, deadlines, etc.)

    def tick(self, timestamp):
        # Handle timeouts
        pass

    # --- Consumer Side Logic ---
    
    def process_discovery(self):
        """Called periodically when in DISCOVER state"""
        best_provider = self.context.provider_table.get_best_provider()
        if best_provider:
            self.context.consumer_state = ConsumerState.EVALUATE
            print(f"[Consumer] Found provider {best_provider.provider_id}")
            # Trigger transition to SEND_OFFER immediately for now
            self._send_offer(best_provider)

    def _send_offer(self, provider):
        self.context.consumer_state = ConsumerState.WAIT_ACCEPT
        self.current_session['provider_id'] = provider.provider_id
        
        # Prepare Data
        # Energy Req: 50.0 kWh (placeholder logic for requirement)
        energy_req_bytes = struct.pack("!f", 50.0) 
        
        # Position !ff
        lat, lon = self.context.node.latitude, self.context.node.longitude
        pos_bytes = struct.pack("!ff", lat, lon)
        
        msg = JoinOfferMessage(
            ttl=self.context.msg_ttl,
            seq_num=int(self.context.current_time),
            sender_id=self.context.node_id,
            consumer_id=self.context.node_id,
            energy_req=energy_req_bytes,
            position=pos_bytes
        )
        
        if self.context.send_callback:
            self.context.send_callback(msg.encode())
        print(f"[Consumer] Sent JOIN_OFFER to {provider.provider_id}")

    def handle_join_accept(self, message: JoinAcceptMessage):
        if self.context.consumer_state != ConsumerState.WAIT_ACCEPT:
            return
            
        provider_id = message.get_tlv_value(TLVType.PROVIDER_ID)
        
        # Unpack Bandwidth/Duration if needed
        # band_bytes = message.get_tlv_value(TLVType.BANDWIDTH)
        # duration_bytes = message.get_tlv_value(TLVType.DURATION)
        
        if provider_id == self.current_session.get('provider_id'):
            print("[Consumer] Received JOIN_ACCEPT. Sending ACK.")
            self.context.consumer_state = ConsumerState.WAIT_ACKACK
            
            # Send ACK
            ack_msg = AckMessage(
                ttl=self.context.msg_ttl,
                seq_num=int(self.context.current_time),
                sender_id=self.context.node_id,
                consumer_id=self.context.node_id
            )
            if self.context.send_callback:
                self.context.send_callback(ack_msg.encode())

    def handle_ackack(self, message: AckAckMessage):
        if self.context.consumer_state != ConsumerState.WAIT_ACKACK:
            return
        print("[Consumer] Received ACKACK. Session BOOKED.")
        self.context.consumer_state = ConsumerState.ALLOCATED

    # --- Provider Side Logic ---

    def handle_join_offer(self, message: JoinOfferMessage):
        consumer_id = message.get_tlv_value(TLVType.CONSUMER_ID)
        
        # Unpack Energy Req
        req_bytes = message.get_tlv_value(TLVType.ENERGY_REQUIRED)
        req_energy = 0.0
        if req_bytes:
             req_energy = struct.unpack("!f", req_bytes)[0]
             
        print(f"[Provider] Received OFFER from {consumer_id} for {req_energy}kWh. Accepting.")
        
        # Send JOIN_ACCEPT
        # Pack meeting point !ff (Using self position for now)
        lat, lon = self.context.node.latitude, self.context.node.longitude
        mp_bytes = struct.pack("!ff", lat, lon)
        
        accept_msg = JoinAcceptMessage(
            ttl=self.context.msg_ttl,
            seq_num=int(self.context.current_time),
            sender_id=self.context.node_id,
            provider_id=self.context.node_id,
            meeting_point=mp_bytes
        )
        if self.context.send_callback:
            self.context.send_callback(accept_msg.encode())
            
        self.context.provider_state = ProviderState.WAIT_ACK

    def handle_ack(self, message: AckMessage):
        print("[Provider] Received ACK. Sending ACKACK.")
        
        ackack_msg = AckAckMessage(
            ttl=self.context.msg_ttl,
            seq_num=int(self.context.current_time),
            sender_id=self.context.node_id,
            provider_id=self.context.node_id
        )
        if self.context.send_callback:
            self.context.send_callback(ackack_msg.encode())
            
        self.context.provider_state = ProviderState.CHARGE
