from enum import Enum, auto


class NodeRole(Enum):
    """Role of a node in the charging coordination protocol."""
    CONSUMER = auto()        # Seeking energy from providers
    PLATOON_HEAD = auto()    # Leading a platoon, providing energy to members
    RREH = auto()            # Roadside Renewable Energy Hub (stationary)
    PLATOON_MEMBER = auto()  # Member of a platoon (receiving charge)


class ConsumerState(Enum):
    """Section 8.1: Consumer State Machine."""
    DISCOVER = auto()      # Listen for PAs and GRID_STATUS
    EVALUATE = auto()      # Build ProviderTable and compute preferences
    SEND_OFFER = auto()    # Send JOIN_OFFER to selected provider
    WAIT_ACCEPT = auto()   # Wait for JOIN_ACCEPT (with timeout)
    SEND_ACK = auto()      # Send ACK upon receiving ACCEPT
    WAIT_ACKACK = auto()   # Wait for final ACKACK
    ALLOCATED = auto()     # Reservation confirmed
    TRAVEL = auto()        # Moving toward meeting point or RREH
    CHARGE = auto()        # Performing charging session
    LEAVE = auto()         # Session ended, update energy state


class PlatoonHeadState(Enum):
    """Section 8.3: Platoon Head State Machine."""
    BEACON = auto()              # Periodically send PLATOON_BEACON
    WAIT_OFFERS = auto()         # Listen for JOIN_OFFER requests
    EVALUATE_OFFERS = auto()     # Evaluate incoming join requests
    SEND_ACCEPT = auto()         # Send JOIN_ACCEPT to accepted members
    WAIT_ACK = auto()            # Wait for ACK from consumer
    SEND_ACKACK = auto()         # Confirm final commitment
    COORDINATE = auto()          # Maintain platoon using PLATOON_STATUS
    HANDOFF = auto()             # Transferring PH role to another member


class RREHState(Enum):
    """RREH (Roadside Renewable Energy Hub) State Machine."""
    GRID_ANNOUNCE = auto()   # Broadcast GRID_STATUS periodically
    WAIT_OFFERS = auto()     # Listen for JOIN_OFFER requests
    EVALUATE_QUEUE = auto()  # Manage queue and select next consumer
    SEND_ACCEPT = auto()     # Send JOIN_ACCEPT to consumer
    WAIT_ACK = auto()        # Wait for ACK
    SEND_ACKACK = auto()     # Confirm commitment
    CHARGE_SESSION = auto()  # Actively charging a consumer
    IDLE = auto()            # No active sessions, ready for new
