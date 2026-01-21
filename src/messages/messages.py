import struct
from enum import IntEnum
from typing import List, Any, Optional

class MessageType(IntEnum):
    HELLO = 1
    PA = 2
    JOIN_OFFER = 3
    JOIN_ACCEPT = 4
    ACK = 5
    ACKACK = 6
    PLATOON_BEACON = 7
    PLATOON_STATUS = 8
    GRID_STATUS = 9
    PLATOON_ANNOUNCE = 10  # PH broadcasts platoon capabilities for inter-platoon discovery

class TLVType(IntEnum):
    # Provisional assignments
    NODE_ID = 1
    NEIGHBOR_LIST = 2
    METRICS = 3 
    PROVIDER_FLAG = 4
    NODE_ATTRIBUTES = 5
    
    PROVIDER_ID = 10
    PROVIDER_TYPE = 11
    POSITION = 12
    DESTINATION = 13
    PLATOON_SIZE = 14
    ENERGY_AVAILABLE = 15
    DIRECTION = 16
    
    CONSUMER_ID = 20
    ENERGY_REQUIRED = 21
    TRAJECTORY = 22
    MEETING_POINT = 23
    
    BANDWIDTH = 30
    DURATION = 31
    PLATOON_MEMBERS = 32
    TOPOLOGY = 33
    
    TIMESTAMP = 40
    VELOCITY = 41
    AVAILABLE_SLOTS = 42
    ROUTE = 43
    
    BATTERY_LEVEL = 50
    RELATIVE_INDEX = 51
    RECEIVE_RATE = 52
    
    HUB_ID = 60
    RENEWABLE_FRACTION = 61
    AVAILABLE_POWER = 62
    MAX_SESSIONS = 63
    QUEUE_TIME = 64
    PRICE = 65
    OPERATIONAL_STATE = 66
    
    # Platoon-specific (Section 5.6)
    PLATOON_ID = 70
    HEAD_ID = 71
    HEAD_POSITION = 72
    
    # Forwarding identity (Section 6.1, Option A)
    PREVIOUS_HOP = 80  # 6 bytes - immediate transmitter of this hop
    
    # Formation optimization (Edge-based platoon coordination)
    FORMATION_POSITIONS = 81  # Target (x,y) per member: [node_id(6B), x(4B), y(4B)] * N
    
    # Inter-platoon discovery
    SURPLUS_ENERGY = 82       # Available shareable energy in kWh (4 bytes float)
    DIRECTION_VECTOR = 83     # Platoon heading as normalized (dx, dy) (8 bytes, 2 floats)
    FORMATION_EFFICIENCY = 84 # Current formation efficiency 0.0-1.0 (4 bytes float)

class MessageHeader:
    # Format: ! H B I 6s H
    # H: msg_type (2 bytes)
    # B: ttl (1 byte)
    # I: sequence_number (4 bytes)
    # 6s: sender_id (6 bytes, typically MAC address style)
    # H: payload_length (2 bytes)
    FORMAT = "!HBI6sH"
    SIZE = struct.calcsize(FORMAT)

    def __init__(self, msg_type: int, ttl: int, seq_num: int, sender_id: bytes, payload_len: int = 0):
        self.msg_type = msg_type
        self.ttl = ttl
        self.seq_num = seq_num
        self.sender_id = sender_id # Expecting 6 bytes
        self.payload_len = payload_len

    def pack(self) -> bytes:
        return struct.pack(self.FORMAT, self.msg_type, self.ttl, self.seq_num, self.sender_id, self.payload_len)

    @classmethod
    def unpack(cls, data: bytes) -> 'MessageHeader':
        unpacked = struct.unpack(cls.FORMAT, data)
        return cls(unpacked[0], unpacked[1], unpacked[2], unpacked[3], unpacked[4])

class TLV:
    def __init__(self, tlv_type: int, value: bytes):
        self.type = tlv_type
        self.length = len(value)
        self.value = value

    def pack(self) -> bytes:
        # T (1 byte), L (1 byte), V (lengths bytes)
        # Note: Length is 1 byte, so max value size is 255 bytes.
        if len(self.value) > 255:
            raise ValueError(f"TLV value too long: {len(self.value)} bytes (max 255)")
        return struct.pack("!BB", self.type, len(self.value)) + self.value

    @classmethod
    def unpack_from(cls, data: bytes, offset: int = 0) -> 'TLV':
        if len(data) < offset + 2:
            raise ValueError("Data too short for TLV header")
        
        type, length = struct.unpack_from("!BB", data, offset)
        if len(data) < offset + 2 + length:
            raise ValueError(f"Data too short for TLV value (expected {length}, got {len(data) - offset - 2})")
            
        value = data[offset+2 : offset+2+length]
        return cls(type, value)

class MVCCPMessage:
    def __init__(self, msg_type: MessageType, ttl: int, seq_num: int, sender_id: bytes):
        self.header = MessageHeader(msg_type, ttl, seq_num, sender_id)
        self.tlvs: List[TLV] = []

    def add_tlv(self, tlv: TLV):
        self.tlvs.append(tlv)
        self.header.payload_len += (2 + len(tlv.value))

    def encode(self) -> bytes:
        payload = b"".join(tlv.pack() for tlv in self.tlvs)
        # Ensure header payload length matches actual payload
        self.header.payload_len = len(payload) 
        return self.header.pack() + payload

    @classmethod
    def decode(cls, data: bytes) -> 'MVCCPMessage':
        if len(data) < MessageHeader.SIZE:
            raise ValueError("Data too short for MVCCP header")
            
        header = MessageHeader.unpack(data[:MessageHeader.SIZE])
        
        # Determine subclass based on msg_type
        msg_class = _MESSAGE_TYPE_MAP.get(header.msg_type, MVCCPMessage)
        
        # Instantiate without calling __init__ to avoid signature mismatches
        msg = msg_class.__new__(msg_class)
        msg.header = header
        msg.tlvs = []
        
        payload = data[MessageHeader.SIZE : MessageHeader.SIZE + header.payload_len]
        offset = 0
        while offset < len(payload):
            tlv = TLV.unpack_from(payload, offset)
            msg.tlvs.append(tlv)
            offset += (2 + tlv.length)
            
        return msg
        
    def get_tlv_value(self, tlv_type: int) -> Optional[bytes]:
        for tlv in self.tlvs:
            if tlv.type == tlv_type:
                return tlv.value
        return None

# --- Specific Message Implementations ---

class HelloMessage(MVCCPMessage):
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, neighbor_list: bytes = b"", metrics: bytes = b"", provider_flag: bytes = b""):
        super().__init__(MessageType.HELLO, ttl, seq_num, sender_id)
        if neighbor_list:
            self.add_tlv(TLV(TLVType.NEIGHBOR_LIST, neighbor_list))
        if metrics:
            self.add_tlv(TLV(TLVType.METRICS, metrics))
        if provider_flag:
            self.add_tlv(TLV(TLVType.PROVIDER_FLAG, provider_flag))

class PAMessage(MVCCPMessage):
    """
    Section 5.2: Provider Announcement - multi-hop advertisement.
    Contains: provider_id, provider_type, position, destination, 
    direction, platoon_size, energy_available, renewable_fraction.
    
    Section 6.1: PREVIOUS_HOP TLV is required for multi-hop forwarding
    when PHY metadata is not available.
    """
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, 
                 provider_id: bytes = b"", 
                 provider_type: bytes = b"",
                 position: bytes = b"",
                 destination: bytes = b"",
                 platoon_size: bytes = b"",
                 energy_available: bytes = b"",
                 direction: bytes = b"",
                 renewable_fraction: bytes = b"",
                 previous_hop: bytes = b""):
        super().__init__(MessageType.PA, ttl, seq_num, sender_id)
        if provider_id:
             self.add_tlv(TLV(TLVType.PROVIDER_ID, provider_id))
        if provider_type:
             self.add_tlv(TLV(TLVType.PROVIDER_TYPE, provider_type))
        if position:
             self.add_tlv(TLV(TLVType.POSITION, position))
        if destination:
             self.add_tlv(TLV(TLVType.DESTINATION, destination))
        if platoon_size:
             self.add_tlv(TLV(TLVType.PLATOON_SIZE, platoon_size))
        if energy_available:
             self.add_tlv(TLV(TLVType.ENERGY_AVAILABLE, energy_available))
        if direction:
             self.add_tlv(TLV(TLVType.DIRECTION, direction))
        if renewable_fraction:
             self.add_tlv(TLV(TLVType.RENEWABLE_FRACTION, renewable_fraction))
        if previous_hop:
             self.add_tlv(TLV(TLVType.PREVIOUS_HOP, previous_hop))

class JoinOfferMessage(MVCCPMessage):
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, 
                 consumer_id: bytes = b"", 
                 energy_req: bytes = b"",
                 trajectory: bytes = b"",
                 meeting_point: bytes = b"",
                 position = b""):
        super().__init__(MessageType.JOIN_OFFER, ttl, seq_num, sender_id)
        if consumer_id:
            self.add_tlv(TLV(TLVType.CONSUMER_ID, consumer_id))
        if energy_req:
            self.add_tlv(TLV(TLVType.ENERGY_REQUIRED, energy_req))
        if trajectory:
            self.add_tlv(TLV(TLVType.TRAJECTORY, trajectory))
        if meeting_point:
            self.add_tlv(TLV(TLVType.MEETING_POINT, meeting_point))
        if position:
            self.add_tlv(TLV(TLVType.POSITION, position))

class JoinAcceptMessage(MVCCPMessage):
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, 
                 provider_id: bytes = b"",
                 meeting_point: bytes = b"",
                 bandwidth: bytes = b"",
                 duration: bytes = b"",
                 platoon_members: bytes = b"",
                 topology: bytes = b""):
        super().__init__(MessageType.JOIN_ACCEPT, ttl, seq_num, sender_id)
        if provider_id:
            self.add_tlv(TLV(TLVType.PROVIDER_ID, provider_id))
        if meeting_point:
            self.add_tlv(TLV(TLVType.MEETING_POINT, meeting_point))
        if bandwidth:
            self.add_tlv(TLV(TLVType.BANDWIDTH, bandwidth))
        if duration:
            self.add_tlv(TLV(TLVType.DURATION, duration))
        if platoon_members:
             self.add_tlv(TLV(TLVType.PLATOON_MEMBERS, platoon_members))
        if topology:
             self.add_tlv(TLV(TLVType.TOPOLOGY, topology))

class AckMessage(MVCCPMessage):
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, consumer_id: bytes = b""):
        super().__init__(MessageType.ACK, ttl, seq_num, sender_id)
        if consumer_id:
            self.add_tlv(TLV(TLVType.CONSUMER_ID, consumer_id))

class AckAckMessage(MVCCPMessage):
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, provider_id: bytes = b""):
        super().__init__(MessageType.ACKACK, ttl, seq_num, sender_id)
        if provider_id:
             self.add_tlv(TLV(TLVType.PROVIDER_ID, provider_id))

class PlatoonBeaconMessage(MVCCPMessage):
    """
    Section 5.6: Broadcast by Platoon Head.
    Contains: platoon_id, head_id, timestamp, head position/velocity, 
    available_slots, platoon topology, approximate route.
    
    Extended with formation_positions for edge-based energy optimization:
    Contains target (x,y) positions for each member to optimize energy transfer.
    """
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, 
                 platoon_id: bytes = b"",
                 head_id: bytes = b"",
                 timestamp: bytes = b"",
                 head_position: bytes = b"",
                 velocity: bytes = b"",
                 available_slots: bytes = b"",
                 topology: bytes = b"",
                 route: bytes = b"",
                 formation_positions: bytes = b""):
        super().__init__(MessageType.PLATOON_BEACON, ttl, seq_num, sender_id)
        if platoon_id:
             self.add_tlv(TLV(TLVType.PLATOON_ID, platoon_id))
        if head_id:
             self.add_tlv(TLV(TLVType.HEAD_ID, head_id))
        if timestamp:
             self.add_tlv(TLV(TLVType.TIMESTAMP, timestamp))
        if head_position:
             self.add_tlv(TLV(TLVType.HEAD_POSITION, head_position))
        if velocity:
             self.add_tlv(TLV(TLVType.VELOCITY, velocity))
        if available_slots:
             self.add_tlv(TLV(TLVType.AVAILABLE_SLOTS, available_slots))
        if topology:
             self.add_tlv(TLV(TLVType.TOPOLOGY, topology))
        if route:
             self.add_tlv(TLV(TLVType.ROUTE, route))
        if formation_positions:
             self.add_tlv(TLV(TLVType.FORMATION_POSITIONS, formation_positions))

class PlatoonStatusMessage(MVCCPMessage):
    """
    Section 5.7: Sent by platoon members to the head.
    Contains: platoon_id, vehicle_id, battery_level, relative_platoon_index, receive_rate.
    """
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, 
                 platoon_id: bytes = b"",
                 vehicle_id: bytes = b"", 
                 battery: bytes = b"",
                 relative_index: bytes = b"",
                 receive_rate: bytes = b""):
        super().__init__(MessageType.PLATOON_STATUS, ttl, seq_num, sender_id)
        if platoon_id:
             self.add_tlv(TLV(TLVType.PLATOON_ID, platoon_id))
        if vehicle_id:
             self.add_tlv(TLV(TLVType.NODE_ID, vehicle_id))
        if battery:
             self.add_tlv(TLV(TLVType.BATTERY_LEVEL, battery))
        if relative_index:
             self.add_tlv(TLV(TLVType.RELATIVE_INDEX, relative_index))
        if receive_rate:
             self.add_tlv(TLV(TLVType.RECEIVE_RATE, receive_rate))

class GridStatusMessage(MVCCPMessage):
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes, 
                 hub_id: bytes = b"", 
                 renewable_fraction: bytes = b"",
                 available_power: bytes = b"",
                 max_sessions: bytes = b"",
                 queue_time: bytes = b"",
                 operational_state: bytes = b""):
        super().__init__(MessageType.GRID_STATUS, ttl, seq_num, sender_id)
        if hub_id:
             self.add_tlv(TLV(TLVType.HUB_ID, hub_id))
        if renewable_fraction:
             self.add_tlv(TLV(TLVType.RENEWABLE_FRACTION, renewable_fraction))
        if available_power:
             self.add_tlv(TLV(TLVType.AVAILABLE_POWER, available_power))
        if max_sessions:
             self.add_tlv(TLV(TLVType.MAX_SESSIONS, max_sessions))
        if queue_time:
             self.add_tlv(TLV(TLVType.QUEUE_TIME, queue_time))
        if operational_state:
             self.add_tlv(TLV(TLVType.OPERATIONAL_STATE, operational_state))


class PlatoonAnnounceMessage(MVCCPMessage):
    """
    Inter-platoon discovery message broadcast by Platoon Heads.
    
    Enables consumers to discover and compare multiple platoons to find
    the best one for their needs (direction, energy, slots).
    
    Contains:
    - platoon_id, head_id: Platoon identification
    - position: Current GPS position of platoon head
    - destination: Platoon's target destination
    - available_slots: Number of open slots for new members
    - surplus_energy: Total shareable energy in kWh
    - direction_vector: Normalized heading (dx, dy)
    - formation_efficiency: Current edge-based formation efficiency (0.0-1.0)
    """
    def __init__(self, ttl: int, seq_num: int, sender_id: bytes,
                 platoon_id: bytes = b"",
                 head_id: bytes = b"",
                 position: bytes = b"",
                 destination: bytes = b"",
                 available_slots: bytes = b"",
                 surplus_energy: bytes = b"",
                 direction_vector: bytes = b"",
                 formation_efficiency: bytes = b""):
        super().__init__(MessageType.PLATOON_ANNOUNCE, ttl, seq_num, sender_id)
        if platoon_id:
            self.add_tlv(TLV(TLVType.PLATOON_ID, platoon_id))
        if head_id:
            self.add_tlv(TLV(TLVType.HEAD_ID, head_id))
        if position:
            self.add_tlv(TLV(TLVType.POSITION, position))
        if destination:
            self.add_tlv(TLV(TLVType.DESTINATION, destination))
        if available_slots:
            self.add_tlv(TLV(TLVType.AVAILABLE_SLOTS, available_slots))
        if surplus_energy:
            self.add_tlv(TLV(TLVType.SURPLUS_ENERGY, surplus_energy))
        if direction_vector:
            self.add_tlv(TLV(TLVType.DIRECTION_VECTOR, direction_vector))
        if formation_efficiency:
            self.add_tlv(TLV(TLVType.FORMATION_EFFICIENCY, formation_efficiency))


# Mapping for decoding
_MESSAGE_TYPE_MAP = {
    MessageType.HELLO: HelloMessage,
    MessageType.PA: PAMessage,
    MessageType.JOIN_OFFER: JoinOfferMessage,
    MessageType.JOIN_ACCEPT: JoinAcceptMessage,
    MessageType.ACK: AckMessage,
    MessageType.ACKACK: AckAckMessage,
    MessageType.PLATOON_BEACON: PlatoonBeaconMessage,
    MessageType.PLATOON_STATUS: PlatoonStatusMessage,
    MessageType.GRID_STATUS: GridStatusMessage,
    MessageType.PLATOON_ANNOUNCE: PlatoonAnnounceMessage,
}


