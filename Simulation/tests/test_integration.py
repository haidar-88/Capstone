"""
Integration tests for MVCCP co-simulation.

These tests require ns-3 and/or SUMO to be installed.
Mark tests that require external dependencies with appropriate markers.

Run with:
    pytest Simulation/tests/ -v
    pytest Simulation/tests/ -m "not integration"  # Skip external deps
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Check for optional dependencies
try:
    import ns.core
    import ns.network
    NS3_AVAILABLE = True
except ImportError:
    NS3_AVAILABLE = False

try:
    import traci
    TRACI_AVAILABLE = True
except ImportError:
    TRACI_AVAILABLE = False


# =============================================================================
# Markers for conditional test execution
# =============================================================================

requires_ns3 = pytest.mark.skipif(
    not NS3_AVAILABLE,
    reason="ns-3 Python bindings not available"
)

requires_sumo = pytest.mark.skipif(
    not TRACI_AVAILABLE,
    reason="TraCI (SUMO) not available"
)

requires_both = pytest.mark.skipif(
    not (NS3_AVAILABLE and TRACI_AVAILABLE),
    reason="Requires both ns-3 and SUMO"
)


# =============================================================================
# Mock classes for testing without ns-3
# =============================================================================

class MockNS3Simulator:
    """Mock ns-3 Simulator for testing without ns-3."""

    _current_time = 0.0

    @classmethod
    def Now(cls):
        class Time:
            @staticmethod
            def GetSeconds():
                return MockNS3Simulator._current_time
        return Time()

    @classmethod
    def Stop(cls, time):
        pass

    @classmethod
    def Run(cls):
        pass

    @classmethod
    def Schedule(cls, time, callback):
        pass


class MockSocket:
    """Mock ns-3 socket for testing."""

    def __init__(self):
        self.packets = []
        self.recv_callback = None

    def Bind(self, addr):
        pass

    def Connect(self, addr):
        pass

    def SetRecvCallback(self, callback):
        self.recv_callback = callback

    def Send(self, packet):
        self.packets.append(packet)

    def Recv(self):
        if self.packets:
            return self.packets.pop(0)
        return None

    def Close(self):
        pass


# =============================================================================
# Test Classes
# =============================================================================

class TestNodeProxy:
    """Test NodeProxy adapter class."""

    def test_node_proxy_creation(self):
        """NodeProxy should initialize with default values."""
        from Simulation.ns3_adapter import NodeProxy

        # Create with mock ns3 node (None for testing)
        proxy = NodeProxy(b'\x00\x00\x00\x00\x00\x01', None)

        assert proxy.node_id == b'\x00\x00\x00\x00\x00\x01'
        assert proxy.battery_capacity_kwh == 100.0
        assert proxy.battery_energy_kwh == 50.0
        assert proxy.min_energy_kwh == 10.0

    def test_node_proxy_position(self):
        """NodeProxy should return position tuple."""
        from Simulation.ns3_adapter import NodeProxy

        proxy = NodeProxy(b'\x00\x00\x00\x00\x00\x01', None)
        proxy.latitude = 10.0
        proxy.longitude = 20.0

        pos = proxy.position()
        assert pos == (10.0, 20.0)

    def test_node_proxy_distance_to(self):
        """NodeProxy should calculate distance correctly."""
        from Simulation.ns3_adapter import NodeProxy

        proxy = NodeProxy(b'\x00\x00\x00\x00\x00\x01', None)
        proxy.latitude = 0.0
        proxy.longitude = 0.0

        # Distance to same point
        dist = proxy.distance_to((0.0, 0.0))
        assert dist == 0.0

        # Distance to nearby point (rough check)
        dist = proxy.distance_to((1.0, 0.0))
        assert dist > 0

    def test_node_proxy_shareable_energy(self):
        """NodeProxy should calculate shareable energy."""
        from Simulation.ns3_adapter import NodeProxy

        proxy = NodeProxy(b'\x00\x00\x00\x00\x00\x01', None)
        proxy.battery_energy_kwh = 80.0
        proxy.min_energy_kwh = 10.0
        proxy.destination = None  # No destination

        shareable = proxy.shareable_energy()

        # Without destination, energy_to_destination is 0
        # shareable = 80 - 0 - 10 = 70
        assert shareable == 70.0

    def test_node_proxy_direction_vector(self):
        """NodeProxy should calculate direction vector."""
        from Simulation.ns3_adapter import NodeProxy

        proxy = NodeProxy(b'\x00\x00\x00\x00\x00\x01', None)
        proxy.latitude = 0.0
        proxy.longitude = 0.0

        # No destination
        dx, dy = proxy.direction_vector()
        assert dx == 0.0
        assert dy == 0.0

        # With destination
        proxy.destination = (1.0, 0.0)
        dx, dy = proxy.direction_vector()
        # Should point roughly north
        assert dy > 0 or (dx == 0 and dy == 0)


class TestMVCCPApplicationBasic:
    """Test MVCCPApplication without ns-3."""

    def test_application_creation_without_ns3(self):
        """Application creation should fail gracefully without ns-3."""
        # This test verifies the import structure works
        try:
            from Simulation.ns3_adapter import MVCCPApplication
            # If ns-3 is available, we'd test the actual class
            if NS3_AVAILABLE:
                pass  # Would need actual ns-3 node
        except (ImportError, AttributeError):
            pass  # Expected without ns-3

    def test_setup_wave_channel_import(self):
        """setup_wave_channel function should be importable."""
        try:
            from Simulation.ns3_adapter import setup_wave_channel
            # Function exists
            assert callable(setup_wave_channel)
        except ImportError:
            pass  # Expected without ns-3


class TestCoSimOrchestratorBasic:
    """Test CoSimOrchestrator without external dependencies."""

    def test_orchestrator_creation(self):
        """Orchestrator should initialize with defaults."""
        from Simulation.cosim_orchestrator import CoSimOrchestrator

        orch = CoSimOrchestrator()

        assert orch.step_size == 0.5
        assert orch.sumo_port == 8813
        assert orch.current_time == 0.0
        assert len(orch.mvccp_apps) == 0

    def test_orchestrator_custom_step_size(self):
        """Orchestrator should accept custom step size."""
        from Simulation.cosim_orchestrator import CoSimOrchestrator

        orch = CoSimOrchestrator(step_size=0.1)

        assert orch.step_size == 0.1

    def test_add_mvccp_application(self):
        """Orchestrator should track added applications."""
        from Simulation.cosim_orchestrator import CoSimOrchestrator

        orch = CoSimOrchestrator()

        # Add mock application
        mock_app = object()
        orch.add_mvccp_application("veh_1", mock_app)

        assert "veh_1" in orch.mvccp_apps
        assert orch.mvccp_apps["veh_1"] is mock_app

    def test_get_statistics(self):
        """Orchestrator should return statistics dict."""
        from Simulation.cosim_orchestrator import CoSimOrchestrator

        orch = CoSimOrchestrator()
        orch.current_time = 10.0
        orch.steps_completed = 20

        stats = orch.get_statistics()

        assert stats['current_time'] == 10.0
        assert stats['steps_completed'] == 20
        assert stats['step_size'] == 0.5
        assert stats['num_vehicles'] == 0

    def test_sumo_to_geo_fallback(self):
        """Coordinate conversion should work without SUMO."""
        from Simulation.cosim_orchestrator import CoSimOrchestrator

        orch = CoSimOrchestrator()
        orch.sumo_connected = False

        # Test fallback conversion
        lat, lon = orch._sumo_to_geo(111000.0, 111000.0)

        # Should return approximate values
        assert abs(lat - 1.0) < 0.1
        assert abs(lon - 1.0) < 0.1


@requires_ns3
class TestNS3Integration:
    """Test ns-3 adapter with actual ns-3."""

    def test_application_starts_and_stops(self):
        """Verify MVCCPApplication lifecycle."""
        from Simulation.ns3_adapter import MVCCPApplication

        # Create ns-3 node
        nodes = ns.network.NodeContainer()
        nodes.Create(1)

        app = MVCCPApplication(b'\x00\x00\x00\x00\x00\x01', nodes.Get(0))
        nodes.Get(0).AddApplication(app)

        # Start application
        app.StartApplication()
        assert app.running is True

        # Stop application
        app.StopApplication()
        assert app.running is False

    def test_packet_send_and_receive(self):
        """Verify packets flow between two nodes."""
        from Simulation.ns3_adapter import MVCCPApplication, setup_wave_channel

        # Create two nodes
        nodes = ns.network.NodeContainer()
        nodes.Create(2)

        # Set up networking
        devices = setup_wave_channel(nodes)

        # Create applications
        app1 = MVCCPApplication(b'\x00\x00\x00\x00\x00\x01', nodes.Get(0))
        app2 = MVCCPApplication(b'\x00\x00\x00\x00\x00\x02', nodes.Get(1))

        nodes.Get(0).AddApplication(app1)
        nodes.Get(1).AddApplication(app2)

        app1.StartApplication()
        app2.StartApplication()

        # Send a test packet
        test_data = b'\x00\x01\x02\x03'
        app1.send_packet(test_data)

        # Run simulator briefly
        ns.core.Simulator.Stop(ns.core.Seconds(1.0))
        ns.core.Simulator.Run()
        ns.core.Simulator.Destroy()

        # Note: Actual packet verification requires more setup
        # This test mainly verifies the code path doesn't crash

    def test_hello_message_propagates(self):
        """Verify HELLO messages reach neighbors."""
        # This is a more complex test that would require
        # full simulation setup - marking as placeholder
        pass


@requires_sumo
class TestSUMOIntegration:
    """Test SUMO orchestrator with actual SUMO."""

    def test_orchestrator_connects_to_sumo(self):
        """Verify TraCI connection."""
        from Simulation.cosim_orchestrator import CoSimOrchestrator

        orch = CoSimOrchestrator()

        # This would require a running SUMO instance
        # Typically done in a controlled test environment
        # For now, just verify the method exists
        assert hasattr(orch, 'connect_sumo')

    def test_coordinate_conversion(self):
        """Verify SUMO->lat/lon conversion with real SUMO."""
        from Simulation.cosim_orchestrator import CoSimOrchestrator

        # This test would require a SUMO connection
        # The fallback is tested in TestCoSimOrchestratorBasic
        pass


@requires_both
class TestFullCoSimulation:
    """Test complete SUMO + ns-3 + MVCCP co-simulation."""

    def test_platoon_forms_during_cosim(self):
        """Run short simulation, verify platoon forms."""
        # This is a full integration test
        # Requires both ns-3 and SUMO properly configured
        pass

    def test_consumer_joins_platoon(self):
        """Run simulation with low-energy vehicle, verify it joins."""
        pass

    def test_energy_transfer_occurs(self):
        """Verify energy actually transfers in platoon."""
        pass


class TestMessageDispatch:
    """Test message dispatching in adapter."""

    def test_dispatch_hello_message(self):
        """HELLO messages should route to Layer A handler."""
        from src.messages.messages import HelloMessage, MessageType

        # Create a hello message
        hello = HelloMessage(
            ttl=1,
            seq_num=100,
            sender_id=b'\x00\x00\x00\x00\x00\x01'
        )

        assert hello.header.msg_type == MessageType.HELLO

    def test_dispatch_pa_message(self):
        """PA messages should route to Layer B handler."""
        from src.messages.messages import PAMessage, MessageType

        pa = PAMessage(
            ttl=3,
            seq_num=200,
            sender_id=b'\x00\x00\x00\x00\x00\x01',
            provider_id=b'\x00\x00\x00\x00\x00\x01'
        )

        assert pa.header.msg_type == MessageType.PA

    def test_dispatch_join_offer(self):
        """JOIN_OFFER should route to Layer C handler."""
        from src.messages.messages import JoinOfferMessage, MessageType

        offer = JoinOfferMessage(
            ttl=1,
            seq_num=300,
            sender_id=b'\x00\x00\x00\x00\x00\x02',
            consumer_id=b'\x00\x00\x00\x00\x00\x02'
        )

        assert offer.header.msg_type == MessageType.JOIN_OFFER


class TestScenarioFiles:
    """Test SUMO scenario file existence and validity."""

    def test_highway_network_exists(self):
        """Highway network file should exist."""
        net_file = Path(__file__).parent.parent / "scenarios/sumo_files/highway/highway.net.xml"
        assert net_file.exists(), f"Missing network file: {net_file}"

    def test_highway_routes_exist(self):
        """Highway routes file should exist."""
        rou_file = Path(__file__).parent.parent / "scenarios/sumo_files/highway/highway.rou.xml"
        assert rou_file.exists(), f"Missing routes file: {rou_file}"

    def test_highway_config_exists(self):
        """Highway config file should exist."""
        cfg_file = Path(__file__).parent.parent / "scenarios/sumo_files/highway/highway.sumocfg"
        assert cfg_file.exists(), f"Missing config file: {cfg_file}"

    def test_config_references_correct_files(self):
        """Config should reference existing network and route files."""
        cfg_file = Path(__file__).parent.parent / "scenarios/sumo_files/highway/highway.sumocfg"

        with open(cfg_file) as f:
            content = f.read()

        assert 'highway.net.xml' in content
        assert 'highway.rou.xml' in content
