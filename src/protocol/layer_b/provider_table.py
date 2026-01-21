from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
import logging

from src.protocol.config import ProtocolConfig
from src.protocol.locks import RWLock, ReadLock, WriteLock

logger = logging.getLogger(__name__)


class ProviderType:
    """Provider type constants (from ProtocolConfig)."""
    MOBILE_PROVIDER = ProtocolConfig.PROVIDER_TYPE_MP   # 0
    PLATOON_HEAD = ProtocolConfig.PROVIDER_TYPE_PH      # 1
    RREH = ProtocolConfig.PROVIDER_TYPE_RREH            # 2


@dataclass
class ProviderEntry:
    """
    Entry in the Provider Table representing a known energy provider.
    Populated from PA messages and GRID_STATUS messages.
    """
    # Core identification
    provider_id: bytes
    provider_type: int  # 0=MP, 1=PH, 2=RREH (use ProviderType enum)
    position: Tuple[float, float]  # (lat, lon)
    energy_available: float  # kWh available for sharing
    timestamp: float  # When this entry was last updated
    
    # Destination and direction (for route alignment)
    destination: Tuple[float, float] = (0.0, 0.0)  # Provider's destination
    direction: Tuple[float, float] = (0.0, 0.0)    # Normalized direction vector (dx, dy)
    
    # Platoon-specific fields (for PH providers)
    platoon_id: bytes = b""
    platoon_size: int = 0           # Current number of members
    available_slots: int = 6        # Slots available for new members
    
    # RREH-specific fields
    queue_time: float = 0.0         # Estimated queue wait time in seconds
    operational_state: str = 'normal'  # normal, congested, limited, offline
    available_power: float = 0.0    # kW available for charging
    max_sessions: int = 1           # Max simultaneous sessions
    
    # Optional fields
    price: float = 0.0
    renewable_fraction: float = 0.0
    
    # Calculated fields (set by consumer during evaluation)
    detour_cost: float = 0.0        # Extra energy cost for detour (kWh)
    route_alignment: float = 0.0    # Dot product of direction vectors (-1 to 1)
    total_cost: float = 0.0         # Combined cost for ranking
    
    def is_rreh(self) -> bool:
        """Check if this provider is an RREH."""
        return self.provider_type == ProviderType.RREH
    
    def is_platoon_head(self) -> bool:
        """Check if this provider is a Platoon Head."""
        return self.provider_type == ProviderType.PLATOON_HEAD
    
    def has_capacity(self) -> bool:
        """Check if provider has capacity for new consumers."""
        if self.is_rreh():
            return self.operational_state in ('normal', 'congested')
        else:
            return self.available_slots > 0


class ProviderTable:
    """
    Thread-safe table of known energy providers.
    Populated from PA messages and GRID_STATUS messages.
    Used by consumers to select the best provider.
    Uses read-write lock for better read concurrency.
    """
    
    def __init__(self, context):
        self.context = context
        self.providers: Dict[bytes, ProviderEntry] = {}
        self._rwlock = RWLock()
        self.PROVIDER_TIMEOUT = 10.0  # seconds

    def update_provider(self, provider_id: bytes, info: dict):
        """
        Update or add a provider entry (thread-safe).
        
        Args:
            provider_id: Unique provider identifier
            info: Dictionary with provider information:
                - type: int (0=MP, 1=PH, 2=RREH)
                - position: (lat, lon) tuple
                - energy: float (kWh available)
                - destination: (lat, lon) tuple
                - direction: (dx, dy) normalized vector
                - platoon_id: bytes
                - platoon_size: int
                - available_slots: int
                - queue_time: float (seconds)
                - operational_state: str
                - available_power: float (kW)
                - renewable_fraction: float
        """
        try:
            with WriteLock(self._rwlock):
                current_time = self.context.current_time
                
                # Check if entry exists and update, or create new
                existing = self.providers.get(provider_id)
                
                entry = ProviderEntry(
                    provider_id=provider_id,
                    provider_type=info.get('type', 0),
                    position=info.get('position', (0.0, 0.0)),
                    energy_available=info.get('energy', 0.0),
                    timestamp=current_time,
                    destination=info.get('destination', (0.0, 0.0)),
                    direction=info.get('direction', (0.0, 0.0)),
                    platoon_id=info.get('platoon_id', b""),
                    platoon_size=info.get('platoon_size', 0),
                    available_slots=info.get('available_slots', 6),
                    queue_time=info.get('queue_time', 0.0),
                    operational_state=info.get('operational_state', 'normal'),
                    available_power=info.get('available_power', 0.0),
                    max_sessions=info.get('max_sessions', 1),
                    renewable_fraction=info.get('renewable_fraction', 0.0),
                )
                
                # Preserve calculated fields from existing entry if not recalculated
                if existing:
                    entry.detour_cost = existing.detour_cost
                    entry.route_alignment = existing.route_alignment
                    entry.total_cost = existing.total_cost
                
                self.providers[provider_id] = entry
        except Exception as e:
            logger.error(f"Error updating provider {provider_id}: {e}", exc_info=True)

    def get_provider(self, provider_id: bytes) -> Optional[ProviderEntry]:
        """Get a specific provider by ID (thread-safe)."""
        try:
            with WriteLock(self._rwlock):
                self._clean_stale_unsafe()
                return self.providers.get(provider_id)
        except Exception as e:
            logger.error(f"Error getting provider {provider_id}: {e}", exc_info=True)
            return None

    def get_all_providers(self) -> List[ProviderEntry]:
        """Get all current providers (thread-safe snapshot)."""
        try:
            with WriteLock(self._rwlock):
                self._clean_stale_unsafe()
                return list(self.providers.values())
        except Exception as e:
            logger.error(f"Error getting all providers: {e}", exc_info=True)
            return []
    
    def get_rrehs(self) -> List[ProviderEntry]:
        """Get all RREH providers (thread-safe)."""
        try:
            with WriteLock(self._rwlock):
                self._clean_stale_unsafe()
                return [p for p in self.providers.values() if p.is_rreh()]
        except Exception as e:
            logger.error(f"Error getting RREHs: {e}", exc_info=True)
            return []
    
    def get_platoon_heads(self) -> List[ProviderEntry]:
        """Get all Platoon Head providers (thread-safe)."""
        try:
            with WriteLock(self._rwlock):
                self._clean_stale_unsafe()
                return [p for p in self.providers.values() if p.is_platoon_head()]
        except Exception as e:
            logger.error(f"Error getting platoon heads: {e}", exc_info=True)
            return []
    
    def get_providers_with_capacity(self) -> List[ProviderEntry]:
        """Get providers that have capacity for new consumers (thread-safe)."""
        try:
            with WriteLock(self._rwlock):
                self._clean_stale_unsafe()
                return [p for p in self.providers.values() if p.has_capacity()]
        except Exception as e:
            logger.error(f"Error getting providers with capacity: {e}", exc_info=True)
            return []

    def get_best_provider(self) -> Optional[ProviderEntry]:
        """
        Get the best provider based on simple energy-based ranking (thread-safe).
        For more sophisticated selection, use EfficiencyCalculator.
        
        Returns:
            Best provider entry or None if no providers available
        """
        try:
            with WriteLock(self._rwlock):
                self._clean_stale_unsafe()
                if not self.providers:
                    return None
                
                # Simple policy: Highest Energy
                best = None
                best_energy = -1.0
                
                for p in self.providers.values():
                    if p.has_capacity() and p.energy_available > best_energy:
                        best_energy = p.energy_available
                        best = p
                return best
        except Exception as e:
            logger.error(f"Error getting best provider: {e}", exc_info=True)
            return None
    
    def get_best_rreh(self) -> Optional[ProviderEntry]:
        """Get the best RREH based on queue time and availability (thread-safe)."""
        rrehs = self.get_rrehs()  # Already thread-safe
        if not rrehs:
            return None
        
        # Filter for available RREHs
        available = [r for r in rrehs if r.operational_state in ('normal', 'congested')]
        if not available:
            return None
        
        # Sort by queue time (ascending)
        available.sort(key=lambda r: r.queue_time)
        return available[0]
    
    def get_best_platoon(self) -> Optional[ProviderEntry]:
        """Get the best platoon based on energy and capacity (thread-safe)."""
        platoons = self.get_platoon_heads()  # Already thread-safe
        if not platoons:
            return None
        
        # Filter for platoons with capacity
        available = [p for p in platoons if p.available_slots > 0]
        if not available:
            return None
        
        # Sort by energy available (descending)
        available.sort(key=lambda p: p.energy_available, reverse=True)
        return available[0]

    def remove_provider(self, provider_id: bytes) -> bool:
        """Remove a provider from the table (thread-safe)."""
        try:
            with WriteLock(self._rwlock):
                if provider_id in self.providers:
                    del self.providers[provider_id]
                    return True
                return False
        except Exception as e:
            logger.error(f"Error removing provider {provider_id}: {e}", exc_info=True)
            return False

    def _clean_stale_unsafe(self):
        """
        Remove stale provider entries. Must be called within write lock.
        
        Returns:
            List of removed provider IDs for logging
        """
        current_time = self.context.current_time
        to_remove = []
        for pid, entry in self.providers.items():
            if current_time - entry.timestamp > self.PROVIDER_TIMEOUT:
                to_remove.append(pid)
        for pid in to_remove:
            del self.providers[pid]
        return to_remove
    
    def clear(self):
        """Clear all provider entries (thread-safe)."""
        try:
            with WriteLock(self._rwlock):
                self.providers.clear()
        except Exception as e:
            logger.error(f"Error clearing providers: {e}", exc_info=True)
