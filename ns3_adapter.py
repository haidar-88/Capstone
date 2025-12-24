try:
    import ns.applications
    import ns.core
    import ns.network
    import ns.wifi
except ImportError:
    # This file is meant to be run within an ns-3 python environment
    pass

from Protocol.context import MVCCPContext
from Protocol.LayerA_NeighborDiscovery.handler import NeighborDiscoveryHandler
from Protocol.LayerB_ProviderAnnouncement.handler import ProviderAnnouncementHandler
from Protocol.LayerC_ChargingCoordination.handler import ChargingCoordinationHandler
from Protocol.LayerD_PlatoonCoordination.handler import PlatoonCoordinationHandler
from messages import MVCCPMessage

class MVCCPApplication(ns.applications.Application):
    """
    Adapter class to run MVCCP Protocol within ns-3 Simulation.
    """
    def __init__(self, node_id_bytes, phy_node):
        super().__init__()
        self.node_id = node_id_bytes
        self.phy_node = phy_node # ns3.Node object
        
        # Setup Python Context
        # We need a mock "Node" object that the Context expects
        # or we update Context to work with this.
        # For now, let's create a proxy object.
        class NodeProxy:
            def __init__(self, nid, ns3_node):
                self.node_id = nid
                self.ns3_node = ns3_node
            
            @property
            def velocity(self):
                # Extract velocity from ns-3 MobilityModel
                mob = self.ns3_node.GetObject(ns.mobility.MobilityModel.GetTypeId())
                if mob:
                    v = mob.GetVelocity()
                    return (v.x, v.y)
                return (0.0, 0.0)

        self.proxy_node = NodeProxy(node_id_bytes, phy_node)
        self.context = MVCCPContext(self.proxy_node)
        
        # Link Send Callback
        self.context.send_callback = self.send_packet
        
        # Initialize Handlers
        self.l1 = NeighborDiscoveryHandler(self.context)
        self.l2 = ProviderAnnouncementHandler(self.context)
        self.l3 = ChargingCoordinationHandler(self.context)
        self.l4 = PlatoonCoordinationHandler(self.context)
        
        self.running = False
        self.socket = None

    def StartApplication(self):
        self.running = True
        
        # Create Socket for Broadcast
        tid = ns.core.TypeId.LookupByName("ns3::PacketSocketFactory")
        self.socket = ns.network.Socket.CreateSocket(self.GetNode(), tid)
        
        # Bind
        local = ns.network.PacketSocketAddress()
        local.SetAllDevices()
        local.SetProtocol(0)
        self.socket.Bind(local)
        
        # Set Broadcast Destination
        dest = ns.network.PacketSocketAddress()
        dest.SetAllDevices()
        dest.SetPhysicalAddress(ns.network.Mac8_Address.GetBroadcast())
        dest.SetProtocol(0)
        self.socket.Connect(dest)
        
        # Register Receive Callback
        self.socket.SetRecvCallback(self.ReceivePacket)
        
        # Schedule pure-python periodic tasks if needed
        # (e.g. call L1/L2 tick methods using Simulator::Schedule)

    def StopApplication(self):
        self.running = False
        if self.socket:
            self.socket.Close()

    def ReceivePacket(self, socket):
        packet = socket.Recv()
        # Extract bytes
        buf = bytearray(packet.GetSize())
        im = ns.core.Packet.InputStream(packet)
        im.Read(buf, packet.GetSize())
        data = bytes(buf)
        
        try:
            msg = MVCCPMessage.decode(data)
            self.dispatch_message(msg)
        except Exception as e:
            print(f"Error decoding packet on Node {self.node_id}: {e}")

    def dispatch_message(self, msg):
        # Route to handlers based on Type
        # L1
        if msg.header.msg_type == 1: # HELLO
            self.l1.handle_hello(msg)
        # L2 
        elif msg.header.msg_type == 2: # PA
            self.l2.handle_pa(msg)
        # L3
        elif msg.header.msg_type in [3, 4, 5, 6]:
            if msg.header.msg_type == 3: self.l3.handle_join_offer(msg)
            elif msg.header.msg_type == 4: self.l3.handle_join_accept(msg)
            elif msg.header.msg_type == 5: self.l3.handle_ack(msg)
            elif msg.header.msg_type == 6: self.l3.handle_ackack(msg)
        # L4
        elif msg.header.msg_type in [7, 8]:
            if msg.header.msg_type == 7: self.l4.handle_beacon(msg)
            elif msg.header.msg_type == 8: self.l4.handle_status(msg)

    def send_packet(self, data: bytes):
        if not self.running or not self.socket:
            return
            
        packet = ns.core.Packet(data)
        self.socket.Send(packet)
