"""
Node Name Registry for MVCCP Protocol Logging.

Provides human-readable node names for logging and debugging,
mapping from node_id bytes to names like 'veh_low_0', 'rreh_1', etc.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class NodeNameRegistry:
    """
    Singleton registry mapping node IDs to human-readable names.
    
    Usage:
        # Register a node
        NodeNameRegistry.register(node_id_bytes, "veh_low_0")
        
        # Get name (returns hex fallback if not registered)
        name = NodeNameRegistry.get_name(node_id_bytes)
    """
    
    _instance = None
    _names: Dict[bytes, str] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._names = {}
        return cls._instance
    
    @classmethod
    def register(cls, node_id: bytes, name: str) -> None:
        """
        Register a human-readable name for a node ID.
        
        Args:
            node_id: 6-byte node identifier
            name: Human-readable name (e.g., 'veh_low_0')
        """
        # Ensure we're using bytes
        if isinstance(node_id, int):
            node_id = node_id.to_bytes(6, 'big')
        elif isinstance(node_id, str):
            node_id = node_id.encode()[:6].ljust(6, b'\x00')
        
        cls._names[node_id] = name
    
    @classmethod
    def get_name(cls, node_id: bytes) -> str:
        """
        Get the human-readable name for a node ID.
        
        Args:
            node_id: 6-byte node identifier
            
        Returns:
            Human-readable name or hex string fallback
        """
        if node_id is None:
            return "None"
        
        # Normalize to bytes
        if isinstance(node_id, int):
            node_id = node_id.to_bytes(6, 'big')
        elif isinstance(node_id, str):
            node_id = node_id.encode()[:6].ljust(6, b'\x00')
        
        # Return registered name or hex fallback
        if node_id in cls._names:
            return cls._names[node_id]
        else:
            return node_id.hex()[:8]
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered names."""
        cls._names.clear()
    
    @classmethod
    def get_all(cls) -> Dict[bytes, str]:
        """Get all registered name mappings."""
        return cls._names.copy()


# Convenience functions
def register_node(node_id: bytes, name: str) -> None:
    """Register a node name."""
    NodeNameRegistry.register(node_id, name)


def get_node_name(node_id: bytes) -> str:
    """Get a node's human-readable name."""
    return NodeNameRegistry.get_name(node_id)
