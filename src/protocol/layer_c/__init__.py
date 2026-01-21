"""
Layer C: Charging Coordination

This layer handles the negotiation and coordination of charging sessions
between consumers (EVs needing charge) and providers (Platoon Heads and RREHs).
"""

# State enums
from .states import (
    NodeRole,
    ConsumerState,
    PlatoonHeadState,
    RREHState,
)

# Role management
from .role_manager import RoleManager

# Efficiency calculation for provider selection
from .efficiency_calc import EfficiencyCalculator, ProviderEvaluation

# Handlers for each role
from .consumer_handler import ConsumerHandler
from .platoon_head_handler import PlatoonHeadHandler
from .rreh_handler import RREHHandler

__all__ = [
    # States
    'NodeRole',
    'ConsumerState',
    'PlatoonHeadState',
    'RREHState',
    
    # Role management
    'RoleManager',
    
    # Efficiency
    'EfficiencyCalculator',
    'ProviderEvaluation',
    
    # Handlers
    'ConsumerHandler',
    'PlatoonHeadHandler',
    'RREHHandler',
]
