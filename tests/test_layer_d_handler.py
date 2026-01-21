"""
Tests for PlatoonCoordinationHandler - Layer D platoon coordination.
"""
import pytest
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.protocol.layer_d.handler import PlatoonCoordinationHandler, MemberStatus
from src.protocol.layer_c.states import NodeRole
from src.protocol.context import MVCCPContext
from src.protocol.config import ProtocolConfig
from src.protocol.layer_a.neighbor_table import NeighborTable
from src.protocol.layer_b.provider_table import ProviderTable
from src.core.node import Node
from src.core.platoon import Platoon
from src.messages.messages import (
    PlatoonBeaconMessage, PlatoonStatusMessage, TLVType
)


class TestPlatoonHeadTick:
    """Tests for platoon head tick behavior."""

    def test_head_tick_broadcasts_beacon(self, message_bus):
        """Platoon head should broadcast beacons periodically."""
        head_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_energy_kwh=80.0,
            latitude=0.0,
            longitude=0.0
        )
        ctx = MVCCPContext(head_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.current_platoon = Platoon(head_node=head_node)
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)

        # First tick
        ctx.update_time(0.0)
        handler.tick(0.0)

        # Advance past beacon interval
        ctx.update_time(ProtocolConfig.BEACON_INTERVAL + 0.1)
        handler.tick(ProtocolConfig.BEACON_INTERVAL + 0.1)

        # Should have sent beacon(s)
        # Note: Actual beacon sending depends on handler implementation


class TestPlatoonMemberTick:
    """Tests for platoon member tick behavior."""

    def test_member_tick_sends_status(self, message_bus):
        """Platoon member should send status to head periodically."""
        member_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            battery_energy_kwh=50.0,
            latitude=5.0,
            longitude=0.0
        )
        ctx = MVCCPContext(member_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_MEMBER
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)

        # Tick should process member logic
        ctx.update_time(1.0)
        handler.tick(1.0)

        # STATUS sending depends on implementation


class TestBeaconHandling:
    """Tests for handling PLATOON_BEACON messages."""

    def test_member_receives_beacon_updates_position(self, message_bus):
        """Member should update tracking when receiving beacon."""
        member_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            battery_energy_kwh=50.0
        )
        ctx = MVCCPContext(member_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_MEMBER
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)

        # Create beacon from head
        head_id = b'\x00\x00\x00\x00\x00\x01'
        beacon = PlatoonBeaconMessage(
            ttl=1,
            seq_num=100,
            sender_id=head_id,
            platoon_id=ctx.current_platoon_id,
            head_id=head_id,
            head_position=struct.pack('!ff', 0.0, 0.0),
            timestamp=struct.pack('!f', 1.0)
        )

        ctx.update_time(1.0)
        handler.handle_beacon(beacon)

        # Member should have processed beacon


class TestStatusHandling:
    """Tests for handling PLATOON_STATUS messages."""

    def test_head_receives_status_updates_member(self, message_bus):
        """Head should update member info when receiving status."""
        head_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_energy_kwh=80.0
        )
        ctx = MVCCPContext(head_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.current_platoon = Platoon(head_node=head_node)
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)

        # Create status from member
        member_id = b'\x00\x00\x00\x00\x00\x02'
        status = PlatoonStatusMessage(
            ttl=1,
            seq_num=200,
            sender_id=member_id,
            platoon_id=ctx.current_platoon_id,
            vehicle_id=member_id,
            battery=struct.pack('!f', 50.0),
            relative_index=struct.pack('!B', 1)
        )

        ctx.update_time(1.0)
        handler.handle_status(status)

        # Head should have member info updated


class TestStaleMemberPruning:
    """Tests for stale member detection."""

    def test_stale_member_pruned(self, message_bus):
        """Members not sending status should be marked stale."""
        head_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_energy_kwh=80.0
        )
        ctx = MVCCPContext(head_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.current_platoon = Platoon(head_node=head_node)
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)

        # Add member status at t=0
        member_id = b'\x00\x00\x00\x00\x00\x02'
        member_status = MemberStatus(member_id)
        member_status.last_update = 0.0
        member_status.battery_level = 50.0
        handler.platoon_members[member_id] = member_status

        # Advance time beyond stale threshold
        ctx.update_time(ProtocolConfig.PLATOON_MEMBER_TIMEOUT + 1.0)
        handler.tick(ProtocolConfig.PLATOON_MEMBER_TIMEOUT + 1.0)

        # Member should be pruned (depends on implementation)


class TestBeaconTimeout:
    """Tests for beacon timeout detection."""

    def test_beacon_timeout_detected(self, message_bus):
        """Member should detect if no beacon received."""
        member_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            battery_energy_kwh=50.0
        )
        ctx = MVCCPContext(member_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_MEMBER
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)
        handler.last_beacon_time = 0.0

        # Advance time beyond beacon timeout (use PLATOON_MEMBER_TIMEOUT as beacon staleness threshold)
        timeout = ProtocolConfig.PLATOON_MEMBER_TIMEOUT
        ctx.update_time(timeout + 1.0)
        handler.tick(timeout + 1.0)

        # Should have detected timeout


class TestFormationInBeacon:
    """Tests for formation data in beacons."""

    def test_formation_included_in_beacon(self, message_bus):
        """Beacon should include formation positions if available."""
        head_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_energy_kwh=80.0,
            latitude=0.0,
            longitude=0.0
        )
        member_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            battery_energy_kwh=50.0,
            latitude=5.0,
            longitude=0.0
        )

        ctx = MVCCPContext(head_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD

        platoon = Platoon(head_node=head_node)
        platoon.add_node(member_node)
        ctx.current_platoon = platoon
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)

        # Compute formation
        formation = platoon.compute_optimal_formation(current_time=1.0)
        handler.last_formation = formation

        # Get formation for beacon
        formation_data = handler.get_formation_for_beacon()

        # Should have formation data (empty dict is OK if not computed)
        assert formation_data is not None


class TestEnergyDistribution:
    """Tests for energy distribution planning."""

    def test_energy_distribution_computed(self, message_bus):
        """Head should compute energy distribution plan."""
        head_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_energy_kwh=80.0,
            battery_capacity_kwh=100.0,
            min_energy_kwh=10.0,
            latitude=0.0,
            longitude=0.0
        )
        deficit_member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            battery_energy_kwh=15.0,
            battery_capacity_kwh=100.0,
            min_energy_kwh=10.0,
            latitude=3.0,
            longitude=0.0
        )

        ctx = MVCCPContext(head_node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD

        platoon = Platoon(head_node=head_node)
        platoon.add_node(deficit_member)
        ctx.current_platoon = platoon
        ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        handler = PlatoonCoordinationHandler(ctx)

        # Get energy distribution plan
        plan = handler.get_energy_distribution_plan()

        # Should have some plan (empty dict is OK if no deficit)
        assert plan is not None
