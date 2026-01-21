"""
Tests for NeighborTable - Layer A neighbor discovery and management.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.protocol.layer_a.neighbor_table import NeighborTable
from src.protocol.context import MVCCPContext
from src.protocol.config import ProtocolConfig
from src.core.node import Node


class TestNeighborTableCreation:
    """Tests for neighbor table creation and updates."""

    def test_update_neighbor_creates_entry(self, context, node_id_2):
        """Adding a new neighbor should create an entry."""
        table = NeighborTable(context)
        context.neighbor_table = table

        attrs = {
            'battery_energy_kwh': 50.0,
            'etx': 1.0,
            'willingness': 5
        }
        table.update_neighbor(node_id_2, attrs, [])

        neighbors = table.get_one_hop_set()
        assert node_id_2 in neighbors

    def test_update_neighbor_updates_existing(self, context, node_id_2):
        """Updating existing neighbor should modify the entry."""
        table = NeighborTable(context)
        context.neighbor_table = table

        # Initial update
        table.update_neighbor(node_id_2, {'battery_energy_kwh': 50.0}, [])

        # Second update with new values
        table.update_neighbor(node_id_2, {'battery_energy_kwh': 60.0}, [])

        # Verify only one entry exists
        neighbors = table.get_one_hop_set()
        assert len(neighbors) == 1
        assert node_id_2 in neighbors


class TestNeighborTablePruning:
    """Tests for stale neighbor pruning."""

    def test_prune_stale_removes_old_neighbors(self, context, node_id_2, node_id_3):
        """Neighbors not seen recently should be pruned."""
        table = NeighborTable(context)
        context.neighbor_table = table

        # Add neighbor at t=0
        context.update_time(0.0)
        table.update_neighbor(node_id_2, {'battery_energy_kwh': 50.0}, [])

        # Advance time beyond NEIGHBOR_TIMEOUT
        context.update_time(ProtocolConfig.NEIGHBOR_TIMEOUT + 1.0)

        # Add another neighbor (this triggers pruning)
        table.update_neighbor(node_id_3, {'battery_energy_kwh': 60.0}, [])

        # Force prune
        table.prune_stale()

        neighbors = table.get_one_hop_set()
        # node_id_2 should be pruned (stale), node_id_3 should remain
        assert node_id_2 not in neighbors
        assert node_id_3 in neighbors


class TestNeighborTableQueries:
    """Tests for neighbor table query methods."""

    def test_get_one_hop_set_returns_neighbors(self, context, node_id_2, node_id_3):
        """get_one_hop_set should return all direct neighbors."""
        table = NeighborTable(context)
        context.neighbor_table = table

        table.update_neighbor(node_id_2, {}, [])
        table.update_neighbor(node_id_3, {}, [])

        one_hop = table.get_one_hop_set()

        assert len(one_hop) == 2
        assert node_id_2 in one_hop
        assert node_id_3 in one_hop

    def test_get_two_hop_set_excludes_self(self, context, node_id_2):
        """get_two_hop_set should not include self."""
        table = NeighborTable(context)
        context.neighbor_table = table

        self_id = context.node_id
        two_hop_neighbor = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        # Add neighbor that reports self_id as its 2-hop neighbor
        table.update_neighbor(node_id_2, {}, [self_id, two_hop_neighbor])

        two_hop = table.get_two_hop_set()

        # Self should be excluded
        assert self_id not in two_hop
        # Actual 2-hop neighbor should be included
        assert two_hop_neighbor in two_hop

    def test_get_two_hop_set_excludes_one_hop(self, context, node_id_2, node_id_3):
        """get_two_hop_set should not include 1-hop neighbors."""
        table = NeighborTable(context)
        context.neighbor_table = table

        # Add node_id_2 as 1-hop neighbor
        table.update_neighbor(node_id_2, {}, [node_id_3])

        # Add node_id_3 as 1-hop neighbor (it reports node_id_2 as 2-hop)
        table.update_neighbor(node_id_3, {}, [node_id_2])

        two_hop = table.get_two_hop_set()

        # node_id_2 and node_id_3 are both 1-hop, so shouldn't be in 2-hop
        assert node_id_2 not in two_hop
        assert node_id_3 not in two_hop

    def test_get_snapshot_thread_safe(self, context, node_id_2):
        """get_snapshot should return a copy safe to iterate."""
        table = NeighborTable(context)
        context.neighbor_table = table

        table.update_neighbor(node_id_2, {
            'battery_energy_kwh': 50.0,
            'etx': 1.5,
            'willingness': 4
        }, [])

        snapshot = table.get_snapshot()

        # Should have data for node_id_2
        assert node_id_2 in snapshot
        assert snapshot[node_id_2]['battery_energy_kwh'] == 50.0
        assert snapshot[node_id_2]['willingness'] == 4

    def test_get_neighbor_count(self, context, node_id_2, node_id_3):
        """get_neighbor_count should return correct count."""
        table = NeighborTable(context)
        context.neighbor_table = table

        assert table.get_neighbor_count() == 0

        table.update_neighbor(node_id_2, {}, [])
        assert table.get_neighbor_count() == 1

        table.update_neighbor(node_id_3, {}, [])
        assert table.get_neighbor_count() == 2


class TestNeighborTableValidation:
    """Tests for input validation and error handling."""

    def test_requires_simulation_time_initialized(self):
        """Operations should fail if simulation time not set."""
        node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        ctx = MVCCPContext(node)
        # Intentionally NOT calling ctx.update_time()
        ctx.current_time = None  # Force None

        table = NeighborTable(ctx)

        with pytest.raises(RuntimeError, match="current_time is None"):
            table.update_neighbor(b'\x00\x00\x00\x00\x00\x02', {}, [])

    def test_invalid_node_id_raises(self, context):
        """None node_id should raise ValueError."""
        table = NeighborTable(context)
        context.neighbor_table = table

        with pytest.raises(ValueError, match="node_id cannot be None"):
            table.update_neighbor(None, {}, [])

    def test_invalid_node_id_type_raises(self, context):
        """Non-bytes node_id should raise TypeError."""
        table = NeighborTable(context)
        context.neighbor_table = table

        with pytest.raises(TypeError, match="node_id must be bytes"):
            table.update_neighbor("not_bytes", {}, [])

    def test_invalid_attrs_filtered(self, context, node_id_2):
        """Attributes not in whitelist should be filtered."""
        table = NeighborTable(context)
        context.neighbor_table = table

        # Include both valid and invalid attributes
        attrs = {
            'battery_energy_kwh': 50.0,  # Valid
            'unknown_field': 'should_be_ignored',  # Invalid - not in whitelist
            '__private': 'dangerous',  # Invalid
        }

        # Should not raise, just filter
        table.update_neighbor(node_id_2, attrs, [])

        # Verify neighbor was added
        assert node_id_2 in table.get_one_hop_set()

    def test_two_hop_list_validates_bytes(self, context, node_id_2):
        """Two-hop list should filter non-bytes entries."""
        table = NeighborTable(context)
        context.neighbor_table = table

        valid_two_hop = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        # Include invalid entries in two-hop list
        two_hop_list = [
            valid_two_hop,  # Valid
            "not_bytes",    # Invalid - string
            None,           # Invalid - None
            123,            # Invalid - int
        ]

        # Should not raise, just filter
        table.update_neighbor(node_id_2, {}, two_hop_list)

        # Only valid entry should be in 2-hop set
        two_hop = table.get_two_hop_set()
        assert valid_two_hop in two_hop


class TestNeighborTableContext:
    """Tests for context requirements."""

    def test_context_cannot_be_none(self):
        """NeighborTable requires a context."""
        with pytest.raises(ValueError, match="context cannot be None"):
            NeighborTable(None)
