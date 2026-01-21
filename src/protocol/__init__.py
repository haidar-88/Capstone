"""
MVCCP Protocol Implementation.

Multi-hop VANET Charging Coordination Protocol (MVCCP) provides a decentralized
framework for autonomous EVs to discover energy providers, negotiate charging
sessions, and coordinate platoon-based wireless energy transfer.
"""

from .context import MVCCPContext
from .config import ProtocolConfig

__all__ = ['MVCCPContext', 'ProtocolConfig']



