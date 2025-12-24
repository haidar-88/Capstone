from messages import PlatoonBeaconMessage, PlatoonStatusMessage, TLVType
import struct

class PlatoonCoordinationHandler:
    def __init__(self, context):
        self.context = context
        self.platoon_members = {} # {vid: status}

    def handle_beacon(self, message: PlatoonBeaconMessage):
        # Implementation for following a platoon leader
        head_id = message.get_tlv_value(TLVType.PROVIDER_ID)
        # print(f"[Platoon] Received Beacon from {head_id}")

    def handle_status(self, message: PlatoonStatusMessage):
        # Implementation for leader tracking members
        vid = message.get_tlv_value(TLVType.NODE_ID)
        battery_bytes = message.get_tlv_value(TLVType.BATTERY_LEVEL)
        
        battery = -1.0
        if battery_bytes:
            try:
                battery = struct.unpack("!f", battery_bytes)[0]
            except: pass
            
        # print(f"[Platoon] Status update from {vid}: Battery={battery}")
