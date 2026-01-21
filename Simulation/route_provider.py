"""
Route Provider Interface and Implementations.

Provides distance calculation for the MVCCP protocol, supporting both
SUMO TraCI integration for real road network distances and fallback
Euclidean calculations for testing.
"""

from abc import ABC, abstractmethod
import math
from typing import Optional, Tuple


class RouteProvider(ABC):
    """
    Abstract interface for route distance calculation.
    Implementations provide distance along actual road networks or fallback methods.
    """
    
    @abstractmethod
    def get_route_distance(self, from_pos: Tuple[float, float], 
                           to_pos: Tuple[float, float]) -> float:
        """
        Calculate distance between two positions.
        
        Args:
            from_pos: Starting position as (lat, lon) tuple
            to_pos: Destination position as (lat, lon) tuple
            
        Returns:
            Distance in kilometers along the route
        """
        pass
    
    @abstractmethod
    def get_route_info(self, from_pos: Tuple[float, float],
                       to_pos: Tuple[float, float]) -> dict:
        """
        Get detailed route information between two positions.
        
        Args:
            from_pos: Starting position as (lat, lon) tuple
            to_pos: Destination position as (lat, lon) tuple
            
        Returns:
            Dictionary with route info:
            {
                'distance_km': float,
                'edges': list,  # List of edge IDs in route
                'travel_time': float,  # Estimated time in seconds
            }
        """
        pass


class SUMORouteProvider(RouteProvider):
    """
    SUMO TraCI implementation for real road network distances.
    Uses TraCI's findRoute() to compute shortest path distances.
    """
    
    def __init__(self, traci_connection=None):
        """
        Initialize SUMO route provider.
        
        Args:
            traci_connection: Active TraCI connection (traci module or connection object)
                             If None, will attempt to import traci on first use.
        """
        self.traci = traci_connection
        self._net = None  # Cached network for edge lookups
        self._edge_cache = {}  # Cache position -> nearest edge
    
    def _ensure_traci(self):
        """Ensure TraCI connection is available."""
        if self.traci is None:
            try:
                import traci
                self.traci = traci
            except ImportError:
                raise RuntimeError("TraCI not available. Install SUMO or use EuclideanRouteProvider.")
    
    def _get_nearest_edge(self, position: Tuple[float, float]) -> Optional[str]:
        """
        Find the nearest edge to a given position.
        
        Note: This converts lat/lon to SUMO coordinates. SUMO uses Cartesian coordinates
        based on the network's projection. For simplicity, we treat lat/lon as x/y.
        In real usage, you may need to use SUMO's geo-conversion utilities.
        
        Args:
            position: (lat, lon) tuple
            
        Returns:
            Edge ID string or None if not found
        """
        self._ensure_traci()
        
        # Check cache first
        cache_key = (round(position[0], 6), round(position[1], 6))
        if cache_key in self._edge_cache:
            return self._edge_cache[cache_key]
        
        try:
            # Convert lat/lon to SUMO x/y coordinates
            # Note: SUMO uses (x, y) where x=lon-based, y=lat-based typically
            # This is a simplified conversion - real usage should use traci.simulation.convertGeo
            x, y = position[1], position[0]  # lon, lat -> x, y
            
            # Use TraCI to find nearest edge
            # traci.simulation.convertRoad returns (edgeID, pos, laneIndex, ...)
            result = self.traci.simulation.convertRoad(x, y, isGeo=False)
            if result:
                edge_id = result[0]
                self._edge_cache[cache_key] = edge_id
                return edge_id
        except Exception:
            pass
        
        return None
    
    def get_route_distance(self, from_pos: Tuple[float, float],
                           to_pos: Tuple[float, float]) -> float:
        """
        Calculate distance using SUMO's routing.
        
        Args:
            from_pos: Starting position as (lat, lon) tuple
            to_pos: Destination position as (lat, lon) tuple
            
        Returns:
            Distance in kilometers, or fallback Euclidean if route not found
        """
        info = self.get_route_info(from_pos, to_pos)
        return info.get('distance_km', 0.0)
    
    def get_route_info(self, from_pos: Tuple[float, float],
                       to_pos: Tuple[float, float]) -> dict:
        """
        Get detailed route info using SUMO TraCI.
        
        Args:
            from_pos: Starting position as (lat, lon)
            to_pos: Destination position as (lat, lon)
            
        Returns:
            Route info dictionary
        """
        self._ensure_traci()
        
        default_result = {
            'distance_km': self._euclidean_distance_km(from_pos, to_pos),
            'edges': [],
            'travel_time': 0.0,
            'fallback': True
        }
        
        try:
            from_edge = self._get_nearest_edge(from_pos)
            to_edge = self._get_nearest_edge(to_pos)
            
            if not from_edge or not to_edge:
                return default_result
            
            if from_edge == to_edge:
                # Same edge - return small distance
                return {
                    'distance_km': 0.01,
                    'edges': [from_edge],
                    'travel_time': 1.0,
                    'fallback': False
                }
            
            # Use TraCI findRoute
            # Returns a Stage object with: type, vType, line, destStop, edges, 
            #                             travelTime, cost, length, intended, depart
            stage = self.traci.simulation.findRoute(from_edge, to_edge)
            
            if stage and hasattr(stage, 'length'):
                return {
                    'distance_km': stage.length / 1000.0,  # meters to km
                    'edges': list(stage.edges) if hasattr(stage, 'edges') else [],
                    'travel_time': stage.travelTime if hasattr(stage, 'travelTime') else 0.0,
                    'fallback': False
                }
        except Exception as e:
            # Log error in debug mode
            pass
        
        return default_result
    
    def _euclidean_distance_km(self, pos1: Tuple[float, float],
                               pos2: Tuple[float, float]) -> float:
        """Fallback Euclidean distance calculation."""
        if not pos1 or not pos2:
            return 0.0
        lat1, lon1 = pos1
        lat2, lon2 = pos2
        
        lat_diff = (lat2 - lat1) * 111.0
        lon_diff = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
        
        return math.sqrt(lat_diff ** 2 + lon_diff ** 2)


class EuclideanRouteProvider(RouteProvider):
    """
    Simple Euclidean distance provider for testing without SUMO.
    Converts lat/lon differences to approximate km distances.
    """
    
    def get_route_distance(self, from_pos: Tuple[float, float],
                           to_pos: Tuple[float, float]) -> float:
        """
        Calculate approximate distance using Euclidean formula.
        
        Uses simple conversion where 1 degree ≈ 111 km.
        Good for small distances and testing.
        
        Args:
            from_pos: Starting position as (lat, lon)
            to_pos: Destination position as (lat, lon)
            
        Returns:
            Distance in kilometers
        """
        if not from_pos or not to_pos:
            return 0.0
            
        lat1, lon1 = from_pos
        lat2, lon2 = to_pos
        
        # Approximate km conversion
        lat_diff = (lat2 - lat1) * 111.0
        lon_diff = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
        
        return math.sqrt(lat_diff ** 2 + lon_diff ** 2)
    
    def get_route_info(self, from_pos: Tuple[float, float],
                       to_pos: Tuple[float, float]) -> dict:
        """
        Get route info (limited for Euclidean provider).
        
        Returns:
            Basic route info with distance only
        """
        distance = self.get_route_distance(from_pos, to_pos)
        
        # Estimate travel time assuming 50 km/h average speed
        travel_time = (distance / 50.0) * 3600.0  # hours to seconds
        
        return {
            'distance_km': distance,
            'edges': [],
            'travel_time': travel_time,
            'fallback': True
        }


# Singleton instance for easy access
_default_provider: Optional[RouteProvider] = None


def get_route_provider() -> RouteProvider:
    """
    Get the default route provider instance.
    Returns EuclideanRouteProvider if no SUMO connection configured.
    """
    global _default_provider
    if _default_provider is None:
        _default_provider = EuclideanRouteProvider()
    return _default_provider


def set_route_provider(provider: RouteProvider):
    """
    Set the default route provider.
    Call this during simulation setup to inject SUMO TraCI provider.
    
    Args:
        provider: RouteProvider instance to use
    """
    global _default_provider
    _default_provider = provider
    
    # Also update Node class's route_provider
    from src.core.node import Node
    Node.route_provider = provider


def configure_sumo_routing(traci_connection):
    """
    Convenience function to configure SUMO-based routing.
    
    Args:
        traci_connection: Active TraCI connection (typically the traci module
                         after traci.start() has been called)
    """
    provider = SUMORouteProvider(traci_connection)
    set_route_provider(provider)

