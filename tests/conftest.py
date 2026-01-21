"""
Shared pytest fixtures for MVCCP protocol tests.
"""
import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def node_id_1():
    """First test node ID."""
    return b'\x00\x00\x00\x00\x00\x01'


@pytest.fixture
def node_id_2():
    """Second test node ID."""
    return b'\x00\x00\x00\x00\x00\x02'


@pytest.fixture
def node_id_3():
    """Third test node ID."""
    return b'\x00\x00\x00\x00\x00\x03'


@pytest.fixture
def mock_node(node_id_1):
    """Create a mock node for testing."""
    from src.core.node import Node
    node = Node(
        node_id=node_id_1,
        battery_capacity_kwh=100.0,
        battery_energy_kwh=50.0,
        min_energy_kwh=10.0,
        latitude=0.0,
        longitude=0.0,
        velocity=0.0,
        willingness=5,
    )
    return node


@pytest.fixture
def mock_node_high_energy(node_id_2):
    """Create a node with high energy (can be platoon head)."""
    from src.core.node import Node
    node = Node(
        node_id=node_id_2,
        battery_capacity_kwh=100.0,
        battery_energy_kwh=80.0,
        min_energy_kwh=10.0,
        latitude=0.0,
        longitude=0.0,
        velocity=0.0,
        willingness=6,
        destination=(10.0, 10.0),  # Close destination
    )
    return node


@pytest.fixture
def mock_node_low_energy(node_id_3):
    """Create a node with low energy (needs charging)."""
    from src.core.node import Node
    node = Node(
        node_id=node_id_3,
        battery_capacity_kwh=100.0,
        battery_energy_kwh=15.0,
        min_energy_kwh=10.0,
        latitude=0.0,
        longitude=0.0,
        velocity=0.0,
        willingness=3,
        destination=(100.0, 100.0),  # Far destination
    )
    return node


@pytest.fixture
def context(mock_node):
    """Create MVCCPContext with mock node."""
    from src.protocol.context import MVCCPContext
    ctx = MVCCPContext(mock_node)
    ctx.update_time(0.0)
    return ctx


@pytest.fixture
def context_high_energy(mock_node_high_energy):
    """Create MVCCPContext with high energy node."""
    from src.protocol.context import MVCCPContext
    ctx = MVCCPContext(mock_node_high_energy)
    ctx.update_time(0.0)
    return ctx


@pytest.fixture
def context_low_energy(mock_node_low_energy):
    """Create MVCCPContext with low energy node."""
    from src.protocol.context import MVCCPContext
    ctx = MVCCPContext(mock_node_low_energy)
    ctx.update_time(0.0)
    return ctx


@pytest.fixture
def rreh_context(node_id_1):
    """Create MVCCPContext for an RREH."""
    from src.core.node import Node
    from src.protocol.context import MVCCPContext

    node = Node(
        node_id=node_id_1,
        battery_capacity_kwh=1000.0,  # Large capacity for RREH
        battery_energy_kwh=1000.0,
        min_energy_kwh=0.0,
        latitude=5.0,
        longitude=5.0,
    )
    ctx = MVCCPContext(node, is_rreh=True)
    ctx.update_time(0.0)
    return ctx


@pytest.fixture
def neighbor_table(context):
    """Create NeighborTable for testing."""
    from src.protocol.layer_a.neighbor_table import NeighborTable
    table = NeighborTable(context)
    context.neighbor_table = table
    return table


@pytest.fixture
def provider_table(context):
    """Create ProviderTable for testing."""
    from src.protocol.layer_b.provider_table import ProviderTable
    table = ProviderTable(context)
    context.provider_table = table
    return table


@pytest.fixture
def consumer_handler(context, neighbor_table, provider_table):
    """Create ConsumerHandler for testing."""
    from src.protocol.layer_c import ConsumerHandler
    from src.protocol.layer_c.states import NodeRole, ConsumerState

    context.node_role = NodeRole.CONSUMER
    context.consumer_state = ConsumerState.DISCOVER
    handler = ConsumerHandler(context)
    return handler


@pytest.fixture
def platoon_head_handler(context_high_energy):
    """Create PlatoonHeadHandler for testing."""
    from src.protocol.layer_c import PlatoonHeadHandler
    from src.protocol.layer_c.states import NodeRole, PlatoonHeadState
    from src.protocol.layer_a.neighbor_table import NeighborTable
    from src.protocol.layer_b.provider_table import ProviderTable

    context = context_high_energy
    context.neighbor_table = NeighborTable(context)
    context.provider_table = ProviderTable(context)
    context.node_role = NodeRole.PLATOON_HEAD
    context.platoon_head_state = PlatoonHeadState.BEACON
    handler = PlatoonHeadHandler(context)
    return handler


@pytest.fixture
def rreh_handler(rreh_context):
    """Create RREHHandler for testing."""
    from src.protocol.layer_c import RREHHandler
    from src.protocol.layer_c.states import RREHState
    from src.protocol.layer_a.neighbor_table import NeighborTable
    from src.protocol.layer_b.provider_table import ProviderTable

    rreh_context.neighbor_table = NeighborTable(rreh_context)
    rreh_context.provider_table = ProviderTable(rreh_context)
    rreh_context.rreh_state = RREHState.GRID_ANNOUNCE
    handler = RREHHandler(rreh_context)
    return handler


@pytest.fixture
def message_bus():
    """Create a message bus for handler-to-handler testing."""
    class MessageBus:
        def __init__(self):
            self.messages = []

        def send(self, data: bytes):
            self.messages.append(data)

        def pop(self):
            return self.messages.pop(0) if self.messages else None

        def peek(self):
            return self.messages[0] if self.messages else None

        def clear(self):
            self.messages.clear()

        def __len__(self):
            return len(self.messages)

    return MessageBus()


@pytest.fixture
def connected_handlers(context, context_high_energy, message_bus):
    """
    Create a consumer and platoon head that can communicate via message bus.
    Returns (consumer_handler, ph_handler, message_bus).
    """
    from src.protocol.layer_c import ConsumerHandler, PlatoonHeadHandler
    from src.protocol.layer_c.states import NodeRole, ConsumerState, PlatoonHeadState
    from src.protocol.layer_a.neighbor_table import NeighborTable
    from src.protocol.layer_b.provider_table import ProviderTable

    # Set up consumer context
    consumer_ctx = context
    consumer_ctx.neighbor_table = NeighborTable(consumer_ctx)
    consumer_ctx.provider_table = ProviderTable(consumer_ctx)
    consumer_ctx.node_role = NodeRole.CONSUMER
    consumer_ctx.consumer_state = ConsumerState.DISCOVER
    consumer_ctx.send_callback = message_bus.send

    # Set up platoon head context
    ph_ctx = context_high_energy
    ph_ctx.neighbor_table = NeighborTable(ph_ctx)
    ph_ctx.provider_table = ProviderTable(ph_ctx)
    ph_ctx.node_role = NodeRole.PLATOON_HEAD
    ph_ctx.platoon_head_state = PlatoonHeadState.BEACON
    ph_ctx.send_callback = message_bus.send

    consumer = ConsumerHandler(consumer_ctx)
    ph = PlatoonHeadHandler(ph_ctx)

    return consumer, ph, message_bus
