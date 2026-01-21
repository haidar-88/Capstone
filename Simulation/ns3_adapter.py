"""
ns-3 Adapter for MVCCP Protocol.

This module provides integration between the MVCCP Python protocol implementation
and the ns-3 network simulator.
"""

# ns-3 global reference (set during import)
ns3 = None

try:
    # ns-3 with cppyy bindings uses 'from ns import ns' pattern
    from ns import ns as ns3
except ImportError:
    # This file is meant to be run within an ns-3 python environment
    pass

from src.protocol.context import MVCCPContext
from src.protocol.layer_a.handler import NeighborDiscoveryHandler
from src.protocol.layer_b.handler import ProviderAnnouncementHandler
from src.protocol.layer_c import (
    ConsumerHandler, PlatoonHeadHandler, RREHHandler, RoleManager
)
from src.protocol.layer_d.handler import PlatoonCoordinationHandler
from src.messages.messages import MVCCPMessage, MessageType
from src.protocol.config import ProtocolConfig


class NodeProxy:
    """
    Proxy object to adapt ns-3 Node to MVCCP Node expectations.
    Provides the minimal interface needed by MVCCPContext.
    """
    
    def __init__(self, nid, ns3_node):
        self.node_id = nid
        self.ns3_node = ns3_node
        
        # Battery attributes (defaults - should be set by simulation)
        self.battery_capacity_kwh = 100.0
        self.battery_energy_kwh = 50.0
        self.min_energy_kwh = 10.0
        self.max_transfer_rate_in = 50.0
        self.max_transfer_rate_out = 50.0
        self.battery_health = 1.0
        
        # Position (updated from ns-3 mobility model)
        self.latitude = 0.0
        self.longitude = 0.0
        
        # Destination for route calculations
        self.destination = None
        
        # QoS metrics
        self.etx = 1.0
        self.delay = 0.0
        self.willingness = 3
        self.lane_weight = 0.5
        self.link_stability = 1.0
        
        # Platoon
        self.platoon = None
        self.is_leader = False
        self.connections_list = {}
        self.two_hop_neighbors = set()
        self.link_status = "SYM"
        
        # Network
        self.ip_address = "0.0.0.0"
        self.last_seen = 0.0
        
        # Velocity (can be set from SUMO or read from ns-3 mobility model)
        self._velocity = (0.0, 0.0)
    
    @property
    def velocity(self):
        """Extract velocity from ns-3 MobilityModel, or return stored value."""
        try:
            if self.ns3_node is not None:
                mob = self.ns3_node.GetObject(ns3.MobilityModel.GetTypeId())
                if mob:
                    v = mob.GetVelocity()
                    return (v.x, v.y)
        except Exception:
            pass
        # Fall back to stored velocity (e.g., from SUMO)
        return self._velocity
    
    @velocity.setter
    def velocity(self, value):
        """Set velocity (typically from SUMO mobility data)."""
        self._velocity = value
    
    def update_position_from_ns3(self):
        """Update position from ns-3 mobility model."""
        try:
            mob = self.ns3_node.GetObject(ns3.MobilityModel.GetTypeId())
            if mob:
                pos = mob.GetPosition()
                self.latitude = pos.y
                self.longitude = pos.x
        except Exception:
            pass
    
    def position(self):
        """Get current position as (lat, lon) tuple."""
        return (self.latitude, self.longitude)
    
    def distance_to(self, target_position):
        """Calculate distance to target in km (Euclidean approximation)."""
        if target_position is None:
            return 0.0
        import math
        lat1, lon1 = self.position()
        lat2, lon2 = target_position
        lat_diff = (lat2 - lat1) * ProtocolConfig.KM_PER_DEGREE
        lon_diff = (lon2 - lon1) * ProtocolConfig.KM_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
        return math.sqrt(lat_diff ** 2 + lon_diff ** 2)
    
    def energy_to(self, target_position):
        """Calculate energy to reach target position."""
        distance_km = self.distance_to(target_position)
        return distance_km * 0.15  # 0.15 kWh/km
    
    def energy_to_destination(self):
        """Calculate energy to reach destination."""
        if self.destination is None:
            return 0.0
        return self.energy_to(self.destination)
    
    def shareable_energy(self):
        """Calculate shareable energy."""
        return self.battery_energy_kwh - self.energy_to_destination() - self.min_energy_kwh
    
    def direction_vector(self):
        """Calculate direction vector to destination."""
        if self.destination is None:
            return (0.0, 0.0)
        import math
        lat1, lon1 = self.position()
        lat2, lon2 = self.destination
        dx = (lon2 - lon1) * ProtocolConfig.KM_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
        dy = (lat2 - lat1) * ProtocolConfig.KM_PER_DEGREE
        mag = math.sqrt(dx ** 2 + dy ** 2)
        if mag < ProtocolConfig.FLOAT_EPSILON:
            return (0.0, 0.0)
        return (dx / mag, dy / mag)
    
    def available_energy(self):
        """Get available battery energy."""
        return self.battery_energy_kwh


class MVCCPApplication(ns3.Application):
    """
    Adapter class to run MVCCP Protocol within ns-3 Simulation.
    """
    
    def __init__(self, node_id_bytes, phy_node, is_rreh: bool = False):
        """
        Initialize MVCCP application.
        
        Args:
            node_id_bytes: Unique node identifier (6 bytes)
            phy_node: ns-3 Node object
            is_rreh: True if this node is an RREH
        """
        super().__init__()
        self.node_id = node_id_bytes
        self.phy_node = phy_node
        self.is_rreh = is_rreh
        
        # Create proxy node with required attributes
        self.proxy_node = NodeProxy(node_id_bytes, phy_node)
        
        # Create protocol context
        self.context = MVCCPContext(self.proxy_node, is_rreh=is_rreh)
        
        # Link Send Callback
        self.context.send_callback = self.send_packet
        
        # Initialize Layer 1 & 2 Handlers
        self.l1 = NeighborDiscoveryHandler(self.context)
        self.l2 = ProviderAnnouncementHandler(self.context)
        
        # Initialize Layer 3 Handlers based on role
        self.role_manager = RoleManager(self.context)
        self.consumer_handler = ConsumerHandler(self.context)
        
        if is_rreh:
            self.rreh_handler = RREHHandler(self.context)
            self.ph_handler = None
        else:
            self.rreh_handler = None
            self.ph_handler = PlatoonHeadHandler(self.context)
        
        # Initialize Layer 4 Handler
        self.l4 = PlatoonCoordinationHandler(self.context)
        
        self.running = False
        self.socket = None

    def StartApplication(self):
        """Start the MVCCP application."""
        self.running = True
        
        # Create Socket for Broadcast
        tid = ns3.TypeId.LookupByName("ns3::PacketSocketFactory")
        self.socket = ns3.Socket.CreateSocket(self.GetNode(), tid)
        
        # Bind
        local = ns3.PacketSocketAddress()
        local.SetAllDevices()
        local.SetProtocol(0)
        self.socket.Bind(local)
        
        # Set Broadcast Destination
        dest = ns3.PacketSocketAddress()
        dest.SetAllDevices()
        dest.SetPhysicalAddress(ns3.Mac48Address.GetBroadcast())
        dest.SetProtocol(0)
        self.socket.Connect(dest)
        
        # Register Receive Callback
        self.socket.SetRecvCallback(self.ReceivePacket)

    def StopApplication(self):
        """Stop the MVCCP application."""
        self.running = False
        if self.socket:
            self.socket.Close()

    def tick(self, timestamp: float):
        """
        Process a protocol tick. Call this periodically from ns-3 scheduler.

        Policy B Timing Model:
            Both tick() and ReceivePacket() update context.current_time to ensure
            handlers always see accurate simulation time. This means:
            - ReceivePacket: Updates time immediately when packet arrives
            - tick(): Updates time at start of periodic processing

            Both paths are role-safe (use RWLock on shared tables) and both
            update time, making packet reception authoritative while tick()
            handles periodic housekeeping (timeouts, beacons, state transitions).

        Args:
            timestamp: Current simulation time in seconds
        """
        # Update context time (Policy B: both receive and tick update time)
        self.context.update_time(timestamp)
        
        # Update position from ns-3
        self.proxy_node.update_position_from_ns3()
        
        # Evaluate role changes (for non-RREH nodes)
        if not self.is_rreh:
            self.role_manager.tick(timestamp)
        
        # Tick appropriate Layer 3 handler
        if self.context.is_consumer():
            self.consumer_handler.tick(timestamp)
        elif self.context.is_platoon_head() and self.ph_handler:
            self.ph_handler.tick(timestamp)
        elif self.context.is_rreh() and self.rreh_handler:
            self.rreh_handler.tick(timestamp)
        
        # Tick Layer 4
        self.l4.tick(timestamp)

    def ReceivePacket(self, socket):
        """
        Handle received packet from ns-3.

        Policy B: ReceivePacket is authoritative - we update simulation time
        immediately when a packet arrives, ensuring handlers see accurate time.
        """
        # Get current simulation time from ns-3 (Policy B: update time on receive)
        timestamp = ns3.Simulator.Now().GetSeconds()
        self.context.update_time(timestamp)

        packet = socket.Recv()
        # Extract bytes from packet
        size = packet.GetSize()
        buf = bytearray(size)
        packet.CopyData(buf, size)
        data = bytes(buf)

        try:
            msg = MVCCPMessage.decode(data)
            self.dispatch_message(msg, timestamp)
        except Exception as e:
            print(f"Error decoding packet on Node {self.node_id}: {e}")

    def dispatch_message(self, msg, timestamp: float = None):
        """
        Route message to appropriate handler based on type.

        Args:
            msg: Decoded MVCCPMessage
            timestamp: Simulation time when packet was received (for logging/debugging)

        Note: Handlers use context.current_time which is already updated before
        this method is called (Policy B compliance).
        """
        msg_type = msg.header.msg_type
        
        # Layer 1: HELLO
        if msg_type == MessageType.HELLO:
            self.l1.handle_hello(msg)
        
        # Layer 2: PA and GRID_STATUS
        elif msg_type == MessageType.PA:
            self.l2.handle_pa(msg)
        elif msg_type == MessageType.GRID_STATUS:
            self.l2.handle_grid_status(msg)
        
        # Layer 3: JOIN_OFFER, JOIN_ACCEPT, ACK, ACKACK
        elif msg_type == MessageType.JOIN_OFFER:
            if self.context.is_platoon_head() and self.ph_handler:
                self.ph_handler.handle_join_offer(msg)
            elif self.context.is_rreh() and self.rreh_handler:
                self.rreh_handler.handle_join_offer(msg)
        
        elif msg_type == MessageType.JOIN_ACCEPT:
            if self.context.is_consumer():
                self.consumer_handler.handle_join_accept(msg)
        
        elif msg_type == MessageType.ACK:
            if self.context.is_platoon_head() and self.ph_handler:
                self.ph_handler.handle_ack(msg)
            elif self.context.is_rreh() and self.rreh_handler:
                self.rreh_handler.handle_ack(msg)
        
        elif msg_type == MessageType.ACKACK:
            if self.context.is_consumer():
                self.consumer_handler.handle_ackack(msg)
        
        # Layer 4: PLATOON_BEACON, PLATOON_STATUS
        elif msg_type == MessageType.PLATOON_BEACON:
            self.l4.handle_beacon(msg)
            # Also forward to PH handler for member tracking
            if self.context.is_platoon_head() and self.ph_handler:
                pass  # Beacon is outbound from PH, not inbound
        
        elif msg_type == MessageType.PLATOON_STATUS:
            self.l4.handle_status(msg)
            if self.context.is_platoon_head() and self.ph_handler:
                self.ph_handler.handle_platoon_status(msg)

    def send_packet(self, data: bytes):
        """Send packet via ns-3 socket."""
        if not self.running or not self.socket:
            return
        packet = ns3.Packet(data)
        self.socket.Send(packet)
    
    def set_destination(self, lat: float, lon: float):
        """Set the node's destination."""
        self.proxy_node.destination = (lat, lon)
        self.context.set_destination((lat, lon))
    
    def set_battery(self, energy_kwh: float):
        """Set current battery energy."""
        self.proxy_node.battery_energy_kwh = energy_kwh
    
    def set_willingness(self, willingness: int):
        """Set MPR willingness (0-7)."""
        self.proxy_node.willingness = willingness


def setup_wave_channel(nodes):
    """
    Configure 802.11p WAVE for VANET communication.

    Sets up the PHY and MAC layers for vehicular ad-hoc networking using
    the 802.11p (WAVE) standard at 5.9 GHz.

    Args:
        nodes: ns-3 NodeContainer with nodes to configure

    Returns:
        NetDeviceContainer with configured WAVE devices
    """
    # Configure 802.11p standard
    wifi = ns3.WifiHelper.Default()
    wifi.SetStandard(ns3.WIFI_STANDARD_80211p)

    # Set up PHY layer
    wifiPhy = ns3.YansWifiPhyHelper.Default()

    # Configure channel (5.9 GHz band for WAVE)
    wifiChannel = ns3.YansWifiChannelHelper.Default()
    wifiChannel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel")
    wifiChannel.AddPropagationLoss(
        "ns3::FriisPropagationLossModel",
        "Frequency", ns3.DoubleValue(5.9e9)
    )
    wifiPhy.SetChannel(wifiChannel.Create())

    # Set transmission power for VANET range (~300m)
    wifiPhy.Set("TxPowerStart", ns3.DoubleValue(20.0))
    wifiPhy.Set("TxPowerEnd", ns3.DoubleValue(20.0))

    # Configure MAC layer (ad-hoc mode for V2V)
    wifiMac = ns3.WifiMacHelper()
    wifiMac.SetType("ns3::AdhocWifiMac")

    # Install on nodes
    return wifi.Install(wifiPhy, wifiMac, nodes)


def create_mvccp_nodes(num_nodes: int, is_rreh_list: list = None):
    """
    Create ns-3 nodes with MVCCP applications installed.

    Args:
        num_nodes: Number of nodes to create
        is_rreh_list: Optional list indicating which nodes are RREHs

    Returns:
        Tuple of (NodeContainer, list of MVCCPApplication)
    """
    if is_rreh_list is None:
        is_rreh_list = [False] * num_nodes

    # Create nodes
    nodes = ns3.NodeContainer()
    nodes.Create(num_nodes)

    # Set up WAVE networking
    devices = setup_wave_channel(nodes)

    # Create MVCCP applications
    apps = []
    for i in range(num_nodes):
        node_id = i.to_bytes(6, 'big')
        app = MVCCPApplication(node_id, nodes.Get(i), is_rreh=is_rreh_list[i])
        nodes.Get(i).AddApplication(app)
        apps.append(app)

    return nodes, apps


def schedule_mvccp_ticks(apps, interval: float = 0.1, duration: float = 100.0):
    """
    Schedule periodic MVCCP tick events for all applications.

    Args:
        apps: List of MVCCPApplication instances
        interval: Tick interval in seconds (default 100ms)
        duration: Total simulation duration in seconds
    """
    def tick_all():
        timestamp = ns3.Simulator.Now().GetSeconds()
        for app in apps:
            if app.running:
                app.tick(timestamp)

    # Schedule ticks throughout simulation
    current = 0.0
    while current < duration:
        ns3.Simulator.Schedule(
            ns3.Seconds(current),
            tick_all
        )
        current += interval
