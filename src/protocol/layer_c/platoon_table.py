"""
PlatoonTable: Tracks known platoons for inter-platoon discovery.

Enables consumers to discover and compare multiple platoons to find
the best one for their needs based on direction, energy, and slots.

Uses RWLock for thread-safety (consistent with NeighborTable/ProviderTable).
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from src.protocol.locks import RWLock, ReadLock, WriteLock

if TYPE_CHECKING:
    from src.core.node import Node

# Import ProtocolConfig for constants
try:
    from src.protocol.config import ProtocolConfig
except ImportError:
    class ProtocolConfig:
        PLATOON_ENTRY_TIMEOUT = 15.0
        PLATOON_SCORE_DIRECTION = 0.4
        PLATOON_SCORE_DISTANCE = 0.3
        PLATOON_SCORE_ENERGY = 0.3
        FLOAT_EPSILON = 1e-9

logger = logging.getLogger(__name__)


@dataclass
class PlatoonEntry:
    """
    Entry in the PlatoonTable representing a discovered platoon.
    
    Updated when PLATOON_ANNOUNCE messages are received.
    """
    platoon_id: bytes
    head_id: bytes
    position: Tuple[float, float]  # (lat, lon) GPS position
    direction: Tuple[float, float]  # Normalized (dx, dy) heading
    destination: Tuple[float, float]  # (lat, lon) target destination
    surplus_energy: float  # Available shareable energy in kWh
    available_slots: int  # Number of open slots
    formation_efficiency: float  # Edge-based formation efficiency (0.0-1.0)
    last_seen: float  # Simulation timestamp of last update
    
    # Computed fields
    score: float = field(default=0.0)  # Computed score for consumer matching
    
    def is_stale(self, current_time: float, timeout: float = None) -> bool:
        """Check if entry is stale (hasn't been updated recently)."""
        if timeout is None:
            timeout = ProtocolConfig.PLATOON_ENTRY_TIMEOUT
        return (current_time - self.last_seen) > timeout
    
    def has_capacity(self) -> bool:
        """Check if platoon has available slots."""
        return self.available_slots > 0
    
    def __repr__(self) -> str:
        pid = self.platoon_id.hex()[:8] if self.platoon_id else "None"
        return (f"PlatoonEntry(id={pid}, energy={self.surplus_energy:.1f}kWh, "
                f"slots={self.available_slots}, eff={self.formation_efficiency:.2f})")


class PlatoonTable:
    """
    Thread-safe table of known platoons in the area.
    
    Used by consumers to select the best platoon to join based on:
    - Direction match (are we heading the same way?)
    - Distance (how far is the platoon?)
    - Energy (does the platoon have enough energy?)
    
    Virtual edges are computed between consumer position and each platoon
    for routing decisions (no physical transfer, just decision support).
    """
    
    def __init__(self):
        """Initialize an empty PlatoonTable."""
        self._entries: Dict[bytes, PlatoonEntry] = {}
        self._lock = RWLock()
    
    def update(self, entry: PlatoonEntry) -> None:
        """
        Add or update a platoon entry.
        
        Called when PLATOON_ANNOUNCE is received.
        
        Args:
            entry: PlatoonEntry to add/update
        """
        with WriteLock(self._lock):
            self._entries[entry.platoon_id] = entry
            logger.debug(f"Updated platoon entry: {entry}")
    
    def update_from_announce(
        self,
        platoon_id: bytes,
        head_id: bytes,
        position: Tuple[float, float],
        direction: Tuple[float, float],
        destination: Tuple[float, float],
        surplus_energy: float,
        available_slots: int,
        formation_efficiency: float,
        timestamp: float
    ) -> None:
        """
        Update table from a PLATOON_ANNOUNCE message.
        
        Convenience method that creates/updates entry from message fields.
        """
        entry = PlatoonEntry(
            platoon_id=platoon_id,
            head_id=head_id,
            position=position,
            direction=direction,
            destination=destination,
            surplus_energy=surplus_energy,
            available_slots=available_slots,
            formation_efficiency=formation_efficiency,
            last_seen=timestamp
        )
        self.update(entry)
    
    def get(self, platoon_id: bytes) -> Optional[PlatoonEntry]:
        """
        Get a platoon entry by ID.
        
        Args:
            platoon_id: ID of the platoon to look up
            
        Returns:
            PlatoonEntry or None if not found
        """
        with ReadLock(self._lock):
            return self._entries.get(platoon_id)
    
    def get_all(self) -> List[PlatoonEntry]:
        """
        Get all platoon entries.
        
        Returns:
            List of all PlatoonEntry objects (copy, safe to modify)
        """
        with ReadLock(self._lock):
            return list(self._entries.values())
    
    def get_available_platoons(self) -> List[PlatoonEntry]:
        """
        Get platoons with available slots.
        
        Returns:
            List of platoons that have capacity for new members
        """
        with ReadLock(self._lock):
            return [e for e in self._entries.values() if e.has_capacity()]
    
    def prune_stale(self, current_time: float) -> int:
        """
        Remove stale entries that haven't been updated recently.
        
        Args:
            current_time: Current simulation time
            
        Returns:
            Number of entries pruned
        """
        with WriteLock(self._lock):
            stale_ids = [
                pid for pid, entry in self._entries.items()
                if entry.is_stale(current_time)
            ]
            
            for pid in stale_ids:
                del self._entries[pid]
                logger.debug(f"Pruned stale platoon entry: {pid.hex()[:8]}")
            
            return len(stale_ids)
    
    def remove(self, platoon_id: bytes) -> bool:
        """
        Remove a specific platoon entry.
        
        Args:
            platoon_id: ID of the platoon to remove
            
        Returns:
            True if removed, False if not found
        """
        with WriteLock(self._lock):
            if platoon_id in self._entries:
                del self._entries[platoon_id]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all entries from the table."""
        with WriteLock(self._lock):
            self._entries.clear()
    
    def __len__(self) -> int:
        """Return number of entries in the table."""
        with ReadLock(self._lock):
            return len(self._entries)
    
    # ==========================================================================
    # Virtual Edge Scoring (for consumer platoon selection)
    # ==========================================================================
    
    def calculate_platoon_score(
        self,
        entry: PlatoonEntry,
        consumer_position: Tuple[float, float],
        consumer_direction: Tuple[float, float],
        energy_needed: float
    ) -> float:
        """
        Calculate a score for how well a platoon matches consumer needs.
        
        Score factors (configurable weights):
        - Direction match: dot product of direction vectors
        - Distance: inverse of distance to platoon
        - Energy match: ratio of surplus to needed
        
        Higher score = better match.
        
        Args:
            entry: PlatoonEntry to score
            consumer_position: Consumer's (lat, lon) position
            consumer_direction: Consumer's normalized (dx, dy) heading
            energy_needed: Energy consumer needs in kWh
            
        Returns:
            Score value (higher is better)
        """
        w_direction = ProtocolConfig.PLATOON_SCORE_DIRECTION
        w_distance = ProtocolConfig.PLATOON_SCORE_DISTANCE
        w_energy = ProtocolConfig.PLATOON_SCORE_ENERGY
        
        # Direction match: dot product of normalized vectors
        # Range: -1 (opposite) to +1 (same direction)
        direction_match = self._dot_product(consumer_direction, entry.direction)
        # Normalize to 0-1 range
        direction_score = (direction_match + 1.0) / 2.0
        
        # Distance: inverse relationship (closer is better)
        distance = self._calculate_distance(consumer_position, entry.position)
        # Avoid division by zero, normalize assuming 10km is "far"
        distance_score = 1.0 / (1.0 + distance / 10.0)
        
        # Energy match: ratio of surplus to needed
        if energy_needed > ProtocolConfig.FLOAT_EPSILON:
            energy_score = min(1.0, entry.surplus_energy / energy_needed)
        else:
            energy_score = 1.0 if entry.surplus_energy > 0 else 0.0
        
        # Bonus for formation efficiency
        efficiency_bonus = entry.formation_efficiency * 0.1
        
        # Weighted sum
        score = (
            w_direction * direction_score +
            w_distance * distance_score +
            w_energy * energy_score +
            efficiency_bonus
        )
        
        # Penalty if no slots available
        if not entry.has_capacity():
            score *= 0.1
        
        return score
    
    def find_best_platoon(
        self,
        consumer_position: Tuple[float, float],
        consumer_direction: Tuple[float, float],
        energy_needed: float,
        exclude_platoon_id: bytes = None
    ) -> Optional[PlatoonEntry]:
        """
        Find the best matching platoon for a consumer.
        
        Uses virtual edge scoring to rank all known platoons.
        
        Args:
            consumer_position: Consumer's (lat, lon) position
            consumer_direction: Consumer's normalized (dx, dy) heading
            energy_needed: Energy consumer needs in kWh
            exclude_platoon_id: Optional platoon to exclude (e.g., current platoon)
            
        Returns:
            Best matching PlatoonEntry, or None if no suitable platoons
        """
        with ReadLock(self._lock):
            best_entry = None
            best_score = -float('inf')
            
            for platoon_id, entry in self._entries.items():
                # Skip excluded platoon
                if exclude_platoon_id and platoon_id == exclude_platoon_id:
                    continue
                
                # Skip platoons without capacity
                if not entry.has_capacity():
                    continue
                
                score = self.calculate_platoon_score(
                    entry, consumer_position, consumer_direction, energy_needed
                )
                
                if score > best_score:
                    best_score = score
                    best_entry = entry
            
            if best_entry:
                # Store computed score
                best_entry.score = best_score
                logger.debug(f"Best platoon: {best_entry} with score {best_score:.3f}")
            
            return best_entry
    
    def rank_platoons(
        self,
        consumer_position: Tuple[float, float],
        consumer_direction: Tuple[float, float],
        energy_needed: float,
        top_n: int = 5
    ) -> List[Tuple[PlatoonEntry, float]]:
        """
        Rank all platoons by score for a consumer.
        
        Args:
            consumer_position: Consumer's (lat, lon) position
            consumer_direction: Consumer's normalized (dx, dy) heading
            energy_needed: Energy consumer needs in kWh
            top_n: Maximum number of results to return
            
        Returns:
            List of (PlatoonEntry, score) tuples, sorted by score descending
        """
        with ReadLock(self._lock):
            scored = []
            
            for entry in self._entries.values():
                score = self.calculate_platoon_score(
                    entry, consumer_position, consumer_direction, energy_needed
                )
                scored.append((entry, score))
            
            # Sort by score descending
            scored.sort(key=lambda x: x[1], reverse=True)
            
            return scored[:top_n]
    
    # ==========================================================================
    # Helper Methods
    # ==========================================================================
    
    @staticmethod
    def _dot_product(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
        """Calculate dot product of two 2D vectors."""
        return v1[0] * v2[0] + v1[1] * v2[1]
    
    @staticmethod
    def _calculate_distance(
        pos1: Tuple[float, float], 
        pos2: Tuple[float, float]
    ) -> float:
        """
        Calculate approximate distance between two GPS positions in km.
        
        Uses simple Euclidean approximation with latitude correction.
        """
        lat1, lon1 = pos1
        lat2, lon2 = pos2
        
        # Approximate km per degree
        km_per_deg_lat = 111.0
        km_per_deg_lon = 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
        
        dlat = (lat2 - lat1) * km_per_deg_lat
        dlon = (lon2 - lon1) * km_per_deg_lon
        
        return math.sqrt(dlat * dlat + dlon * dlon)
