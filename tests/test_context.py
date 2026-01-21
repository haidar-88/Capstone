"""
Tests for MVCCPContext - protocol context, time management, and role transitions.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.protocol.context import MVCCPContext
from src.protocol.layer_c.states import NodeRole, ConsumerState, PlatoonHeadState, RREHState
from src.protocol.config import ProtocolConfig, TTLMode
from src.core.node import Node


class TestContextInitialization:
    """Tests for context initialization."""

    def test_context_initializes_time_to_zero(self):
        """Context should initialize current_time to 0.0, not wall-clock."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)

        # Must be 0.0, not wall-clock time
        assert ctx.current_time == 0.0

    def test_context_default_role_is_consumer(self):
        """Non-RREH node should default to CONSUMER role."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node, is_rreh=False)

        assert ctx.node_role == NodeRole.CONSUMER

    def test_context_rreh_role_is_rreh(self):
        """RREH node should have RREH role."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node, is_rreh=True)

        assert ctx.node_role == NodeRole.RREH
        assert ctx.is_rreh()

    def test_context_initializes_rreh_fields(self):
        """RREH context should have RREH-specific fields."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node, is_rreh=True)

        assert hasattr(ctx, 'rreh_queue')
        assert hasattr(ctx, 'rreh_max_sessions')
        assert hasattr(ctx, 'rreh_available_power')
        assert ctx.rreh_max_sessions == 4


class TestTimeManagement:
    """Tests for simulation time management."""

    def test_update_time_monotonic(self):
        """update_time should accept increasing timestamps."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)

        ctx.update_time(1.0)
        assert ctx.current_time == 1.0

        ctx.update_time(2.5)
        assert ctx.current_time == 2.5

        ctx.update_time(100.0)
        assert ctx.current_time == 100.0

    def test_update_time_same_timestamp_allowed(self):
        """update_time should allow same timestamp (not strictly increasing)."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)

        ctx.update_time(5.0)
        ctx.update_time(5.0)  # Same timestamp should be OK

        assert ctx.current_time == 5.0

    def test_update_time_rejects_backward(self):
        """update_time should reject timestamps that go backward."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)

        ctx.update_time(10.0)

        with pytest.raises(ValueError, match="cannot go backward"):
            ctx.update_time(5.0)


class TestRoleTransitions:
    """Tests for role transitions."""

    def test_role_transition_consumer_to_platoon_head(self):
        """Consumer should be able to transition to Platoon Head."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)

        assert ctx.node_role == NodeRole.CONSUMER

        ctx.set_role(NodeRole.PLATOON_HEAD)

        assert ctx.node_role == NodeRole.PLATOON_HEAD
        assert ctx.platoon_head_state == PlatoonHeadState.BEACON
        assert ctx.consumer_state is None

    def test_role_transition_platoon_head_to_consumer(self):
        """Platoon Head should be able to transition back to Consumer."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)

        ctx.set_role(NodeRole.PLATOON_HEAD)
        assert ctx.node_role == NodeRole.PLATOON_HEAD

        ctx.set_role(NodeRole.CONSUMER)

        assert ctx.node_role == NodeRole.CONSUMER
        assert ctx.consumer_state == ConsumerState.DISCOVER
        assert ctx.platoon_head_state is None

    def test_set_role_same_role_noop(self):
        """Setting same role should be a no-op."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)

        ctx.set_role(NodeRole.CONSUMER)  # Already consumer
        assert ctx.node_role == NodeRole.CONSUMER

    def test_role_transition_to_platoon_member(self):
        """Consumer should be able to become Platoon Member."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)

        ctx.set_role(NodeRole.PLATOON_MEMBER)

        assert ctx.node_role == NodeRole.PLATOON_MEMBER
        assert ctx.is_platoon_member()


class TestRoleEligibility:
    """Tests for role eligibility checks."""

    def test_rreh_cannot_become_platoon_head(self):
        """RREH should never be eligible to become Platoon Head."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_energy_kwh=1000.0,  # High energy
            willingness=7
        )
        ctx = MVCCPContext(node, is_rreh=True)
        ctx.update_time(0.0)

        # Even with high energy and willingness, RREH can't be PH
        assert not ctx.can_become_platoon_head()

    def test_can_become_platoon_head_energy_threshold(self):
        """Node needs sufficient shareable energy to become PH."""
        # Node with destination far away (needs energy to reach)
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=30.0,  # Low energy
            min_energy_kwh=10.0,
            destination=(100.0, 100.0),  # Far destination
            willingness=6
        )
        ctx = MVCCPContext(node, is_rreh=False)
        ctx.update_time(0.0)

        # Low shareable energy should disqualify
        assert not ctx.can_become_platoon_head()

    def test_can_become_platoon_head_willingness_threshold(self):
        """Node needs sufficient willingness to become PH."""
        # High energy but low willingness
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=90.0,  # High energy
            min_energy_kwh=10.0,
            destination=(1.0, 1.0),  # Close destination
            willingness=1  # Low willingness
        )
        ctx = MVCCPContext(node, is_rreh=False)
        ctx.update_time(0.0)

        # Should fail willingness check
        assert not ctx.can_become_platoon_head()

    def test_can_become_platoon_head_meets_all_criteria(self):
        """Node meeting all criteria should be eligible for PH."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=85.0,  # High energy
            min_energy_kwh=10.0,
            latitude=0.0,
            longitude=0.0,
            destination=(0.001, 0.001),  # ~0.15km away (truly close)
            willingness=6  # High willingness
        )
        ctx = MVCCPContext(node, is_rreh=False)
        ctx.update_time(0.0)

        assert ctx.can_become_platoon_head()


    def test_platoon_member_cannot_become_platoon_head(self):
        """Current platoon member cannot become PH (already in platoon)."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=85.0,
            willingness=6
        )
        ctx = MVCCPContext(node, is_rreh=False)
        ctx.update_time(0.0)

        # Simulate being in a platoon as member
        ctx.set_role(NodeRole.PLATOON_MEMBER)
        ctx.current_platoon = object()  # Non-None platoon

        assert not ctx.can_become_platoon_head()


class TestNeedsCharge:
    """Tests for needs_charge detection."""

    def test_needs_charge_negative_shareable(self):
        """Node with negative shareable energy needs charge."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=15.0,  # Low energy
            min_energy_kwh=10.0,
            destination=(500.0, 500.0)  # Very far = high energy needed
        )
        ctx = MVCCPContext(node, is_rreh=False)
        ctx.update_time(0.0)

        # shareable = current - energy_to_dest - min
        # With far destination, this should be negative
        assert ctx.needs_charge()

    def test_needs_charge_sufficient_energy(self):
        """Node with sufficient energy doesn't need charge."""
        node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0,  # High energy
            min_energy_kwh=10.0,
            destination=(1.0, 1.0)  # Close destination
        )
        ctx = MVCCPContext(node, is_rreh=False)
        ctx.update_time(0.0)

        assert not ctx.needs_charge()


class TestEffectiveTTL:
    """Tests for TTL calculation modes."""

    def test_effective_ttl_fixed_mode(self):
        """FIXED mode should return base_ttl."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)

        ctx.ttl_mode = TTLMode.FIXED
        ctx.base_ttl = 4

        assert ctx.get_effective_ttl() == 4

    def test_effective_ttl_density_mode_few_neighbors(self):
        """DENSITY mode with few neighbors should give higher TTL."""
        from src.protocol.layer_a.neighbor_table import NeighborTable

        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.update_time(0.0)

        ctx.ttl_mode = TTLMode.DENSITY_BASED
        ctx.neighbor_table = NeighborTable(ctx)

        # Few neighbors = higher TTL (messages need to travel farther)
        # Formula: max(2, min(6, 8 - log2(neighbor_count)))
        ttl = ctx.get_effective_ttl()

        # With 0 neighbors (counted as 1 to avoid log(0)), TTL should be high
        assert ttl >= ProtocolConfig.PA_TTL_MIN
        assert ttl <= ProtocolConfig.PA_TTL_MAX


class TestRoleChecks:
    """Tests for is_* helper methods."""

    def test_is_consumer(self):
        """is_consumer should return True for CONSUMER role."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.node_role = NodeRole.CONSUMER

        assert ctx.is_consumer()
        assert not ctx.is_platoon_head()
        assert not ctx.is_rreh()

    def test_is_platoon_head(self):
        """is_platoon_head should return True for PLATOON_HEAD role."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        ctx.node_role = NodeRole.PLATOON_HEAD

        assert ctx.is_platoon_head()
        assert not ctx.is_consumer()
        assert not ctx.is_rreh()

    def test_is_rreh(self):
        """is_rreh should return True for RREH role."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node, is_rreh=True)

        assert ctx.is_rreh()
        assert not ctx.is_consumer()
        assert not ctx.is_platoon_head()
