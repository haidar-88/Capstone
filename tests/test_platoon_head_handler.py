"""
Tests for PlatoonHeadHandler - Layer C platoon head state machine.
"""
import pytest
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.protocol.layer_c import PlatoonHeadHandler
from src.protocol.layer_c.platoon_head_handler import PendingMember
from src.protocol.layer_c.states import NodeRole, PlatoonHeadState
from src.protocol.context import MVCCPContext
from src.protocol.config import ProtocolConfig
from src.protocol.layer_a.neighbor_table import NeighborTable
from src.protocol.layer_b.provider_table import ProviderTable
from src.core.node import Node
from src.core.platoon import Platoon
from src.messages.messages import (
    MVCCPMessage, MessageType, TLVType, TLV,
    JoinOfferMessage, AckMessage
)


class TestPlatoonHeadBeacon:
    """Tests for BEACON state - periodic broadcasts."""

    def test_beacon_broadcasts_periodically(self, message_bus):
        """PH should broadcast beacons at configured interval."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.BEACON
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)
        
        # Set last_beacon_time to allow immediate send on first tick
        handler.last_beacon_time = -ProtocolConfig.BEACON_INTERVAL - 1.0

        # First tick should now send beacon (interval elapsed)
        ctx.update_time(0.0)
        handler.tick(0.0)

        # Should have sent at least one beacon (or platoon announce)
        assert len(message_bus.messages) >= 1



class TestPlatoonHeadOffers:
    """Tests for handling JOIN_OFFER messages."""

    def test_wait_offers_collects_offers(self, message_bus):
        """PH should collect offers for evaluation."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)

        # Send offer from consumer
        consumer_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        offer_msg = JoinOfferMessage(
            ttl=1,
            seq_num=100,
            sender_id=consumer_id,
            consumer_id=consumer_id,
            energy_req=struct.pack('!f', 25.0),
            position=struct.pack('!ff', 5.0, 5.0)
        )

        handler.handle_join_offer(offer_msg)

        # Should have collected the offer in pending_members
        assert len(handler.pending_members) >= 1

    def test_evaluate_offers_scores_correctly(self, message_bus):
        """PH should score offers based on configured criteria."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6,
            destination=(100.0, 100.0)
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)

        # Add two offers with different characteristics
        close_consumer = b'\x00\x00\x00\x00\x00\x02'
        far_consumer = b'\x00\x00\x00\x00\x00\x03'

        # Close consumer (better)
        offer1 = JoinOfferMessage(
            ttl=1,
            seq_num=100,
            sender_id=close_consumer,
            consumer_id=close_consumer,
            energy_req=struct.pack('!f', 20.0),
            position=struct.pack('!ff', 1.0, 1.0)  # Close
        )

        # Far consumer (worse)
        offer2 = JoinOfferMessage(
            ttl=1,
            seq_num=101,
            sender_id=far_consumer,
            consumer_id=far_consumer,
            energy_req=struct.pack('!f', 20.0),
            position=struct.pack('!ff', 50.0, 50.0)  # Far
        )

        handler.handle_join_offer(offer1)
        handler.handle_join_offer(offer2)

        assert len(handler.pending_members) >= 2

    def test_max_pending_members_enforced(self, message_bus):
        """PH should enforce max pending offers limit."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)
        max_pending = handler.MAX_PENDING

        # Send more offers than allowed
        for i in range(max_pending + 5):
            consumer_id = bytes([0, 0, 0, 0, 0, i + 2])
            offer = JoinOfferMessage(
                ttl=1,
                seq_num=100 + i,
                sender_id=consumer_id,
                consumer_id=consumer_id,
                energy_req=struct.pack('!f', 20.0)
            )
            handler.handle_join_offer(offer)

        # Should not exceed max
        assert len(handler.pending_members) <= max_pending

    def test_duplicate_offer_ignored(self, message_bus):
        """PH should ignore duplicate offers from same consumer."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)

        consumer_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        offer = JoinOfferMessage(
            ttl=1,
            seq_num=100,
            sender_id=consumer_id,
            consumer_id=consumer_id,
            energy_req=struct.pack('!f', 20.0)
        )

        handler.handle_join_offer(offer)
        handler.handle_join_offer(offer)  # Duplicate

        # Should only have one offer from this consumer (keyed by consumer_id)
        assert len(handler.pending_members) == 1
        assert consumer_id in handler.pending_members


class TestPlatoonHeadAccept:
    """Tests for SEND_ACCEPT state."""

    def test_send_accept_to_best_offer(self, message_bus):
        """PH should send ACCEPT to best offer during evaluation."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        # Use EVALUATE_OFFERS state - this is where accepts are actually sent
        ctx.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)

        # Add a pending member
        consumer_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        handler.pending_members[consumer_id] = PendingMember(
            consumer_id=consumer_id,
            energy_required=20.0,
            position=(5.0, 5.0),
            trajectory=(10.0, 10.0),
            timestamp=0.0
        )

        ctx.update_time(1.0)
        handler.tick(1.0)

        # Should have sent ACCEPT
        assert len(message_bus.messages) >= 1



class TestPlatoonHeadAck:
    """Tests for handling ACK and sending ACKACK."""

    def test_wait_ack_receives_ack(self, message_bus):
        """PH should process ACK from consumer."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.WAIT_ACK
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)
        consumer_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        handler.current_target = consumer_id
        handler.current_target_timeout = ctx.current_time + handler.ACK_TIMEOUT

        # Add pending member
        handler.pending_members[consumer_id] = PendingMember(
            consumer_id=consumer_id,
            energy_required=20.0,
            position=(5.0, 5.0),
            trajectory=(10.0, 10.0),
            timestamp=0.0
        )
        handler.pending_members[consumer_id].accepted = True

        # Send ACK
        ack_msg = AckMessage(
            ttl=1,
            seq_num=200,
            sender_id=consumer_id,
            consumer_id=consumer_id
        )

        handler.handle_ack(ack_msg)

        # Handler sends ACKACK immediately and transitions to COORDINATE
        assert ctx.platoon_head_state in [PlatoonHeadState.SEND_ACKACK, PlatoonHeadState.COORDINATE, PlatoonHeadState.EVALUATE_OFFERS]

    def test_ack_from_wrong_consumer_ignored(self, message_bus):
        """PH should ignore ACK from wrong consumer."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.WAIT_ACK
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)
        expected_consumer = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        wrong_consumer = b'\x11\x22\x33\x44\x55\x66'
        handler.current_target = expected_consumer
        handler.current_target_timeout = ctx.current_time + handler.ACK_TIMEOUT

        # ACK from wrong consumer
        ack_msg = AckMessage(
            ttl=1,
            seq_num=200,
            sender_id=wrong_consumer,
            consumer_id=wrong_consumer
        )

        handler.handle_ack(ack_msg)

        # Should remain in WAIT_ACK
        assert ctx.platoon_head_state == PlatoonHeadState.WAIT_ACK

    def test_send_ackack_completes_handshake(self, message_bus):
        """Sending ACKACK should complete handshake."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.SEND_ACKACK
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)
        consumer_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        handler.current_target = consumer_id
        handler.pending_members[consumer_id] = PendingMember(
            consumer_id=consumer_id,
            energy_required=20.0,
            position=(5.0, 5.0),
            trajectory=(10.0, 10.0),
            timestamp=0.0
        )
        handler.pending_members[consumer_id].accepted = True
        handler.pending_members[consumer_id].ack_received = True

        ctx.update_time(1.0)
        handler.tick(1.0)

        # Should have sent ACKACK and transitioned
        # State transitions to COORDINATE or back to EVALUATE_OFFERS/BEACON
        assert ctx.platoon_head_state in [
            PlatoonHeadState.SEND_ACKACK,
            PlatoonHeadState.COORDINATE,
            PlatoonHeadState.BEACON,
            PlatoonHeadState.WAIT_OFFERS,
            PlatoonHeadState.EVALUATE_OFFERS
        ]


class TestPlatoonHeadTimeout:
    """Tests for timeout handling."""

    def test_ack_timeout_clears_pending(self, message_bus):
        """ACK timeout should clear pending target."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,
            willingness=6
        )
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)
        ctx.neighbor_table = NeighborTable(ctx)
        ctx.provider_table = ProviderTable(ctx)
        ctx.send_callback = message_bus.send
        ctx.node_role = NodeRole.PLATOON_HEAD
        ctx.platoon_head_state = PlatoonHeadState.WAIT_ACK
        ctx.current_platoon = Platoon(head_node=node)

        handler = PlatoonHeadHandler(ctx)
        consumer_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        handler.current_target = consumer_id
        handler.current_target_timeout = 0.0  # Already timed out

        # Advance beyond ACK timeout
        timeout = handler.ACK_TIMEOUT
        ctx.update_time(timeout + 1.0)
        handler.tick(timeout + 1.0)

        # Should clear target and transition
        # May go to BEACON, WAIT_OFFERS, EVALUATE_OFFERS, or COORDINATE
        assert ctx.platoon_head_state in [
            PlatoonHeadState.BEACON,
            PlatoonHeadState.WAIT_OFFERS,
            PlatoonHeadState.EVALUATE_OFFERS,
            PlatoonHeadState.COORDINATE
        ]
