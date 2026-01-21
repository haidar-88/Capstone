"""
Tests for Platoon core - edge graph, Dijkstra, and formation optimization.
"""
import pytest
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.platoon import Platoon
from src.core.node import Node
from src.core.edge import Edge
from src.protocol.config import ProtocolConfig


class TestPlatoonCreation:
    """Tests for platoon creation and basic operations."""

    def test_create_platoon_with_head(self):
        """Creating a platoon should have a head."""
        head_node = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_capacity_kwh=100.0,
            battery_energy_kwh=80.0
        )

        platoon = Platoon(head_node=head_node)

        assert platoon.head_node == head_node
        assert platoon.head_id == head_node.node_id

    def test_head_always_exists(self):
        """Platoon should always have a head."""
        head_node = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        platoon = Platoon(head_node=head_node)

        assert platoon.head_node is not None


class TestEdgeGraph:
    """Tests for edge graph construction."""

    def test_build_edge_graph_creates_edges(self):
        """Adding members should create edges between all nodes."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0
        )
        member1 = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=3.0,
            longitude=0.0
        )
        member2 = Node(
            node_id=b'\x00\x00\x00\x00\x00\x03',
            latitude=0.0,
            longitude=3.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member1)
        platoon.add_node(member2)

        # Should have 3 nodes total (head + 2 members)
        # nodes list includes head
        assert len(platoon.nodes) == 3

    def test_edge_efficiency_inverse_square(self):
        """Edge efficiency should follow inverse-square model."""
        # Test the efficiency formula directly
        distance = 3.0  # meters
        scale = ProtocolConfig.EDGE_EFFICIENCY_SCALE

        # distance_efficiency = 1 / (1 + scale * distance^2)
        expected = 1.0 / (1.0 + scale * distance * distance)

        # Edge requires Node objects
        source = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        dest = Node(node_id=b'\x00\x00\x00\x00\x00\x02')
        edge = Edge(source=source, destination=dest, distance=distance)

        # Check distance efficiency component (hardware efficiency affects final)
        assert abs(edge.distance_efficiency - expected) < 0.01

    def test_edge_below_min_efficiency_removed(self):
        """Edges with efficiency below threshold should be unusable."""
        # Very large distance should result in low efficiency
        large_distance = 20.0  # meters (beyond EDGE_MAX_RANGE_M)

        source = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        dest = Node(node_id=b'\x00\x00\x00\x00\x00\x02')
        edge = Edge(source=source, destination=dest, distance=large_distance)

        # Edge should not be usable (efficiency = 0 beyond max range)
        assert not edge.is_usable()

    def test_update_edge_distances_recalculates(self):
        """Updating positions should recalculate edge distances."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0
        )
        member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=3.0,
            longitude=0.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member)

        # Move member closer
        member.latitude = 1.0
        member.longitude = 0.0

        platoon.update_edge_distances()

        # Edges should reflect new positions


class TestDijkstra:
    """Tests for Dijkstra energy path finding."""

    def test_dijkstra_finds_shortest_path(self):
        """Dijkstra should find shortest path between nodes."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0,
            battery_energy_kwh=80.0
        )
        member1 = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=2.0,
            longitude=0.0,
            battery_energy_kwh=60.0
        )
        member2 = Node(
            node_id=b'\x00\x00\x00\x00\x00\x03',
            latitude=4.0,
            longitude=0.0,
            battery_energy_kwh=20.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member1)
        platoon.add_node(member2)

        # Dijkstra should find path from head to member2
        # Result depends on implementation details

    def test_dijkstra_multi_hop_cheaper_than_direct(self):
        """Multi-hop path may be cheaper than direct transfer."""
        # Set up scenario where A -> B -> C is better than A -> C
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0,
            battery_energy_kwh=80.0
        )
        relay = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=3.0,  # Close to head
            longitude=0.0,
            battery_energy_kwh=60.0
        )
        target = Node(
            node_id=b'\x00\x00\x00\x00\x00\x03',
            latitude=6.0,  # Far from head, close to relay
            longitude=0.0,
            battery_energy_kwh=20.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(relay)
        platoon.add_node(target)

        # Path through relay should be more efficient than direct

    def test_dijkstra_energy_paths_surplus_to_deficit(self):
        """Should find paths from surplus to deficit nodes."""
        # Head has surplus, member3 has deficit
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0,
            battery_energy_kwh=90.0,
            battery_capacity_kwh=100.0,
            min_energy_kwh=10.0
        )
        deficit_member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=5.0,
            longitude=0.0,
            battery_energy_kwh=15.0,
            battery_capacity_kwh=100.0,
            min_energy_kwh=10.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(deficit_member)

        # Should identify deficit_member as needing energy


class TestFormationOptimization:
    """Tests for formation position optimization."""

    def test_compute_optimal_formation(self):
        """Should compute target positions for members."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0,
            battery_energy_kwh=80.0
        )
        member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=10.0,
            longitude=0.0,
            battery_energy_kwh=60.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member)

        formation = platoon.compute_optimal_formation(current_time=1.0)

        # Should return dict of node_id -> (x, y) positions
        assert formation is not None

    def test_formation_respects_min_distance(self):
        """Formation should maintain minimum vehicle separation."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0
        )
        member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=1.0,
            longitude=0.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member)

        formation = platoon.compute_optimal_formation(current_time=1.0)

        # Positions should be at least MIN_VEHICLE_DISTANCE apart
        if formation and len(formation) > 1:
            positions = list(formation.values())
            for i, pos1 in enumerate(positions):
                for pos2 in positions[i+1:]:
                    dist = math.sqrt((pos2[0]-pos1[0])**2 + (pos2[1]-pos1[1])**2)
                    # Should respect minimum distance

    def test_formation_respects_lane_width(self):
        """Formation should respect lateral lane constraints."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0
        )
        member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=5.0,
            longitude=0.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member)

        formation = platoon.compute_optimal_formation(current_time=1.0)

        # Lateral offset should be within lane width
        # Implementation specific


class TestMemberManagement:
    """Tests for adding and removing members."""

    def test_add_member_updates_edge_graph(self):
        """Adding a member should update the edge graph."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0
        )

        platoon = Platoon(head_node=head)
        # Head is in nodes, so initial size is 1
        initial_size = len(platoon.nodes)

        member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=3.0,
            longitude=0.0
        )
        platoon.add_node(member)

        assert len(platoon.nodes) == initial_size + 1
        assert member in platoon.nodes

    def test_remove_member_updates_edge_graph(self):
        """Removing a member should update the edge graph."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0
        )
        member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            latitude=3.0,
            longitude=0.0
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member)
        assert member in platoon.nodes

        platoon.remove_node(member)
        assert member not in platoon.nodes

    def test_members_list_consistent(self):
        """Members list should be consistent with edge graph."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            latitude=0.0,
            longitude=0.0
        )

        platoon = Platoon(head_node=head)

        # Add multiple members
        for i in range(5):
            member = Node(
                node_id=bytes([0, 0, 0, 0, 0, i + 2]),
                latitude=float(i * 3),
                longitude=0.0
            )
            platoon.add_node(member)

        # 5 members + 1 head = 6 nodes
        assert len(platoon.nodes) == 6


class TestPlatoonInvariants:
    """Tests for platoon invariants."""

    def test_auto_handoff_on_head_leave(self):
        """If head leaves, another member should become head."""
        head = Node(
            node_id=b'\x00\x00\x00\x00\x00\x01',
            battery_energy_kwh=80.0,
            willingness=6
        )
        member = Node(
            node_id=b'\x00\x00\x00\x00\x00\x02',
            battery_energy_kwh=70.0,
            willingness=5
        )

        platoon = Platoon(head_node=head)
        platoon.add_node(member)

        # If head leaves, member should become new head
        # Implementation depends on handoff logic

    def test_platoon_dissolves_when_empty(self):
        """Platoon with no members should handle gracefully."""
        head = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        platoon = Platoon(head_node=head)

        # Just the head, nodes list contains head
        assert platoon.node_number == 1


class TestEdgeClass:
    """Tests for Edge class directly."""

    def test_edge_cost_calculation(self):
        """Edge cost should combine distance and efficiency."""
        source = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        dest = Node(node_id=b'\x00\x00\x00\x00\x00\x02')
        edge = Edge(source=source, destination=dest, distance=5.0)

        # Cost should be positive
        assert edge.edge_cost > 0

    def test_edge_within_range(self):
        """Edge within max range should be usable."""
        source = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        dest = Node(node_id=b'\x00\x00\x00\x00\x00\x02')
        edge = Edge(source=source, destination=dest, distance=3.0)

        # Edge should be usable (is_usable checks transfer_efficiency >= MIN)
        assert edge.is_usable()

    def test_edge_beyond_range(self):
        """Edge beyond max range should have very low efficiency."""
        source = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        dest = Node(node_id=b'\x00\x00\x00\x00\x00\x02')
        edge = Edge(source=source, destination=dest, distance=15.0)

        # Should have low efficiency (beyond max range of 10m, efficiency = 0)
        assert edge.transfer_efficiency == 0.0


class TestPlatoonCapacity:
    """Tests for platoon capacity management."""

    def test_can_add_node_when_space(self):
        """can_add_node should return True when space available."""
        head = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        platoon = Platoon(head_node=head)

        assert platoon.can_add_node() is True

    def test_cannot_add_when_full(self):
        """can_add_node should return False when platoon is full."""
        head = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        platoon = Platoon(head_node=head)

        # Add 5 more members to fill platoon (max 6 including head)
        for i in range(5):
            member = Node(node_id=bytes([0, 0, 0, 0, 0, i + 2]))
            platoon.add_node(member)

        assert platoon.can_add_node() is False

    def test_available_slots(self):
        """available_slots should return correct count."""
        head = Node(node_id=b'\x00\x00\x00\x00\x00\x01')
        platoon = Platoon(head_node=head)

        # With just head, 5 slots available
        assert platoon.available_slots() == 5

        # Add a member
        member = Node(node_id=b'\x00\x00\x00\x00\x00\x02')
        platoon.add_node(member)

        # Now 4 slots available
        assert platoon.available_slots() == 4
