class Message:
    """
    Messages Exchanged in our protocol 
    Messages without a dst are broadcast messages 
    """

    def __init__(self, src):
        self.src = src

    def HELLO(src, dst=None, info=None, distance=None):
        return Message("HELLO", src, dst, info=info, distance=distance)

    def PA(src, dst=None, can_share=True):
        return Message("PA", src, dst, can_share=can_share)
    
    def JoinOffer(src, dst, energy_available, energy_demand):
        return Message("JOIN_OFFER", src, dst, energy_available=energy_available, energy_demand=energy_demand)
    
    def JoinAccept(src, dst, platoon_id):
        return Message("JOIN_ACCEPT", src, dst, platoon_id=platoon_id)
    
    def REGISTER(src, platoon_id):
        return Message("REGISTER", src, dst=None, platoon_id=platoon_id)
    
    def VERIFY(src, target):
        return Message("VERIFY", src, dst=None, target=target)
    
    def ACK(src):
        return Message("ACK", src, dst=None)
    
    def NACK(src):
        return Message("NACK", src, dst=None)
    
    def PlatoonBeacon(src, platoon_id, info=None):
        return Message("PLATOON_BEACON", src, dst=None, platoon_id=platoon_id, info=info)
    
    def PlatoonStatus(src, platoon_id, status=None):
        return Message("PLATOON_STATUS", src, dst=None, platoon_id=platoon_id, status=status)
    
    def FIN(src, dst=None):
        return Message("FIN", src, dst)
    
    def AIM(src, dst, infra_info):
        return Message("AIM", src, dst, infra_info=infra_info)
