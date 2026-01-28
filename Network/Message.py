import json


class Message:
    """
    Messages Exchanged in our protocol 
    Messages without a dst are broadcast messages 
    """

    def __init__(self, msg_type, src, dst=None, **kwargs):
        self.msg_type = msg_type
        self.src = src
        self.dst = dst
        self.payload = kwargs

    def to_bytes(self) -> bytes:
        """Serialize message to bytes for network transmission."""
        return json.dumps({
            "type": self.msg_type,
            "src": self.src,
            "dst": self.dst,
            **self.payload
        }).encode('utf-8')

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Message':
        """Deserialize message from received bytes."""
        d = json.loads(data.decode('utf-8'))
        msg_type = d.pop("type")
        src = d.pop("src")
        dst = d.pop("dst", None)
        return cls(msg_type, src, dst, **d)

    def __repr__(self):
        return f"Message({self.msg_type}, src={self.src}, dst={self.dst}, payload={self.payload})"

    @staticmethod
    def HELLO(src, dst=None, info=None, distance=None):
        return Message("HELLO", src, dst, info=info, distance=distance)

    @staticmethod
    def PA(src, dst=None, can_share=True):
        return Message("PA", src, dst, can_share=can_share)

    @staticmethod
    def JoinOffer(src, dst, energy_available, energy_demand):
        return Message("JOIN_OFFER", src, dst, energy_available=energy_available, energy_demand=energy_demand)

    @staticmethod
    def JoinAccept(src, dst, platoon_id):
        return Message("JOIN_ACCEPT", src, dst, platoon_id=platoon_id)

    @staticmethod
    def REGISTER(src, platoon_id):
        return Message("REGISTER", src, dst=None, platoon_id=platoon_id)

    @staticmethod
    def VERIFY(src, target):
        return Message("VERIFY", src, dst=None, target=target)

    @staticmethod
    def ACK(src):
        return Message("ACK", src, dst=None)

    @staticmethod
    def NACK(src):
        return Message("NACK", src, dst=None)

    def ACKACK(src):
        return Message("ACKACK", src, dst=None)

    @staticmethod
    def PlatoonBeacon(src, platoon_id, info=None):
        return Message("PLATOON_BEACON", src, dst=None, platoon_id=platoon_id, info=info)

    @staticmethod
    def PlatoonStatus(src, platoon_id, status=None):
        return Message("PLATOON_STATUS", src, dst=None, platoon_id=platoon_id, status=status)

    @staticmethod
    def FIN(src, dst=None):
        return Message("FIN", src, dst)

    @staticmethod
    def AIM(src, dst, infra_info):
        return Message("AIM", src, dst, infra_info=infra_info)
