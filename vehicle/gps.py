import math

class GPS:
    """
    Handles 2D Cartesian position tracking for SUMO (x, y in meters).
    """

    EARTH_RADIUS_M = 6371000  # Kept for compatibility (not used)

    def __init__(self, latitude=0.0, longitude=0.0, heading=0.0):
        """
        :param latitude: Used as X coordinate (meters)
        :param longitude: Used as Y coordinate (meters)
        :param heading: Direction in degrees (0 = East, 90 = North)
        """
        self.latitude = float(latitude)    # now represents X
        self.longitude = float(longitude)  # now represents Y
        self.heading = float(heading)

    def get_position(self):
        """Returns tuple (x, y)"""
        return (self.latitude, self.longitude)

    def get_distance_to(self, target_lat, target_lon):
        """
        Calculates Euclidean distance in METERS to a target coordinate.
        """
        dx = target_lat - self.latitude
        dy = target_lon - self.longitude
        return math.sqrt(dx**2 + dy**2)

    def update_position(self, speed_mps, time_delta_s):
        """
        Updates internal x/y based on speed and heading.
        :param speed_mps: Speed in meters per second
        :param time_delta_s: Time elapsed in seconds
        """
        if speed_mps == 0:
            return

        distance = speed_mps * time_delta_s
        heading_rad = math.radians(self.heading)

        # 0° = East, 90° = North (SUMO-style Cartesian)
        self.latitude += distance * math.cos(heading_rad)
        self.longitude += distance * math.sin(heading_rad)

    @staticmethod
    def kmh_to_mps(kmh):
        return kmh / 3.6
    
    @staticmethod
    def mps_to_kmh(mps):
        return mps * 3.6

    def __str__(self):
        return f"(x={self.latitude:.2f}, y={self.longitude:.2f}) H:{self.heading:.1f}°"