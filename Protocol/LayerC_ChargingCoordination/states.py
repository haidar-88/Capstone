from enum import Enum, auto

class ConsumerState(Enum):
    DISCOVER = auto()
    EVALUATE = auto()
    SEND_OFFER = auto()
    WAIT_ACCEPT = auto()
    SEND_ACK = auto()
    WAIT_ACKACK = auto()
    ALLOCATED = auto()
    TRAVEL = auto()
    CHARGE = auto()
    LEAVE = auto()

class ProviderState(Enum):
    ANNOUNCE = auto()
    WAIT_OFFERS = auto()
    SELECT = auto()
    SEND_ACCEPT = auto()
    WAIT_ACK = auto()
    SEND_ACKACK = auto()
    CHARGE = auto()
