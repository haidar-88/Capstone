"""
Tests for ProviderTable - Layer B provider announcement handling.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.protocol.layer_b.provider_table import ProviderTable, ProviderType
from src.protocol.context import MVCCPContext
from src.protocol.config import ProtocolConfig
from src.core.node import Node


class TestProviderTableBasics:
    """Tests for basic provider table operations."""

    def test_add_provider_creates_entry(self, context):
        """Adding a provider should create an entry."""
        table = ProviderTable(context)

        provider_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })

        providers = table.get_all_providers()
        provider_ids = [p.provider_id for p in providers]
        assert provider_id in provider_ids

    def test_update_provider_refreshes_timestamp(self, context):
        """Updating provider should refresh its timestamp."""
        table = ProviderTable(context)

        provider_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        # Add at t=0
        context.update_time(0.0)
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })

        # Update at t=5
        context.update_time(5.0)
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (15.0, 25.0),
            'energy': 60.0,
        })

        # Provider should still exist (not stale)
        providers = table.get_all_providers()
        provider_ids = [p.provider_id for p in providers]
        assert provider_id in provider_ids

        # Check updated energy
        provider = table.get_provider(provider_id)
        assert provider is not None
        assert provider.energy_available == 60.0


class TestProviderTablePruning:
    """Tests for provider pruning."""

    def test_prune_stale_providers(self, context):
        """Providers not refreshed should be pruned automatically."""
        table = ProviderTable(context)

        provider_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        # Add at t=0
        context.update_time(0.0)
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })

        # Advance time beyond timeout
        context.update_time(table.PROVIDER_TIMEOUT + 1.0)

        # Get providers triggers auto-prune
        providers = table.get_all_providers()
        provider_ids = [p.provider_id for p in providers]
        assert provider_id not in provider_ids


class TestProviderSelection:
    """Tests for provider selection and scoring."""

    def test_get_best_provider_by_energy(self, context):
        """get_best_provider should prefer higher energy providers."""
        table = ProviderTable(context)

        low_energy_id = b'\x00\x00\x00\x00\x00\x01'
        high_energy_id = b'\x00\x00\x00\x00\x00\x02'

        # Add low energy provider
        table.update_provider(low_energy_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 20.0,
            'available_slots': 3,
        })

        # Add high energy provider
        table.update_provider(high_energy_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 80.0,
            'available_slots': 3,
        })

        # Best provider should be the high energy one
        best = table.get_best_provider()

        # Should return provider with more energy
        assert best is not None
        assert best.provider_id == high_energy_id
        assert best.energy_available == 80.0


class TestDeduplication:
    """Tests for provider updates (implicit deduplication via update_provider)."""

    def test_update_same_provider_replaces_entry(self, context):
        """Updating same provider_id should replace the entry."""
        table = ProviderTable(context)

        provider_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'

        # First add
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })

        # Second add with same provider_id
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (15.0, 25.0),
            'energy': 70.0,  # Updated energy
        })

        # Should have only one entry with updated values
        providers = table.get_all_providers()
        assert len(providers) == 1
        assert providers[0].energy_available == 70.0
        assert providers[0].position == (15.0, 25.0)

    def test_multiple_providers_coexist(self, context):
        """Different provider_ids should create separate entries."""
        table = ProviderTable(context)

        provider_id_1 = b'\xAA\xBB\xCC\xDD\xEE\x01'
        provider_id_2 = b'\xAA\xBB\xCC\xDD\xEE\x02'

        # Add first provider
        table.update_provider(provider_id_1, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })

        # Add second provider with different ID
        table.update_provider(provider_id_2, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (15.0, 25.0),
            'energy': 60.0,
        })

        providers = table.get_all_providers()
        assert len(providers) == 2


class TestProviderTableThreadSafety:
    """Tests for thread-safety mechanisms."""

    def test_concurrent_read_access(self, context):
        """Multiple reads should not block each other."""
        table = ProviderTable(context)

        provider_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
            'available_slots': 3,
        })

        # Multiple reads should work
        providers1 = table.get_all_providers()
        providers2 = table.get_all_providers()
        best = table.get_best_provider()

        assert len(providers1) == len(providers2)
        assert best is not None


class TestProviderTableFiltering:
    """Tests for provider filtering."""

    def test_filter_by_type(self, context):
        """Should be able to filter providers by type."""
        table = ProviderTable(context)

        platoon_id = b'\x00\x00\x00\x00\x00\x01'
        rreh_id = b'\x00\x00\x00\x00\x00\x02'

        table.update_provider(platoon_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })

        table.update_provider(rreh_id, {
            'type': ProviderType.RREH,
            'position': (30.0, 40.0),
            'energy': 100.0,
            'operational_state': 'normal',
        })

        # Get all providers
        all_providers = table.get_all_providers()
        assert len(all_providers) == 2

        # Get only RREHs
        rrehs = table.get_rrehs()
        assert len(rrehs) == 1
        assert rrehs[0].provider_id == rreh_id

        # Get only platoon heads
        platoons = table.get_platoon_heads()
        assert len(platoons) == 1
        assert platoons[0].provider_id == platoon_id

    def test_get_providers_with_capacity(self, context):
        """Should filter providers that have capacity."""
        table = ProviderTable(context)

        has_capacity_id = b'\x00\x00\x00\x00\x00\x01'
        no_capacity_id = b'\x00\x00\x00\x00\x00\x02'

        # Provider with capacity
        table.update_provider(has_capacity_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
            'available_slots': 3,
        })

        # Provider without capacity
        table.update_provider(no_capacity_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (20.0, 30.0),
            'energy': 60.0,
            'available_slots': 0,
        })

        providers_with_capacity = table.get_providers_with_capacity()
        assert len(providers_with_capacity) == 1
        assert providers_with_capacity[0].provider_id == has_capacity_id


class TestProviderRemoval:
    """Tests for provider removal."""

    def test_remove_provider(self, context):
        """Should be able to remove a provider."""
        table = ProviderTable(context)

        provider_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        table.update_provider(provider_id, {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })

        # Verify added
        assert table.get_provider(provider_id) is not None

        # Remove
        result = table.remove_provider(provider_id)
        assert result is True

        # Verify removed
        assert table.get_provider(provider_id) is None

    def test_remove_nonexistent_provider(self, context):
        """Removing nonexistent provider should return False."""
        table = ProviderTable(context)

        provider_id = b'\xAA\xBB\xCC\xDD\xEE\xFF'
        result = table.remove_provider(provider_id)
        assert result is False

    def test_clear_all_providers(self, context):
        """Should be able to clear all providers."""
        table = ProviderTable(context)

        # Add multiple providers
        table.update_provider(b'\x00\x00\x00\x00\x00\x01', {
            'type': ProviderType.PLATOON_HEAD,
            'position': (10.0, 20.0),
            'energy': 50.0,
        })
        table.update_provider(b'\x00\x00\x00\x00\x00\x02', {
            'type': ProviderType.RREH,
            'position': (30.0, 40.0),
            'energy': 100.0,
        })

        assert len(table.get_all_providers()) == 2

        # Clear all
        table.clear()

        assert len(table.get_all_providers()) == 0
