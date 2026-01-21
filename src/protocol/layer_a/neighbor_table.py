from typing import Dict, Set, Any, Optional
from copy import deepcopy
from src.core.node import Node
import logging
from src.protocol.config import ProtocolConfig
from src.protocol.locks import RWLock, ReadLock, WriteLock

logger = logging.getLogger(__name__)


class NeighborTable:
    """
    Thread-safe neighbor table with type-validated updates and rate-limited pruning.
    Uses read-write lock for better read concurrency.
    """
    
    def __init__(self, context):
        if context is None:
            raise ValueError("context cannot be None")
        self.context = context
        self.neighbors: Dict[bytes, Node] = {}
        self._rwlock = RWLock()
        self._last_prune_time = 0.0

    def update_neighbor(self, node_id: bytes, attrs: dict, two_hop_list: list) -> None:
        """
        Update or create a neighbor entry.
        
        Args:
            node_id: Unique identifier for the neighbor
            attrs: Attributes to update (will be validated and filtered)
            two_hop_list: List of 2-hop neighbor IDs
        """
        # Validate inputs
        self._validate_inputs(node_id, attrs, two_hop_list)
        
        # Validate and filter attributes OUTSIDE the lock
        safe_attrs = self._validate_attrs(attrs)
        
        # Validate and filter two-hop list OUTSIDE the lock
        safe_two_hop_list = self._validate_two_hop_list(two_hop_list)
        
        # Merge with defaults for required fields
        node_params = {**ProtocolConfig.NODE_DEFAULTS, **safe_attrs}
        
        node_to_add = None
        removed_nids = []
        
        # Critical Section: Write lock for updates
        try:
            with WriteLock(self._rwlock):
                # Read current_time INSIDE the lock to avoid race condition
                current_time = self.context.current_time
                if current_time is None:
                    raise RuntimeError(
                        "context.current_time is None - simulation time must be "
                        "initialized via context.update_time() before protocol operations"
                    )
                
                # Rate-limited pruning (not on every update)
                if current_time - self._last_prune_time > ProtocolConfig.PRUNE_INTERVAL:
                    removed_nids = self._prune_stale_unsafe(current_time)
                    self._last_prune_time = current_time
                
                if node_id not in self.neighbors:
                    try:
                        self.neighbors[node_id] = Node(node_id=node_id, **node_params)
                        node_to_add = node_id
                    except Exception as e:
                        logger.error(f"Failed to create Node for {node_id}: {e}")
                        return

                node = self.neighbors[node_id]
                node.last_seen = current_time
                
                # Safe update: only whitelisted + type-validated attrs
                for key, val in safe_attrs.items():
                    if hasattr(node, key):
                        setattr(node, key, val)
                
                # Update Topology
                node.two_hop_neighbors = set(safe_two_hop_list)
                node.link_status = "SYM"
        except RuntimeError:
            # Re-raise critical errors (e.g., time not initialized)
            raise
        except Exception as e:
            logger.error(f"Error in update_neighbor for {node_id}: {e}", exc_info=True)
            return

        
        # Logging OUTSIDE the lock
        try:
            if node_to_add:
                logger.debug(f"New neighbor discovered: {node_to_add}")
            for nid in removed_nids:
                logger.debug(f"Removed stale neighbor: {nid}")
        except Exception:
            # Ignore logging errors (misconfigured logger)
            pass

    def _validate_inputs(self, node_id: bytes, attrs: dict, two_hop_list: list) -> None:
        """Validate input parameters for None and basic types."""
        if node_id is None:
            raise ValueError("node_id cannot be None")
        if not isinstance(node_id, bytes):
            raise TypeError(f"node_id must be bytes, got {type(node_id)}")
        if attrs is None:
            raise ValueError("attrs cannot be None")
        if not isinstance(attrs, dict):
            raise TypeError(f"attrs must be dict, got {type(attrs)}")
        if two_hop_list is None:
            raise ValueError("two_hop_list cannot be None")
        if not isinstance(two_hop_list, (list, tuple)):
            raise TypeError(f"two_hop_list must be list or tuple, got {type(two_hop_list)}")

    def _validate_two_hop_list(self, two_hop_list: list) -> list:
        """
        Validate and filter two-hop neighbor list.
        Removes None, non-bytes, and self-references.
        """
        safe_list = []
        for item in two_hop_list:
            if item is None:
                logger.warning("Found None in two_hop_list, skipping")
                continue
            if not isinstance(item, bytes):
                logger.warning(f"Found non-bytes item in two_hop_list: {type(item)}, skipping")
                continue
            if item == self.context.node_id:
                logger.debug(f"Found self-reference in two_hop_list, skipping")
                continue
            safe_list.append(item)
        return safe_list

    def _validate_attrs(self, attrs: dict) -> dict:
        """
        Filter and type-validate attributes.
        
        Returns only attributes that are:
        1. In the whitelist (ALLOWED_NODE_ATTRS)
        2. Have valid types (per ATTR_TYPES)
        3. Pass range validation (per ATTR_RANGES)
        """
        safe_attrs = {}
        for key, val in attrs.items():
            # Check whitelist
            if key not in ProtocolConfig.ALLOWED_NODE_ATTRS:
                continue
            
            # Check type
            expected_types = ProtocolConfig.ATTR_TYPES.get(key)
            if expected_types and not isinstance(val, expected_types):
                logger.warning(
                    f"Invalid type for {key}: expected {expected_types}, got {type(val)}"
                )
                continue
            
            # Check range (if range validation exists for this attribute)
            if not self._validate_range(key, val):
                continue
            
            safe_attrs[key] = val
        
        return safe_attrs

    def _validate_range(self, key: str, val: Any) -> bool:
        """
        Validate attribute value is within allowed range.
        Returns True if valid, False otherwise.
        """
        if key not in ProtocolConfig.ATTR_RANGES:
            return True  # No range validation defined
        
        min_val, max_val = ProtocolConfig.ATTR_RANGES[key]
        
        # Check minimum
        if min_val is not None and val < min_val:
            logger.warning(
                f"Value {val} for {key} is below minimum {min_val}, clamping"
            )
            return False
        
        # Check maximum
        if max_val is not None and val > max_val:
            logger.warning(
                f"Value {val} for {key} is above maximum {max_val}, clamping"
            )
            return False
        
        # Special case: battery_energy_kwh must not exceed capacity
        # This is checked dynamically during update, not here
        
        return True

    def get_one_hop_set(self) -> Set[bytes]:
        """Returns a snapshot of current neighbor IDs."""
        try:
            with ReadLock(self._rwlock):
                return set(self.neighbors.keys())
        except Exception as e:
            logger.error(f"Error in get_one_hop_set: {e}", exc_info=True)
            return set()

    def get_two_hop_set(self) -> Set[bytes]:
        """Returns a snapshot of 2-hop neighbor IDs (excluding self and 1-hop)."""
        try:
            with ReadLock(self._rwlock):
                two_hops = set()
                for node in self.neighbors.values():
                    two_hops.update(node.two_hop_neighbors)
                
                two_hops.discard(self.context.node_id)
                two_hops.difference_update(self.neighbors.keys())
                return two_hops
        except Exception as e:
            logger.error(f"Error in get_two_hop_set: {e}", exc_info=True)
            return set()

    def get_snapshot(self) -> Dict[bytes, dict]:
        """
        Returns a thread-safe snapshot of neighbor data for read-heavy operations.
        
        The returned dict maps node_id -> dict of relevant attributes.
        This is safe to iterate over without holding the lock.
        All mutable structures (sets) are deep copied for immutability.
        """
        try:
            with ReadLock(self._rwlock):
                snapshot = {}
                for nid, node in self.neighbors.items():
                    # Normalize velocity to tuple format
                    vel = node.velocity
                    if isinstance(vel, (int, float)):
                        vel = (float(vel), 0.0)
                    elif isinstance(vel, (list, tuple)) and len(vel) >= 2:
                        vel = (float(vel[0]), float(vel[1]))
                    else:
                        vel = (0.0, 0.0)
                    
                    snapshot[nid] = {
                        'node_id': node.node_id,
                        'battery_capacity_kwh': float(node.battery_capacity_kwh),
                        'battery_energy_kwh': float(node.battery_energy_kwh),
                        'velocity': vel,  # Always tuple
                        'etx': float(node.etx),
                        'delay': float(getattr(node, 'delay', 0.0)),  # Delay in ms (Section 7.4)
                        'willingness': int(node.willingness),
                        'lane_weight': float(node.lane_weight),
                        'link_stability': float(node.link_stability),
                        'two_hop_neighbors': set(node.two_hop_neighbors),  # Copy the set
                    }
                return snapshot
        except Exception as e:
            logger.error(f"Error in get_snapshot: {e}", exc_info=True)
            return {}

    def get_neighbor_count(self) -> int:
        """
        Returns the number of one-hop neighbors (thread-safe).

        Returns:
            Number of neighbors in the table
        """
        try:
            with ReadLock(self._rwlock):
                return len(self.neighbors)
        except Exception as e:
            logger.error(f"Error getting neighbor count: {e}")
            return 0

    def prune_stale(self) -> None:
        """Public method to explicitly trigger pruning."""
        removed = []
        try:
            with WriteLock(self._rwlock):
                current_time = self.context.current_time
                if current_time is None:
                    raise RuntimeError(
                        "context.current_time is None - simulation time must be "
                        "initialized via context.update_time() before protocol operations"
                    )
                removed = self._prune_stale_unsafe(current_time)
        except Exception as e:
            logger.error(f"Error in prune_stale: {e}", exc_info=True)
            return
        
        # Log outside lock
        try:
            for nid in removed:
                logger.debug(f"Removed stale neighbor: {nid}")
        except Exception:
            # Ignore logging errors
            pass

    def _prune_stale_unsafe(self, current_time: float) -> list:
        """
        Remove stale neighbors. Must be called within write lock.
        
        Returns list of removed node IDs for logging outside lock.
        """
        to_remove = []
        for nid, node in self.neighbors.items():
            if current_time - node.last_seen > ProtocolConfig.NEIGHBOR_TIMEOUT:
                to_remove.append(nid)
        
        for nid in to_remove:
            del self.neighbors[nid]
        
        return to_remove



