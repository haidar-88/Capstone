from typing import Optional, Set, List
import math

from src.protocol.config import ProtocolConfig, TTLMode
from src.protocol.layer_c.states import (
    NodeRole, ConsumerState, PlatoonHeadState, RREHState
)
from src.protocol.metrics import NodeMetrics



class MVCCPContext:
    """
    Shared context for MVCCP protocol handlers.
    Contains node state, protocol tables, and configuration.
    """
    
    def __init__(self, node, is_rreh: bool = False):
        """
        Initialize protocol context.
        
        Args:
            node: The physical Node object this context represents
            is_rreh: True if this node is an RREH (stationary, predetermined)
        """
        self.node = node  # The physical Node object
        
        # Identity
        self.node_id = node.node_id
        
        # Configuration (from ProtocolConfig)
        self.hello_interval = ProtocolConfig.HELLO_INTERVAL
        self.pa_interval = ProtocolConfig.PA_INTERVAL
        self.beacon_interval = ProtocolConfig.BEACON_INTERVAL
        self.grid_status_interval = ProtocolConfig.GRID_STATUS_INTERVAL

        # TTL Configuration (Section 7.6)
        self.ttl_mode = ProtocolConfig.PA_TTL_MODE
        self.base_ttl = ProtocolConfig.PA_TTL_DEFAULT

        # For adaptive mode tracking
        self.pa_receive_count = 0         # PA messages received this interval
        self.pa_receive_window_start = 0.0
        
        # Network Interface Callback
        # This function should be set by the Network Interface (e.g. ns3 adapter)
        # Signature: callback(data: bytes)
        self.send_callback = None
        
        # Timing State
        self.last_hello_time = 0.0
        self.last_pa_time = 0.0
        self.last_beacon_time = 0.0
        self.last_grid_status_time = 0.0
        
        # Layer 1 Data (Neighbor Discovery)
        self.neighbor_table = None  # Initialized in Layer 1 handler
        self.mpr_set: Set = set()   # Set of neighbor IDs selected as MPRs
        self.mpr_selector_set: Set = set()  # Set of neighbors that selected ME as MPR
        
        # Layer 2 Data (Provider Announcement)
        self.provider_table = None  # Initialized in Layer 2 handler
        
        # --- Layer 3 Data (Charging Coordination) ---
        
        # Node Role (dynamic for EVs, static for RREHs)
        if is_rreh:
            self.node_role = NodeRole.RREH
        else:
            self.node_role = NodeRole.CONSUMER  # Default, will be evaluated dynamically
        
        # State machines for each role (only one active at a time based on node_role)
        self.consumer_state: Optional[ConsumerState] = None
        self.platoon_head_state: Optional[PlatoonHeadState] = None
        self.rreh_state: Optional[RREHState] = None
        
        # Platoon membership
        self.current_platoon = None  # Platoon instance if member/head
        self.current_platoon_id: Optional[bytes] = None
        
        # If this node is a PlatoonHead, list of member node IDs
        self.platoon_members: List[bytes] = []
        
        # Selected provider for current session (when acting as consumer)
        self.selected_provider = None
        self.selected_provider_type = None  # 'RREH' or 'PLATOON'
        
        # Session tracking
        self.pending_offers: List[dict] = []  # For PH: incoming join offers to evaluate
        self.current_session: dict = {}       # Active charging session info
        
        # Metrics (A6: Observability)
        self.metrics = NodeMetrics()
        
        # --- RREH-specific fields ---
        if is_rreh:
            self.rreh_queue: List[bytes] = []  # Queue of consumer IDs waiting
            self.rreh_max_sessions = 4         # Max simultaneous sessions
            self.rreh_active_sessions = 0      # Current active sessions
            self.rreh_available_power = 150.0  # kW available
            self.rreh_renewable_fraction = 1.0 # 100% renewable by default
            self.rreh_operational_state = 'normal'  # normal, congested, limited, offline
        
        # Time Management (simulation-time only, initialized to 0.0)
        self.current_time = 0.0
    
    def update_time(self, timestamp: float):
        """
        Update the current simulation time.
        
        Args:
            timestamp: New simulation time in seconds
            
        Raises:
            ValueError: If timestamp goes backward (non-monotonic time)
        """
        if timestamp < self.current_time:
            raise ValueError(
                f"Time cannot go backward: current={self.current_time}, new={timestamp}"
            )
        self.current_time = timestamp
    
    def set_role(self, role: NodeRole):
        """
        Change the node's role and initialize appropriate state machine.
        
        Args:
            role: New NodeRole to assign
        """
        if role == self.node_role:
            return  # No change
        
        old_role = self.node_role
        self.node_role = role
        
        # Initialize state machine for new role
        if role == NodeRole.CONSUMER:
            self.consumer_state = ConsumerState.DISCOVER
            self.platoon_head_state = None
        elif role == NodeRole.PLATOON_HEAD:
            self.platoon_head_state = PlatoonHeadState.BEACON
            self.consumer_state = None
        elif role == NodeRole.PLATOON_MEMBER:
            # Member doesn't run its own state machine for charging
            # but tracks consumer state for receiving charge
            self.consumer_state = ConsumerState.ALLOCATED
            self.platoon_head_state = None
        elif role == NodeRole.RREH:
            self.rreh_state = RREHState.GRID_ANNOUNCE
            self.consumer_state = None
            self.platoon_head_state = None
    
    def is_consumer(self) -> bool:
        """Check if node is acting as a consumer."""
        return self.node_role == NodeRole.CONSUMER
    
    def is_platoon_head(self) -> bool:
        """Check if node is acting as a platoon head."""
        return self.node_role == NodeRole.PLATOON_HEAD
    
    def is_rreh(self) -> bool:
        """Check if node is an RREH."""
        return self.node_role == NodeRole.RREH
    
    def is_platoon_member(self) -> bool:
        """Check if node is a platoon member (not head)."""
        return self.node_role == NodeRole.PLATOON_MEMBER
    
    def get_destination(self) -> Optional[tuple]:
        """Get the node's destination coordinates."""
        return self.node.destination
    
    def set_destination(self, destination: tuple):
        """Set the node's destination coordinates."""
        self.node.destination = destination
    
    def can_become_platoon_head(self) -> bool:
        """
        Check if this node meets the criteria to become a platoon head.
        Uses thresholds from ProtocolConfig.
        """
        if self.is_rreh():
            return False  # RREHs don't become platoon heads
        
        if self.current_platoon is not None and not self.is_platoon_head():
            return False  # Already in a platoon as member
        
        shareable = self.node.shareable_energy()
        threshold = ProtocolConfig.PH_ENERGY_THRESHOLD_PERCENT * self.node.battery_capacity_kwh
        
        return shareable >= threshold and self.node.willingness >= ProtocolConfig.PH_WILLINGNESS_THRESHOLD
    
    def needs_charge(self) -> bool:
        """
        Check if this node needs charging.
        Returns True if shareable_energy is negative (can't reach destination).
        """
        return self.node.shareable_energy() < 0

    def get_effective_ttl(self) -> int:
        """
        Calculate effective TTL based on mode.

        Returns:
            TTL value to use for outgoing PA messages.
        """
        if self.ttl_mode == TTLMode.FIXED:
            return self.base_ttl

        elif self.ttl_mode == TTLMode.DENSITY_BASED:
            # TTL = max(2, min(6, 8 - log2(neighbor_count)))
            neighbor_count = 1
            if self.neighbor_table is not None:
                neighbor_count = self.neighbor_table.get_neighbor_count()
            neighbor_count = max(1, neighbor_count)  # Avoid log(0)
            ttl = 8 - math.log2(neighbor_count)
            return max(ProtocolConfig.PA_TTL_MIN,
                       min(ProtocolConfig.PA_TTL_MAX, int(ttl)))

        return self.base_ttl  # Fallback
    
    def get_metrics_summary(self) -> dict:
        """
        Get a summary of all protocol metrics (A6).
        
        Returns:
            Dictionary containing metrics summary
        """
        return self.metrics.get_summary()