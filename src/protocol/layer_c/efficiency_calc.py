"""
Efficiency Calculator for Provider Selection.

Implements the RREH vs Platoon selection logic with 20% efficiency threshold.
Energy-only comparison based on detour costs.
"""

from typing import Optional, List, Tuple, TYPE_CHECKING
from dataclasses import dataclass

from src.protocol.config import ProtocolConfig

if TYPE_CHECKING:
    from src.protocol.context import MVCCPContext
    from src.protocol.layer_b.provider_table import ProviderEntry


@dataclass
class ProviderEvaluation:
    """Result of evaluating a provider for selection."""
    provider: 'ProviderEntry'
    direct_cost: float      # Energy to go directly to destination (kWh)
    provider_cost: float    # Energy to go via provider then to destination (kWh)
    detour_cost: float      # Extra energy for detour (provider_cost - direct_cost)
    detour_percentage: float  # Detour as percentage of direct cost
    route_alignment: float  # Dot product of direction vectors (-1 to 1)
    is_rreh: bool
    is_recommended: bool    # True if this provider is recommended
    effective_threshold: float = 0.20  # Threshold used for this evaluation (P5)
    urgency_ratio: float = 0.0         # distance_to_empty / distance_to_dest (P5)
    queue_time: float = 0.0            # Queue wait time in seconds (P7)
    queue_penalty: float = 0.0         # Energy penalty for queue (kWh) (P7)
    total_cost: float = 0.0            # detour_cost + queue_penalty (P7)


class EfficiencyCalculator:
    """
    Calculates efficiency of different provider options for a consumer.
    
    Selection Logic:
    1. Calculate direct_cost = energy to reach destination directly
    2. For each RREH: rreh_cost = energy_to_rreh + energy_rreh_to_destination
    3. For each Platoon: platoon_cost = energy_to_meetup + energy_meetup_to_destination
    4. Calculate detour = provider_cost - direct_cost
    5. Prefer RREH if detour <= 20% of direct_cost
    6. Otherwise, choose provider with lowest detour
    """
    
    # Efficiency threshold: prefer RREH if detour <= 20%
    RREH_PREFERENCE_THRESHOLD = 0.20
    
    def __init__(self, context: 'MVCCPContext'):
        """
        Initialize the efficiency calculator.
        
        Args:
            context: MVCCP protocol context
        """
        self.context = context
    
    def calculate_urgency_ratio(self) -> float:
        """
        Calculate urgency ratio for battery-aware provider selection (P5).
        
        Urgency = distance_to_empty / distance_to_destination
        - < 1.0: Critical - can't reach destination without charging
        - < 1.2: Low battery - should charge soon
        - >= 1.2: Healthy - can reach destination comfortably
        
        Returns:
            Urgency ratio (0.0 if no destination set)
        """
        node = self.context.node
        destination = node.destination
        
        if destination is None:
            return 0.0
        
        # Calculate distance to empty (km we can travel with remaining battery)
        current_pos = node.position()
        shareable = node.shareable_energy()
        remaining_energy = node.battery_energy_kwh
        
        # Use remaining energy (not shareable) for urgency calculation
        distance_to_empty = remaining_energy / ProtocolConfig.ENERGY_CONSUMPTION_RATE
        
        # Calculate distance to destination
        distance_to_dest = node._euclidean_distance_km(current_pos, destination)
        
        if distance_to_dest < ProtocolConfig.FLOAT_EPSILON:
            return float('inf')  # At destination
        
        return distance_to_empty / distance_to_dest
    
    def get_dynamic_threshold(self) -> float:
        """
        Get dynamic RREH preference threshold based on battery urgency (P5).
        
        Returns:
            Threshold value (0.20 to 1.0)
        """
        urgency = self.calculate_urgency_ratio()
        
        if urgency < ProtocolConfig.URGENCY_CRITICAL:
            # Critical battery - accept any detour
            return ProtocolConfig.THRESHOLD_CRITICAL
        elif urgency < ProtocolConfig.URGENCY_LOW:
            # Low battery - more willing to detour
            return ProtocolConfig.THRESHOLD_LOW
        else:
            # Healthy battery - standard threshold
            return ProtocolConfig.THRESHOLD_HEALTHY
    
    def calculate_direct_cost(self) -> float:
        """
        Calculate energy cost to go directly to destination.
        
        Returns:
            Energy in kWh to reach destination directly
        """
        return self.context.node.energy_to_destination()
    
    def calculate_provider_cost(self, provider: 'ProviderEntry') -> float:
        """
        Calculate total energy cost to reach destination via a provider.
        
        For RREH: energy_to_rreh + energy_from_rreh_to_destination
        For Platoon: energy_to_meetup + energy_from_meetup_to_destination
        
        Args:
            provider: Provider entry to evaluate
            
        Returns:
            Total energy in kWh
        """
        node = self.context.node
        provider_pos = provider.position
        destination = node.destination
        
        if destination is None:
            return 0.0
        
        # Energy to reach the provider
        energy_to_provider = node.energy_to(provider_pos)
        
        # Energy from provider to our destination
        # Use node's energy calculation method for consistency
        energy_provider_to_dest = self._energy_between(provider_pos, destination)
        
        return energy_to_provider + energy_provider_to_dest
    
    def _energy_between(self, from_pos: Tuple[float, float], 
                        to_pos: Tuple[float, float]) -> float:
        """
        Calculate energy to travel between two positions.
        
        Args:
            from_pos: Starting position (lat, lon)
            to_pos: Ending position (lat, lon)
            
        Returns:
            Energy in kWh
        """
        from src.core.node import Node
        
        # Use Node's distance calculation (which uses route_provider if available)
        if Node.route_provider is not None:
            distance_km = Node.route_provider.get_route_distance(from_pos, to_pos)
        else:
            # Fallback to Euclidean
            distance_km = self.context.node._euclidean_distance_km(from_pos, to_pos)
        
        return distance_km * ProtocolConfig.ENERGY_CONSUMPTION_RATE
    
    def calculate_route_alignment(self, provider: 'ProviderEntry') -> float:
        """
        Calculate route alignment between consumer and provider direction.
        Uses dot product of normalized direction vectors.
        
        Args:
            provider: Provider entry
            
        Returns:
            Alignment score from -1 (opposite) to 1 (same direction)
        """
        consumer_dir = self.context.node.direction_vector()
        provider_dir = provider.direction
        
        if consumer_dir == (0.0, 0.0) or provider_dir == (0.0, 0.0):
            return 0.0
        
        # Dot product of normalized vectors
        return consumer_dir[0] * provider_dir[0] + consumer_dir[1] * provider_dir[1]
    
    def evaluate_provider(self, provider: 'ProviderEntry') -> ProviderEvaluation:
        """
        Evaluate a single provider with dynamic threshold and queue modeling (P5/P7).
        
        Args:
            provider: Provider to evaluate
            
        Returns:
            ProviderEvaluation with all calculated metrics
        """
        direct_cost = self.calculate_direct_cost()
        provider_cost = self.calculate_provider_cost(provider)
        detour_cost = provider_cost - direct_cost
        
        # Calculate detour percentage (avoid division by zero)
        if direct_cost > 0:
            detour_percentage = detour_cost / direct_cost
        else:
            detour_percentage = 0.0 if detour_cost <= 0 else float('inf')
        
        route_alignment = self.calculate_route_alignment(provider)
        is_rreh = provider.is_rreh()
        
        # P5: Get dynamic threshold based on battery urgency
        effective_threshold = self.get_dynamic_threshold()
        urgency_ratio = self.calculate_urgency_ratio()
        
        # Determine if recommended (RREH within dynamic threshold)
        is_recommended = is_rreh and detour_percentage <= effective_threshold
        
        # P7: Calculate queue penalty for RREHs
        queue_time = provider.queue_time if is_rreh else 0.0
        queue_penalty = queue_time * ProtocolConfig.QUEUE_TIME_WEIGHT
        total_cost = detour_cost + queue_penalty
        
        return ProviderEvaluation(
            provider=provider,
            direct_cost=direct_cost,
            provider_cost=provider_cost,
            detour_cost=detour_cost,
            detour_percentage=detour_percentage,
            route_alignment=route_alignment,
            is_rreh=is_rreh,
            is_recommended=is_recommended,
            effective_threshold=effective_threshold,
            urgency_ratio=urgency_ratio,
            queue_time=queue_time,
            queue_penalty=queue_penalty,
            total_cost=total_cost
        )
    
    def evaluate_all_providers(self, filter_func=None) -> List[ProviderEvaluation]:
        """
        Evaluate all available providers.
        
        Args:
            filter_func: Optional function to filter providers (returns True to include)
        
        Returns:
            List of ProviderEvaluation sorted by recommendation and detour cost
        """
        if self.context.provider_table is None:
            return []
        
        providers = self.context.provider_table.get_providers_with_capacity()
        
        # Apply filter if provided
        if filter_func:
            providers = [p for p in providers if filter_func(p)]
        
        evaluations = [self.evaluate_provider(p) for p in providers]
        
        # Sort: recommended first, then by total cost (P7: includes queue penalty)
        evaluations.sort(key=lambda e: (not e.is_recommended, e.total_cost))
        
        return evaluations
    
    def select_best_provider(self, filter_func=None) -> Optional[ProviderEvaluation]:
        """
        Select the best provider with dynamic thresholds and platoon fallback (P5/P7).
        
        Logic:
        1. Find best RREH (lowest total_cost = detour + queue penalty)
        2. Find best Platoon (lowest total_cost)
        3. Use dynamic threshold based on battery urgency
        4. If best RREH within threshold, choose RREH (guaranteed charging)
        5. Else if platoon total_cost < RREH total_cost, choose platoon
        6. Else if critical battery, allow platoon fallback even if worse
        7. Else choose RREH (guaranteed charging)
        
        Args:
            filter_func: Optional function to filter providers (returns True to include)
        
        Returns:
            Best ProviderEvaluation or None if no providers available
        """
        evaluations = self.evaluate_all_providers(filter_func)
        
        if not evaluations:
            return None
        
        # Separate RREHs and platoons
        rrehs = [e for e in evaluations if e.is_rreh]
        platoons = [e for e in evaluations if not e.is_rreh]
        
        # P7: Use total_cost (includes queue penalty) instead of just detour_cost
        best_rreh = min(rrehs, key=lambda e: e.total_cost) if rrehs else None
        best_platoon = min(platoons, key=lambda e: e.total_cost) if platoons else None
        
        # If only one type available, return it
        if best_rreh is None:
            return best_platoon
        if best_platoon is None:
            return best_rreh
        
        # Both available - apply selection logic with dynamic threshold (P5)
        direct_cost = self.calculate_direct_cost()
        dynamic_threshold = self.get_dynamic_threshold()
        urgency = self.calculate_urgency_ratio()
        
        # P5: Prefer RREH if detour is within dynamic threshold
        if direct_cost > 0:
            rreh_detour_pct = best_rreh.detour_cost / direct_cost
            if rreh_detour_pct <= dynamic_threshold:
                return best_rreh
        
        # P7: Compare total costs (includes queue penalty)
        if best_platoon.total_cost < best_rreh.total_cost:
            return best_platoon
        
        # P5: Platoon fallback - if critical battery and platoon exists, allow it
        # even if RREH has lower cost (platoon is "good enough" in emergency)
        if urgency < ProtocolConfig.URGENCY_CRITICAL and best_platoon is not None:
            # Critical battery - accept platoon as fallback
            return best_platoon
        
        # Default: prefer RREH (guaranteed charging)
        return best_rreh
    
    def get_recommendation_reason(self, evaluation: ProviderEvaluation) -> str:
        """
        Get human-readable reason for the recommendation.
        
        Args:
            evaluation: The selected provider evaluation
            
        Returns:
            Explanation string
        """
        if evaluation.is_rreh:
            if evaluation.detour_percentage <= self.RREH_PREFERENCE_THRESHOLD:
                return (f"RREH selected: detour {evaluation.detour_percentage:.1%} "
                       f"is within {self.RREH_PREFERENCE_THRESHOLD:.0%} threshold")
            else:
                return (f"RREH selected: guaranteed charging despite "
                       f"{evaluation.detour_percentage:.1%} detour")
        else:
            return (f"Platoon selected: lower detour ({evaluation.detour_cost:.2f} kWh) "
                   f"than available RREHs")
    
    def update_provider_costs(self):
        """
        Update detour_cost and route_alignment in all provider entries.
        Call this after provider table is updated to pre-compute costs.
        """
        if self.context.provider_table is None:
            return
        
        for provider in self.context.provider_table.get_all_providers():
            evaluation = self.evaluate_provider(provider)
            provider.detour_cost = evaluation.detour_cost
            provider.route_alignment = evaluation.route_alignment
            provider.total_cost = evaluation.provider_cost



