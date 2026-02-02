import math

class GPS:
    """
    Handles position tracking and geodesic calculations (Haversine).
    """
    EARTH_RADIUS_M = 6371000  # Earth's radius in meters

    def __init__(self, latitude=0.0, longitude=0.0, heading=0.0):
        """
        :param latitude: Initial latitude in degrees
        :param longitude: Initial longitude in degrees
        :param heading: Initial direction in degrees (0=North, 90=East)
        """
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.heading = float(heading)

    def get_position(self):
        """Returns tuple (lat, lon)"""
        return (self.latitude, self.longitude)

    def get_distance_to(self, target_lat, target_lon):
        """
        Calculates distance in METERS to a target coordinate tuple 
        using the Haversine formula.
        """
        lat1_rad = math.radians(self.latitude)
        lon1_rad = math.radians(self.longitude)
        lat2_rad = math.radians(target_lat)
        lon2_rad = math.radians(target_lon)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return self.EARTH_RADIUS_M * c

    def update_position(self, speed_mps, time_delta_s):
        """
        Updates the internal latitude/longitude based on speed, heading, and time.
        :param speed_mps: Speed in meters per second
        :param time_delta_s: Time elapsed in seconds
        """
        if speed_mps == 0:
            return

        distance_m = speed_mps * time_delta_s
        angular_distance = distance_m / self.EARTH_RADIUS_M

        lat_rad = math.radians(self.latitude)
        lon_rad = math.radians(self.longitude)
        bearing_rad = math.radians(self.heading)

        new_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(angular_distance) +
            math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
        )

        new_lon_rad = lon_rad + math.atan2(
            math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
            math.cos(angular_distance) - math.sin(lat_rad) * math.sin(new_lat_rad)
        )

        self.latitude = math.degrees(new_lat_rad)
        self.longitude = math.degrees(new_lon_rad)

    @staticmethod
    def kmh_to_mps(kmh):
        return kmh / 3.6
    
    @staticmethod
    def mps_to_kmh(mps):
        return mps * 3.6

    def __str__(self):
        return f"({self.latitude:.6f}, {self.longitude:.6f}) H:{self.heading:.1f}°"