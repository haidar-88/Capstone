import unittest
import struct
from messages import (
    MessageType, TLVType, MessageHeader, TLV, MVCCPMessage,
    HelloMessage, PAMessage, JoinOfferMessage, JoinAcceptMessage, AckMessage, AckAckMessage,
    PlatoonBeaconMessage, PlatoonStatusMessage, GridStatusMessage
)

class TestMessages(unittest.TestCase):

    def test_header_packing(self):
        # Format: !HBI6sH
        # msg_type=1, ttl=4, seq_num=100, sender_id=b'ABCDEF', payload_len=0
        header = MessageHeader(1, 4, 100, b'ABCDEF', 0)
        packed = header.pack()
        expected = struct.pack("!HBI6sH", 1, 4, 100, b'ABCDEF', 0)
        self.assertEqual(packed, expected)
        self.assertEqual(len(packed), 13 + 2) # Wait, struct alignment?
        # !H(2) B(1) I(4) 6s(6) H(2) = 15 bytes exactly. No padding in standard size usually with !
        self.assertEqual(MessageHeader.SIZE, 15)
        self.assertEqual(len(packed), 15)

    def test_tlv_packing(self):
        tlv = TLV(TLVType.NODE_ID, b'123')
        packed = tlv.pack()
        # Type(1) + Len(1) + Val(3) = 5 bytes
        self.assertEqual(packed, b'\x01\x03123')

    def test_hello_message_encoding(self):
        sender_id = b'\x00\x00\x00\x00\x00\x01'
        msg = HelloMessage(ttl=4, seq_num=1, sender_id=sender_id, neighbor_list=b'\x02\x02', metrics=b'\x00', provider_flag=b'\x01')
        encoded = msg.encode()
        
        # Decode
        decoded = MVCCPMessage.decode(encoded)
        self.assertIsInstance(decoded, HelloMessage)
        self.assertEqual(decoded.header.msg_type, MessageType.HELLO)
        self.assertEqual(decoded.header.ttl, 4)
        self.assertEqual(decoded.header.sender_id, sender_id)
        
        # Check TLVs
        self.assertEqual(len(decoded.tlvs), 3)
        self.assertEqual(decoded.get_tlv_value(TLVType.NEIGHBOR_LIST), b'\x02\x02')
        self.assertEqual(decoded.get_tlv_value(TLVType.METRICS), b'\x00')
        self.assertEqual(decoded.get_tlv_value(TLVType.PROVIDER_FLAG), b'\x01')

    def test_pa_message_roundtrip(self):
        sender = b'SERVER'
        msg = PAMessage(ttl=3, seq_num=50, sender_id=sender, 
                        provider_id=b'PROV01', 
                        provider_type=b'\x00', 
                        position=b'latlong',
                        destination=b'dest',
                        platoon_size=b'\x05',
                        energy_available=b'\xFF\xFF')
        encoded = msg.encode()
        
        decoded = MVCCPMessage.decode(encoded)
        self.assertIsInstance(decoded, PAMessage)
        self.assertEqual(decoded.get_tlv_value(TLVType.PROVIDER_ID), b'PROV01')
        self.assertEqual(decoded.get_tlv_value(TLVType.PROVIDER_TYPE), b'\x00')
        self.assertEqual(decoded.get_tlv_value(TLVType.POSITION), b'latlong')
        self.assertEqual(decoded.get_tlv_value(TLVType.DESTINATION), b'dest')
        self.assertEqual(decoded.get_tlv_value(TLVType.PLATOON_SIZE), b'\x05')
        self.assertEqual(decoded.get_tlv_value(TLVType.ENERGY_AVAILABLE), b'\xFF\xFF')

    def test_platoon_beacon_roundtrip(self):
        msg = PlatoonBeaconMessage(ttl=4, seq_num=60, sender_id=b'HEAD01', 
                                   platoon_id=b'LAT001', 
                                   timestamp=b'123456',
                                   velocity=b'10.5',
                                   available_slots=b'\x02',
                                   topology=b'topo',
                                   route=b'route')
        encoded = msg.encode()
        decoded = MVCCPMessage.decode(encoded)
        self.assertIsInstance(decoded, PlatoonBeaconMessage)
        self.assertEqual(decoded.get_tlv_value(TLVType.PROVIDER_ID), b'LAT001')
        self.assertEqual(decoded.get_tlv_value(TLVType.TIMESTAMP), b'123456')
        self.assertEqual(decoded.get_tlv_value(TLVType.VELOCITY), b'10.5')
        self.assertEqual(decoded.get_tlv_value(TLVType.AVAILABLE_SLOTS), b'\x02')
        self.assertEqual(decoded.get_tlv_value(TLVType.TOPOLOGY), b'topo')
        self.assertEqual(decoded.get_tlv_value(TLVType.ROUTE), b'route')

    def test_platoon_status_roundtrip(self):
        msg = PlatoonStatusMessage(ttl=1, seq_num=70, sender_id=b'CAR002', 
                                   platoon_id=b'P1',
                                   vehicle_id=b'CAR002', 
                                   battery=b'\x50',
                                   relative_index=b'\x01',
                                   receive_rate=b'good')
        encoded = msg.encode()
        decoded = MVCCPMessage.decode(encoded)
        self.assertIsInstance(decoded, PlatoonStatusMessage)
        self.assertEqual(decoded.get_tlv_value(TLVType.PROVIDER_ID), b'P1')
        self.assertEqual(decoded.get_tlv_value(TLVType.NODE_ID), b'CAR002')
        self.assertEqual(decoded.get_tlv_value(TLVType.BATTERY_LEVEL), b'\x50')
        self.assertEqual(decoded.get_tlv_value(TLVType.RELATIVE_INDEX), b'\x01')
        self.assertEqual(decoded.get_tlv_value(TLVType.RECEIVE_RATE), b'good')

    def test_grid_status_roundtrip(self):
        msg = GridStatusMessage(ttl=5, seq_num=80, sender_id=b'GRID01', 
                                hub_id=b'HUB123', 
                                renewable_fraction=b'\x64',
                                available_power=b'\xFF',
                                max_sessions=b'\x0A',
                                queue_time=b'\x00',
                                operational_state=b'OK')
        encoded = msg.encode()
        decoded = MVCCPMessage.decode(encoded)
        self.assertIsInstance(decoded, GridStatusMessage)
        self.assertEqual(decoded.get_tlv_value(TLVType.HUB_ID), b'HUB123')
        self.assertEqual(decoded.get_tlv_value(TLVType.RENEWABLE_FRACTION), b'\x64')
        self.assertEqual(decoded.get_tlv_value(TLVType.AVAILABLE_POWER), b'\xFF')
        self.assertEqual(decoded.get_tlv_value(TLVType.MAX_SESSIONS), b'\x0A')
        self.assertEqual(decoded.get_tlv_value(TLVType.QUEUE_TIME), b'\x00')
        self.assertEqual(decoded.get_tlv_value(TLVType.OPERATIONAL_STATE), b'OK')

    def test_invalid_decode(self):
        with self.assertRaises(ValueError):
            MVCCPMessage.decode(b'\x00') # Too short

if __name__ == '__main__':
    unittest.main()
