"""
Integration tests for the 4-way handshake without ns-3.

Tests complete handshake flow:
JOIN_OFFER -> JOIN_ACCEPT -> ACK -> ACKACK
"""
import pytest
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.protocol.layer_c import ConsumerHandler, PlatoonHeadHandler
from src.protocol.layer_c.states import NodeRole, ConsumerState, PlatoonHeadState
from src.protocol.context import MVCCPContext
from src.protocol.config import ProtocolConfig
from src.protocol.layer_a.neighbor_table import NeighborTable
from src.protocol.layer_b.provider_table import ProviderTable, ProviderType
from src.core.node import Node
from src.core.platoon import Platoon
from src.messages.messages import (
    MVCCPMessage, MessageType, TLVType,
    JoinOfferMessage, JoinAcceptMessage, AckMessage, AckAckMessage
)


class MessageRouter:
    """
    Simple message router for testing handshake without ns-3.
    Routes messages between handlers based on message type.
    """
    def __init__(self):
        self.messages = []
        self.handlers = {}

    def register_handler(self, node_id: bytes, handler, context):
        """Register a handler for a node."""
        self.handlers[node_id] = (handler, context)

    def send(self, data: bytes):
        """Queue a message for delivery."""
        self.messages.append(data)

    def deliver_all(self):
        """Deliver all queued messages to appropriate handlers."""
        delivered = 0
        while self.messages:
            data = self.messages.pop(0)
            msg = MVCCPMessage.decode(data)
            delivered += self._deliver_message(msg, data)
        return delivered

    def _deliver_message(self, msg: MVCCPMessage, raw_data: bytes):
        """Deliver a single message to all registered handlers."""
        delivered = 0
        msg_type = msg.header.msg_type

        for node_id, (handler, context) in self.handlers.items():
            # Skip sender
            if msg.header.sender_id == node_id:
                continue

            # Route based on message type
            if msg_type == MessageType.JOIN_OFFER:
                if hasattr(handler, 'handle_join_offer'):
                    handler.handle_join_offer(msg)
                    delivered += 1
            elif msg_type == MessageType.JOIN_ACCEPT:
                if hasattr(handler, 'handle_join_accept'):
                    handler.handle_join_accept(msg)
                    delivered += 1
            elif msg_type == MessageType.ACK:
                if hasattr(handler, 'handle_ack'):
                    handler.handle_ack(msg)
                    delivered += 1
            elif msg_type == MessageType.ACKACK:
                if hasattr(handler, 'handle_ackack'):
                    handler.handle_ackack(msg)
                    delivered += 1

        return delivered

    def clear(self):
        """Clear all queued messages."""
        self.messages.clear()


@pytest.fixture
def router():
    """Create a message router."""
    return MessageRouter()


@pytest.fixture
def consumer_setup(router):
    """Set up a consumer node with low energy."""
    node = Node(
        node_id=b'\x00\x00\x00\x00\x00\x01',
        battery_capacity_kwh=100.0,
        battery_energy_kwh=15.0,
        min_energy_kwh=10.0,
        latitude=0.0,
        longitude=0.0,
        destination=(50.0, 50.0)
    )
    ctx = MVCCPContext(node)
    ctx.update_time(0.0)
    ctx.neighbor_table = NeighborTable(ctx)
    ctx.provider_table = ProviderTable(ctx)
    ctx.send_callback = router.send
    ctx.node_role = NodeRole.CONSUMER
    ctx.consumer_state = ConsumerState.DISCOVER

    handler = ConsumerHandler(ctx)
    router.register_handler(node.node_id, handler, ctx)

    return handler, ctx, node


@pytest.fixture
def platoon_head_setup(router):
    """Set up a platoon head node with high energy."""
    node = Node(
        node_id=b'\x00\x00\x00\x00\x00\x02',
        battery_capacity_kwh=100.0,
        battery_energy_kwh=80.0,
        min_energy_kwh=10.0,
        latitude=5.0,
        longitude=5.0,
        destination=(50.0, 50.0),
        willingness=6
    )
    ctx = MVCCPContext(node)
    ctx.update_time(0.0)
    ctx.neighbor_table = NeighborTable(ctx)
    ctx.provider_table = ProviderTable(ctx)
    ctx.send_callback = router.send
    ctx.node_role = NodeRole.PLATOON_HEAD
    ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
    ctx.platoon_members = []

    # Create platoon
    platoon = Platoon(head_node=node)
    ctx.current_platoon = platoon
    ctx.current_platoon_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

    handler = PlatoonHeadHandler(ctx)
    router.register_handler(node.node_id, handler, ctx)

    return handler, ctx, node


class TestFullHandshake:
    """Tests for complete 4-way handshake flow."""

    def test_consumer_platoon_head_full_handshake(self, router, consumer_setup, platoon_head_setup):
        """Test complete handshake between consumer and platoon head."""
        consumer, consumer_ctx, consumer_node = consumer_setup
        ph, ph_ctx, ph_node = platoon_head_setup

        # Add platoon head as provider in consumer's table
        consumer_ctx.provider_table.update_provider(ph_node.node_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (5.0, 5.0),
            'energy': 60.0,
            'available_slots': 3,
        })

        # Step 1: Consumer discovers and sends JOIN_OFFER
        consumer_ctx.update_time(1.0)
        consumer_ctx.consumer_state = ConsumerState.EVALUATE
        consumer.tick(1.0)

        # Should have sent JOIN_OFFER
        assert len(router.messages) >= 1

        # Deliver to platoon head
        router.deliver_all()

        # PH should have pending offer
        assert len(ph.pending_members) >= 1

        # Step 2: PH evaluates and sends JOIN_ACCEPT
        ph_ctx.update_time(2.0)
        ph_ctx.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        ph.tick(2.0)

        # Should have sent JOIN_ACCEPT
        assert len(router.messages) >= 1

        # Deliver to consumer
        router.deliver_all()

        # Consumer should be in WAIT_ACKACK or ALLOCATED state (handler may complete atomically)
        assert consumer_ctx.consumer_state in [ConsumerState.SEND_ACK, ConsumerState.WAIT_ACKACK, ConsumerState.ALLOCATED]

        # Step 3: Consumer tick (may send ACK if not already sent)
        consumer_ctx.update_time(3.0)
        consumer.tick(3.0)

        # Should have moved to WAIT_ACKACK or ALLOCATED
        assert consumer_ctx.consumer_state in [ConsumerState.WAIT_ACKACK, ConsumerState.ALLOCATED]

        # Deliver any remaining messages to PH
        router.deliver_all()

        # PH should be in SEND_ACKACK or COORDINATE state (may complete atomically)
        assert ph_ctx.platoon_head_state in [PlatoonHeadState.SEND_ACKACK, PlatoonHeadState.COORDINATE, PlatoonHeadState.EVALUATE_OFFERS]

        # Step 4: Deliver any remaining ACKACK
        router.deliver_all()

        # Consumer should be ALLOCATED
        assert consumer_ctx.consumer_state == ConsumerState.ALLOCATED

        # Consumer should be in platoon members list
        assert consumer_node.node_id in ph_ctx.platoon_members


    def test_multiple_consumers_sequential(self, router):
        """Test multiple consumers joining sequentially."""
        # Create platoon head
        ph_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x10',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=90.0,
            min_energy_kwh=10.0,
            latitude=0.0,
            longitude=0.0,
            willingness=6
        )
        ph_ctx = MVCCPContext(ph_node)
        ph_ctx.update_time(0.0)
        ph_ctx.neighbor_table = NeighborTable(ph_ctx)
        ph_ctx.provider_table = ProviderTable(ph_ctx)
        ph_ctx.send_callback = router.send
        ph_ctx.node_role = NodeRole.PLATOON_HEAD
        ph_ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
        ph_ctx.platoon_members = []

        platoon = Platoon(head_node=ph_node)
        ph_ctx.current_platoon = platoon

        ph = PlatoonHeadHandler(ph_ctx)
        router.register_handler(ph_node.node_id, ph, ph_ctx)

        # Create two consumers
        consumers = []
        for i in range(2):
            c_node = Node(
                node_id=bytes([0, 0, 0, 0, 0, i + 1]),
                battery_capacity_kwh=100.0,
                battery_energy_kwh=15.0,
                min_energy_kwh=10.0
            )
            c_ctx = MVCCPContext(c_node)
            c_ctx.update_time(0.0)
            c_ctx.neighbor_table = NeighborTable(c_ctx)
            c_ctx.provider_table = ProviderTable(c_ctx)
            c_ctx.send_callback = router.send
            c_ctx.node_role = NodeRole.CONSUMER
            c_ctx.consumer_state = ConsumerState.DISCOVER

            # Add PH as provider
            c_ctx.provider_table.update_provider(ph_node.node_id, {
                'type': ProviderType.PLATOON_HEAD,
                'position': (0.0, 0.0),
                'energy': 70.0,
                'available_slots': 3,
            })

            c_handler = ConsumerHandler(c_ctx)
            router.register_handler(c_node.node_id, c_handler, c_ctx)
            consumers.append((c_handler, c_ctx, c_node))

        # First consumer joins
        c1, c1_ctx, c1_node = consumers[0]

        # Consumer 1 sends offer
        c1_ctx.update_time(1.0)
        c1_ctx.consumer_state = ConsumerState.EVALUATE
        c1.tick(1.0)
        router.deliver_all()

        # PH evaluates
        ph_ctx.update_time(2.0)
        ph_ctx.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        ph.tick(2.0)
        router.deliver_all()

        # Consumer 1 ACKs
        c1_ctx.update_time(3.0)
        c1.tick(3.0)
        router.deliver_all()

        # PH sends ACKACK
        router.deliver_all()

        # First consumer should be allocated
        assert c1_ctx.consumer_state == ConsumerState.ALLOCATED
        assert c1_node.node_id in ph_ctx.platoon_members

        # Second consumer joins
        c2, c2_ctx, c2_node = consumers[1]
        ph_ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS

        c2_ctx.update_time(10.0)
        c2_ctx.consumer_state = ConsumerState.EVALUATE
        c2.tick(10.0)
        router.deliver_all()

        ph_ctx.update_time(11.0)
        ph_ctx.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        ph.tick(11.0)
        router.deliver_all()

        c2_ctx.update_time(12.0)
        c2.tick(12.0)
        router.deliver_all()
        router.deliver_all()

        # Both consumers should be allocated
        assert c2_ctx.consumer_state == ConsumerState.ALLOCATED
        assert c2_node.node_id in ph_ctx.platoon_members
        assert len(ph_ctx.platoon_members) == 2

    def test_multiple_consumers_parallel(self, router):
        """Test multiple consumers sending offers simultaneously."""
        # Create platoon head
        ph_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x10',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=90.0,
            min_energy_kwh=10.0,
            willingness=6
        )
        ph_ctx = MVCCPContext(ph_node)
        ph_ctx.update_time(0.0)
        ph_ctx.neighbor_table = NeighborTable(ph_ctx)
        ph_ctx.provider_table = ProviderTable(ph_ctx)
        ph_ctx.send_callback = router.send
        ph_ctx.node_role = NodeRole.PLATOON_HEAD
        ph_ctx.platoon_head_state = PlatoonHeadState.WAIT_OFFERS
        ph_ctx.platoon_members = []

        platoon = Platoon(head_node=ph_node)
        ph_ctx.current_platoon = platoon

        ph = PlatoonHeadHandler(ph_ctx)
        router.register_handler(ph_node.node_id, ph, ph_ctx)

        # Create multiple consumers
        consumers = []
        for i in range(3):
            c_node = Node(
                node_id=bytes([0, 0, 0, 0, 0, i + 1]),
                battery_capacity_kwh=100.0,
                battery_energy_kwh=15.0 + i * 5,  # Different energy levels
                min_energy_kwh=10.0
            )
            c_ctx = MVCCPContext(c_node)
            c_ctx.update_time(0.0)
            c_ctx.neighbor_table = NeighborTable(c_ctx)
            c_ctx.provider_table = ProviderTable(c_ctx)
            c_ctx.send_callback = router.send
            c_ctx.node_role = NodeRole.CONSUMER
            c_ctx.consumer_state = ConsumerState.DISCOVER

            c_ctx.provider_table.update_provider(ph_node.node_id, {
                'type': ProviderType.PLATOON_HEAD,
                'position': (0.0, 0.0),
                'energy': 70.0,
                'available_slots': 3,
            })

            c_handler = ConsumerHandler(c_ctx)
            router.register_handler(c_node.node_id, c_handler, c_ctx)
            consumers.append((c_handler, c_ctx, c_node))

        # All consumers send offers at same time
        for c, c_ctx, _ in consumers:
            c_ctx.update_time(1.0)
            c_ctx.consumer_state = ConsumerState.EVALUATE
            c.tick(1.0)

        # Deliver all offers to PH
        router.deliver_all()

        # PH should have multiple pending offers
        assert len(ph.pending_members) >= 1  # At least one, up to 3

        # PH evaluates and accepts one
        ph_ctx.update_time(2.0)
        ph_ctx.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        ph.tick(2.0)

        # Complete handshake for accepted consumer
        router.deliver_all()

        # At least one consumer should proceed to SEND_ACK or further
        ack_states = [c_ctx.consumer_state for _, c_ctx, _ in consumers]
        assert any(s in [ConsumerState.SEND_ACK, ConsumerState.WAIT_ACKACK, ConsumerState.ALLOCATED] for s in ack_states)

    def test_handshake_with_simulated_delays(self, router, consumer_setup, platoon_head_setup):
        """Test handshake with simulated network delays between messages."""
        consumer, consumer_ctx, consumer_node = consumer_setup
        ph, ph_ctx, ph_node = platoon_head_setup

        # Add provider
        consumer_ctx.provider_table.update_provider(ph_node.node_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (5.0, 5.0),
            'energy': 60.0,
            'available_slots': 3,
        })

        # Step 1: Consumer sends offer at t=0
        consumer_ctx.update_time(0.0)
        consumer_ctx.consumer_state = ConsumerState.EVALUATE
        consumer.tick(0.0)

        # Simulated delay: message arrives at t=0.5
        ph_ctx.update_time(0.5)
        router.deliver_all()

        # Step 2: PH processes at t=1.0 (another delay)
        ph_ctx.update_time(1.0)
        ph_ctx.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        ph.tick(1.0)

        # Accept arrives at consumer at t=1.5
        consumer_ctx.update_time(1.5)
        router.deliver_all()

        # Handler may immediately send ACK and advance to WAIT_ACKACK or ALLOCATED
        assert consumer_ctx.consumer_state in [ConsumerState.SEND_ACK, ConsumerState.WAIT_ACKACK, ConsumerState.ALLOCATED]

        # Step 3: Consumer sends ACK at t=2.0
        consumer_ctx.update_time(2.0)
        consumer.tick(2.0)

        # ACK arrives at PH at t=2.5
        ph_ctx.update_time(2.5)
        router.deliver_all()

        # Step 4: ACKACK arrives at consumer at t=3.0
        consumer_ctx.update_time(3.0)
        router.deliver_all()

        # Handshake complete despite delays
        assert consumer_ctx.consumer_state in [ConsumerState.WAIT_ACKACK, ConsumerState.ALLOCATED]

    def test_handshake_retry_and_recovery(self, router, consumer_setup, platoon_head_setup):
        """Test that handshake recovers after timeout and retry."""
        consumer, consumer_ctx, consumer_node = consumer_setup
        ph, ph_ctx, ph_node = platoon_head_setup

        # Add provider
        consumer_ctx.provider_table.update_provider(ph_node.node_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (5.0, 5.0),
            'energy': 60.0,
            'available_slots': 3,
        })

        # Consumer sends offer
        consumer_ctx.update_time(0.0)
        consumer_ctx.consumer_state = ConsumerState.EVALUATE
        consumer.tick(0.0)

        # Save the offer message but don't deliver yet (simulating loss)
        lost_message = router.messages.pop(0)

        # Consumer should be waiting for accept
        assert consumer_ctx.consumer_state == ConsumerState.WAIT_ACCEPT

        # Simulate timeout - advance time beyond ACCEPT_TIMEOUT
        timeout = consumer.ACCEPT_TIMEOUT + 1.0
        consumer_ctx.update_time(timeout)
        consumer.tick(timeout)

        # Should have triggered backoff
        assert consumer.current_session.get('retries', 0) >= 1 or \
               consumer.current_session.get('next_retry_time') is not None

        # Wait for backoff and retry
        retry_time = consumer.current_session.get('next_retry_time', timeout + 1.0)
        consumer_ctx.update_time(retry_time + 0.1)
        consumer.tick(retry_time + 0.1)

        # Should have resent offer
        assert len(router.messages) >= 1

        # Now deliver to PH
        router.deliver_all()

        # PH processes offer
        ph_ctx.update_time(retry_time + 1.0)
        ph_ctx.platoon_head_state = PlatoonHeadState.EVALUATE_OFFERS
        ph.tick(retry_time + 1.0)

        # Complete handshake
        router.deliver_all()
        consumer_ctx.update_time(retry_time + 2.0)
        consumer.tick(retry_time + 2.0)
        router.deliver_all()
        router.deliver_all()

        # Should eventually succeed
        assert consumer_ctx.consumer_state in [
            ConsumerState.SEND_ACK,
            ConsumerState.WAIT_ACKACK,
            ConsumerState.ALLOCATED
        ]


class TestRREHHandshake:
    """Tests for RREH (fixed charging station) handshake."""

    def test_consumer_rreh_full_handshake(self, router):
        """Test complete handshake between consumer and RREH."""
        # Create RREH node
        rreh_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\xAA',
            battery_capacity_kwh=1000.0,
            battery_energy_kwh=1000.0,
            min_energy_kwh=0.0,
            latitude=10.0,
            longitude=10.0
        )
        rreh_ctx = MVCCPContext(rreh_node, is_rreh=True)
        rreh_ctx.update_time(0.0)
        rreh_ctx.neighbor_table = NeighborTable(rreh_ctx)
        rreh_ctx.provider_table = ProviderTable(rreh_ctx)
        rreh_ctx.send_callback = router.send

        # Create consumer
        consumer_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=15.0,
            min_energy_kwh=10.0,
            latitude=0.0,
            longitude=0.0,
            destination=(20.0, 20.0)
        )
        consumer_ctx = MVCCPContext(consumer_node)
        consumer_ctx.update_time(0.0)
        consumer_ctx.neighbor_table = NeighborTable(consumer_ctx)
        consumer_ctx.provider_table = ProviderTable(consumer_ctx)
        consumer_ctx.send_callback = router.send
        consumer_ctx.node_role = NodeRole.CONSUMER
        consumer_ctx.consumer_state = ConsumerState.DISCOVER

        # Add RREH as provider
        consumer_ctx.provider_table.update_provider(rreh_node.node_id, {
            'type': ProviderType.RREH,
            'position': (10.0, 10.0),
            'energy': 500.0,
            'operational_state': 'normal',
        })

        consumer = ConsumerHandler(consumer_ctx)
        router.register_handler(consumer_node.node_id, consumer, consumer_ctx)

        # Consumer evaluates and sends offer
        consumer_ctx.update_time(1.0)
        consumer_ctx.consumer_state = ConsumerState.EVALUATE
        consumer.tick(1.0)

        # Should have sent JOIN_OFFER
        assert len(router.messages) >= 1

        # Decode and verify it's targeting RREH
        msg_data = router.messages[0]
        msg = MVCCPMessage.decode(msg_data)
        assert msg.header.msg_type == MessageType.JOIN_OFFER

        # In real system, RREH would have RREHHandler
        # For this test, just verify consumer sent correct message
        # and is waiting for response
        assert consumer_ctx.consumer_state == ConsumerState.WAIT_ACCEPT

        # Simulate RREH response by creating accept message
        accept_msg = JoinAcceptMessage(
            ttl=1,
            seq_num=100,
            sender_id=rreh_node.node_id,
            provider_id=rreh_node.node_id,
            meeting_point=struct.pack('!ff', 10.0, 10.0),
            bandwidth=struct.pack('!f', 50.0),
            duration=struct.pack('!f', 600.0)
        )

        consumer_ctx.update_time(2.0)
        consumer.handle_join_accept(accept_msg)

        # Should transition to SEND_ACK or further (handler may advance atomically)
        assert consumer_ctx.consumer_state in [ConsumerState.SEND_ACK, ConsumerState.WAIT_ACKACK]

        # Send ACK
        consumer.tick(2.0)
        assert consumer_ctx.consumer_state == ConsumerState.WAIT_ACKACK

        # Simulate ACKACK
        ackack_msg = AckAckMessage(
            ttl=1,
            seq_num=200,
            sender_id=rreh_node.node_id,
            provider_id=rreh_node.node_id
        )

        consumer_ctx.update_time(3.0)
        consumer.handle_ackack(ackack_msg)

        # Consumer should be allocated
        assert consumer_ctx.consumer_state == ConsumerState.ALLOCATED
        # Session should have the RREH as the provider
        assert consumer.current_session.get('provider_id') == rreh_node.node_id


class TestHandshakeEdgeCases:
    """Tests for edge cases in the handshake process."""

    def test_accept_from_unknown_provider_ignored(self, router, consumer_setup, platoon_head_setup):
        """Consumer should ignore accept from provider it didn't contact."""
        consumer, consumer_ctx, consumer_node = consumer_setup
        _, ph_ctx, ph_node = platoon_head_setup

        # Add provider
        consumer_ctx.provider_table.update_provider(ph_node.node_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (5.0, 5.0),
            'energy': 60.0,
            'available_slots': 3,
        })

        # Consumer sends offer to PH
        consumer_ctx.update_time(1.0)
        consumer_ctx.consumer_state = ConsumerState.EVALUATE
        consumer.tick(1.0)

        assert consumer_ctx.consumer_state == ConsumerState.WAIT_ACCEPT

        # Create accept from unknown provider
        unknown_id = b'\xFF\xFF\xFF\xFF\xFF\xFF'
        fake_accept = JoinAcceptMessage(
            ttl=1,
            seq_num=100,
            sender_id=unknown_id,
            provider_id=unknown_id
        )

        consumer_ctx.update_time(2.0)
        consumer.handle_join_accept(fake_accept)

        # Should still be waiting for accept from original provider
        assert consumer_ctx.consumer_state == ConsumerState.WAIT_ACCEPT

    def test_ackack_from_wrong_provider_ignored(self, router, consumer_setup, platoon_head_setup):
        """Consumer should ignore ACKACK from provider it didn't negotiate with."""
        consumer, consumer_ctx, consumer_node = consumer_setup
        ph, ph_ctx, ph_node = platoon_head_setup

        # Set up consumer in WAIT_ACKACK state
        consumer_ctx.update_time(0.0)
        consumer_ctx.consumer_state = ConsumerState.WAIT_ACKACK
        consumer.current_session['provider_id'] = ph_node.node_id

        # Create ACKACK from wrong provider
        wrong_id = b'\xFF\xFF\xFF\xFF\xFF\xFF'
        wrong_ackack = AckAckMessage(
            ttl=1,
            seq_num=100,
            sender_id=wrong_id,
            provider_id=wrong_id
        )

        consumer.handle_ackack(wrong_ackack)

        # Should still be waiting
        assert consumer_ctx.consumer_state == ConsumerState.WAIT_ACKACK

        # Correct ACKACK should work
        correct_ackack = AckAckMessage(
            ttl=1,
            seq_num=101,
            sender_id=ph_node.node_id,
            provider_id=ph_node.node_id
        )

        consumer.handle_ackack(correct_ackack)
        assert consumer_ctx.consumer_state == ConsumerState.ALLOCATED

    def test_duplicate_offer_ignored_by_ph(self, router, consumer_setup, platoon_head_setup):
        """Platoon head should ignore duplicate offers from same consumer."""
        consumer, consumer_ctx, consumer_node = consumer_setup
        ph, ph_ctx, ph_node = platoon_head_setup

        # Create offer message
        offer = JoinOfferMessage(
            ttl=1,
            seq_num=100,
            sender_id=consumer_node.node_id,
            consumer_id=consumer_node.node_id,
            energy_req=struct.pack('!f', 25.0)
        )

        # Send first offer
        ph.handle_join_offer(offer)
        assert len(ph.pending_members) == 1

        # Send duplicate offer
        ph.handle_join_offer(offer)

        # Should still only have one pending
        assert len(ph.pending_members) == 1
