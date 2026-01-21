import math
from enum import Enum


class TTLMode(Enum):
    """TTL calculation mode for PA message dissemination."""
    FIXED = "fixed"           # Static TTL value
    DENSITY_BASED = "density" # Adjust based on neighbor count


class ProtocolConfig:
    # Timeouts
    NEIGHBOR_TIMEOUT = 5.0  # seconds
    PRUNE_INTERVAL = 1.0    # seconds - rate limit for stale cleanup
    
    # Protocol Message Intervals (Section 5)
    HELLO_INTERVAL = 1.0          # seconds - Layer A neighbor discovery
    PA_INTERVAL = 5.0             # seconds - Layer B provider announcement  
    BEACON_INTERVAL = 2.0         # seconds - Layer D platoon beacons
    GRID_STATUS_INTERVAL = 10.0   # seconds - Layer B RREH status updates

    # Node Attributes Keys
    ATTR_BATTERY_CAPACITY_KWH = 'battery_capacity_kwh'
    ATTR_BATTERY_ENERGY_KWH = 'battery_energy_kwh'
    ATTR_MIN_ENERGY_KWH = 'min_energy_kwh'
    ATTR_MAX_TRANSFER_RATE_IN = 'max_transfer_rate_in'
    ATTR_MAX_TRANSFER_RATE_OUT = 'max_transfer_rate_out'
    ATTR_LATITUDE = 'latitude'
    ATTR_LONGITUDE = 'longitude'
    ATTR_VELOCITY = 'velocity'
    ATTR_BATTERY_HEALTH = 'battery_health'
    
    # QoS Attributes Keys (Section 7.4)
    ATTR_ETX = 'etx'
    ATTR_DELAY = 'delay'  # Transmission delay in ms
    ATTR_WILLINGNESS = 'willingness'
    ATTR_LANE_WEIGHT = 'lane_weight'
    ATTR_LINK_STABILITY = 'link_stability'

    # Allowed attributes for Node updates (Whitelist)
    ALLOWED_NODE_ATTRS = {
        ATTR_BATTERY_CAPACITY_KWH, ATTR_BATTERY_ENERGY_KWH, ATTR_MIN_ENERGY_KWH,
        ATTR_MAX_TRANSFER_RATE_IN, ATTR_MAX_TRANSFER_RATE_OUT,
        ATTR_LATITUDE, ATTR_LONGITUDE, ATTR_VELOCITY, ATTR_BATTERY_HEALTH,
        ATTR_ETX, ATTR_DELAY, ATTR_WILLINGNESS, ATTR_LANE_WEIGHT, ATTR_LINK_STABILITY
    }
    
    # Type validation mapping: attribute -> allowed types
    ATTR_TYPES = {
        ATTR_BATTERY_CAPACITY_KWH: (int, float),
        ATTR_BATTERY_ENERGY_KWH: (int, float),
        ATTR_MIN_ENERGY_KWH: (int, float),
        ATTR_MAX_TRANSFER_RATE_IN: (int, float),
        ATTR_MAX_TRANSFER_RATE_OUT: (int, float),
        ATTR_LATITUDE: (int, float),
        ATTR_LONGITUDE: (int, float),
        ATTR_VELOCITY: (int, float, tuple),  # Can be scalar or (vx, vy)
        ATTR_BATTERY_HEALTH: (int, float),
        ATTR_ETX: (int, float),
        ATTR_DELAY: (int, float),  # Delay in ms
        ATTR_WILLINGNESS: (int,),
        ATTR_LANE_WEIGHT: (int, float),
        ATTR_LINK_STABILITY: (int, float),
    }
    
    # Range validation mapping: attribute -> (min, max) where None means unbounded
    ATTR_RANGES = {
        ATTR_BATTERY_CAPACITY_KWH: (0.1, None),  # Must be positive
        ATTR_BATTERY_ENERGY_KWH: (0, None),  # 0 to capacity (checked dynamically)
        ATTR_MIN_ENERGY_KWH: (0, None),  # Must be non-negative
        ATTR_MAX_TRANSFER_RATE_IN: (0, None),  # Must be non-negative
        ATTR_MAX_TRANSFER_RATE_OUT: (0, None),  # Must be non-negative
        ATTR_ETX: (1.0, None),  # ETX >= 1.0 (perfect link)
        ATTR_DELAY: (0, None),  # Delay >= 0
        ATTR_WILLINGNESS: (0, 7),  # OLSR spec: 0-7
        ATTR_LANE_WEIGHT: (0.0, 1.0),  # Normalized 0-1
        ATTR_LINK_STABILITY: (0.0, 1.0),  # Normalized 0-1
        ATTR_BATTERY_HEALTH: (0.0, 1.0),  # Normalized 0-1
    }
    
    # Default values for required Node fields (prevents TypeError)
    NODE_DEFAULTS = {
        ATTR_BATTERY_CAPACITY_KWH: 100.0,
        ATTR_BATTERY_ENERGY_KWH: 50.0,
        ATTR_MIN_ENERGY_KWH: 10.0,
        ATTR_MAX_TRANSFER_RATE_IN: 50.0,
        ATTR_MAX_TRANSFER_RATE_OUT: 50.0,
        ATTR_LATITUDE: 0.0,
        ATTR_LONGITUDE: 0.0,
        ATTR_VELOCITY: 0.0,
        ATTR_BATTERY_HEALTH: 1.0,
        ATTR_ETX: 1.0,
        ATTR_DELAY: 0.0,  # Default 0ms delay
        ATTR_WILLINGNESS: 3,
        ATTR_LANE_WEIGHT: 0.5,
        ATTR_LINK_STABILITY: 1.0,
    }
    
    # OLSR QoS Weights (Section 7.4)
    # Must sum to 1.0
    OLSR_WEIGHTS = {
        'battery': 0.20,
        'etx': 0.20,
        'delay': 0.15,       # Transmission delay/jitter
        'mobility': 0.15,
        'willingness': 0.10,
        'congestion': 0.10,
        'stability': 0.10
    }
    
    # ==========================================================================
    # Protocol Constants (from Protocol Definition.md)
    # ==========================================================================
    
    # Node ID size (Section 10.1: sender_id 48 bits = 6 bytes)
    NODE_ID_SIZE = 6
    
    # TLV limits (Section 10.2)
    TLV_MAX_VALUE_SIZE = 255
    
    # Platoon limits (Section 5.6)
    PLATOON_MAX_SIZE = 6
    
    # PA TTL Configuration (Section 7.6)
    PA_TTL_DEFAULT = 4          # Default hops
    PA_TTL_MIN = 2              # Minimum TTL (dense areas)
    PA_TTL_MAX = 6              # Maximum TTL (sparse areas)
    PA_TTL_MODE = TTLMode.FIXED # Default mode
    
    # Provider Types (Section 5.2)
    PROVIDER_TYPE_MP = 0      # Mobile Provider
    PROVIDER_TYPE_PH = 1      # Platoon Head
    PROVIDER_TYPE_RREH = 2    # Roadside Renewable Energy Hub
    
    # Link Status (OLSR spec for neighbor discovery)
    LINK_STATUS_LOST = 0
    LINK_STATUS_ASYM = 1
    LINK_STATUS_SYM = 2
    
    # Operational States (Section 5.8: GRID_STATUS operational_state)
    OP_STATE_NORMAL = "normal"
    OP_STATE_CONGESTED = "congested"
    OP_STATE_LIMITED = "limited"
    OP_STATE_OFFLINE = "offline"
    
    # Timeouts (Section 11: Error Handling)
    JOIN_ACCEPT_TIMEOUT = 5.0  # seconds - consumer waiting for JOIN_ACCEPT
    ACK_TIMEOUT = 3.0          # seconds - provider waiting for ACK
    ACKACK_TIMEOUT = 3.0       # seconds - consumer waiting for ACKACK
    
    # Provider Table timeout (Section 6)
    PROVIDER_TIMEOUT = 10.0    # seconds - stale provider entry removal
    
    # Retry and Backoff Constants (P2: Retry Upgrade)
    RETRY_BASE_DELAY = 1.0     # seconds - base delay for exponential backoff
    RETRY_MAX_JITTER = 0.5     # seconds - ±0.5s randomization for backoff
    RETRY_MAX_RETRIES = 3      # maximum retry attempts before blacklist
    BLACKLIST_DURATION = 30.0  # seconds - provider blacklist duration (per-session)
    
    # P5: Dynamic Provider Selection (Urgency-Based Thresholds)
    URGENCY_CRITICAL = 1.0     # distance_to_empty / distance_to_dest ratio
    URGENCY_LOW = 1.2          # threshold for low battery state
    THRESHOLD_CRITICAL = 1.0   # Accept any detour when critical (100%)
    THRESHOLD_LOW = 0.50       # Accept 50% detour when low battery
    THRESHOLD_HEALTHY = 0.20   # Accept 20% detour when healthy (default)
    
    # P7: RREH Queue Time Model
    RREH_AVG_SESSION_DURATION = 1800.0  # seconds (30 minutes) - avg charging session
    QUEUE_TIME_WEIGHT = 0.01            # kWh/s - energy penalty per second of wait
    MAX_ACCEPTABLE_QUEUE_TIME = 3600.0  # seconds (1 hour) - max acceptable wait
    
    # Beacon intervals
    PLATOON_BEACON_INTERVAL = 1.0  # seconds
    
    # Edge cost weights (for Dijkstra/routing)
    # Note: EDGE_WEIGHT_ENERGY_LOSS also covers efficiency (avoids double-counting)
    EDGE_WEIGHT_DISTANCE = 0.4
    EDGE_WEIGHT_ENERGY_LOSS = 0.3  # Used for both energy_loss and (1-efficiency)
    EDGE_WEIGHT_TIME = 0.3
    
    # ==========================================================================
    # Wireless Charging Edge Model (Intra-Platoon)
    # ==========================================================================
    
    # Inverse-square efficiency: efficiency = 1 / (1 + EDGE_EFFICIENCY_SCALE * distance²)
    EDGE_EFFICIENCY_SCALE = 0.1    # Scaling factor for distance² term
    EDGE_MAX_RANGE_M = 10.0        # Max effective wireless charging range (meters)
    EDGE_MIN_EFFICIENCY = 0.1     # Below this, edge is considered unusable
    
    # Formation optimization
    FORMATION_UPDATE_INTERVAL = 2.0  # Seconds between formation recomputation
    
    # ==========================================================================
    # Inter-Platoon Discovery Constants
    # ==========================================================================
    
    # Timing for PLATOON_ANNOUNCE broadcasts
    PLATOON_ANNOUNCE_INTERVAL = 5.0    # Seconds between announcements (slower than beacons)
    PLATOON_ANNOUNCE_TTL = 3           # Hop limit for forwarding
    PLATOON_ENTRY_TIMEOUT = 15.0       # Seconds before pruning stale entries
    
    # Virtual edge scoring weights for platoon selection (must sum to 1.0)
    PLATOON_SCORE_DIRECTION = 0.4     # Weight for direction match
    PLATOON_SCORE_DISTANCE = 0.3      # Weight for distance (inverse)
    PLATOON_SCORE_ENERGY = 0.3        # Weight for energy availability
    
    # ==========================================================================
    # Energy Model Constants
    # ==========================================================================
    
    # Energy consumption rate (kWh per km traveled)
    # Typical EV efficiency for highway driving
    ENERGY_CONSUMPTION_RATE = 0.15  # kWh/km
    
    # Geographic conversion constant (km per degree latitude)
    # At equator: 1 degree latitude ≈ 111 km
    # Used for approximate distance calculations
    KM_PER_DEGREE = 111.0
    
    # Numerical epsilon for float comparisons
    # Used to avoid division by zero and handle floating point precision
    FLOAT_EPSILON = 1e-9
    
    # ==========================================================================
    # Role Management Constants
    # ==========================================================================
    
    # Platoon Head eligibility thresholds
    PH_ENERGY_THRESHOLD_PERCENT = 0.60  # 60% of battery capacity as shareable
    PH_WILLINGNESS_THRESHOLD = 4        # Minimum willingness (0-7 scale)
    
    # Consumer threshold (negative shareable energy = needs charge)
    CONSUMER_CRITICAL_ENERGY = 0.0  # Below this shareable energy → consumer
    
    # ==========================================================================
    # Security/DoS Protection Constants
    # ==========================================================================
    
    # Maximum sequence number (reject obviously bogus values)
    MAX_SEQUENCE_NUMBER = 2**31 - 1
    
    # Maximum entries in seen_messages cache (prevents memory exhaustion)
    MAX_SEEN_MESSAGES = 10000
    
    # Platoon member timeout (seconds) - remove stale members
    PLATOON_MEMBER_TIMEOUT = 10.0
    
    # ==========================================================================
    # QoS Normalization Bounds
    # ==========================================================================
    
    # Maximum acceptable delay in ms (for delay score normalization)
    MAX_ACCEPTABLE_DELAY_MS = 100.0


def validate_config():
    """Validate configuration at module load time."""
    # Validate OLSR weights sum to 1.0
    total = sum(ProtocolConfig.OLSR_WEIGHTS.values())
    if not math.isclose(total, 1.0, abs_tol=1e-5):
        raise ValueError(
            f"OLSR_WEIGHTS must sum to 1.0, got {total}. "
            f"Weights: {ProtocolConfig.OLSR_WEIGHTS}"
        )
    
    # Check for zero weights (would cause division by zero)
    for key, val in ProtocolConfig.OLSR_WEIGHTS.items():
        if val <= 0:
            raise ValueError(f"OLSR_WEIGHTS[{key}] must be positive, got {val}")
    
    # Validate energy constants
    if ProtocolConfig.ENERGY_CONSUMPTION_RATE <= 0:
        raise ValueError("ENERGY_CONSUMPTION_RATE must be positive")
    
    if ProtocolConfig.KM_PER_DEGREE <= 0:
        raise ValueError("KM_PER_DEGREE must be positive")
    
    # Validate role thresholds
    if not (0.0 <= ProtocolConfig.PH_ENERGY_THRESHOLD_PERCENT <= 1.0):
        raise ValueError("PH_ENERGY_THRESHOLD_PERCENT must be in [0, 1]")
    
    if not (0 <= ProtocolConfig.PH_WILLINGNESS_THRESHOLD <= 7):
        raise ValueError("PH_WILLINGNESS_THRESHOLD must be in [0, 7]")
    
    # Validate intervals are positive
    intervals = [
        ('PA_INTERVAL', ProtocolConfig.PA_INTERVAL),
        ('BEACON_INTERVAL', ProtocolConfig.BEACON_INTERVAL),
        ('GRID_STATUS_INTERVAL', ProtocolConfig.GRID_STATUS_INTERVAL),
    ]
    for name, interval in intervals:
        if interval <= 0:
            raise ValueError(f"{name} must be positive, got {interval}")


# Validate configuration on import
validate_config()



