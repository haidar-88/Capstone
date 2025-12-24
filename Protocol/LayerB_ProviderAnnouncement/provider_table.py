from dataclasses import dataclass
from typing import Dict, Optional
import time

@dataclass
class ProviderEntry:
    provider_id: bytes
    provider_type: int # 0=MP, 1=PH, 2=RREH
    position: tuple
    energy_available: float
    timestamp: float
    
    # Optional fields
    price: float = 0.0
    renewable_fraction: float = 0.0
    
    # Helpers
    detour_cost: float = 0.0 # Calculated by consumer

class ProviderTable:
    def __init__(self, context):
        self.context = context
        self.providers: Dict[bytes, ProviderEntry] = {}
        self.PROVIDER_TIMEOUT = 10.0 # seconds

    def update_provider(self, provider_id: bytes, info: dict):
        current_time = self.context.current_time
        
        # Parse info
        p_type = info.get('type', 0)
        pos = info.get('position', (0.0, 0.0))
        energy = info.get('energy', 0.0)
        
        entry = ProviderEntry(
            provider_id=provider_id,
            provider_type=p_type,
            position=pos,
            energy_available=energy,
            timestamp=current_time
        )
        self.providers[provider_id] = entry
        print(f"[ProviderTable] Updated provider {provider_id}")

    def get_best_provider(self) -> Optional[ProviderEntry]:
        self._clean_stale()
        if not self.providers:
            return None
        
        # Simple policy: Highest Energy for now
        # Ideally: "Green-aware" policy as per Step 9.
        best = None
        best_energy = -1.0
        
        for p in self.providers.values():
            if p.energy_available > best_energy:
                best_energy = p.energy_available
                best = p
        return best

    def _clean_stale(self):
        current_time = self.context.current_time
        to_remove = []
        for pid, entry in self.providers.items():
            if current_time - entry.timestamp > self.PROVIDER_TIMEOUT:
                to_remove.append(pid)
        for pid in to_remove:
            del self.providers[pid]
