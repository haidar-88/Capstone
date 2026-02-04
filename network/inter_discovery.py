from vehicle import gps
from protocol import messages
import threading

class Network:
    def __init__(self, discovery_range_m=10.0):
        self.all_vehicles = []
        self.discovery_range_m = discovery_range_m

    def start_threads(self):
        t1 = threading.Thread(target=self.scan_for_neighbors, args=())
        t1.start()
        return True

    def register_vehicle(self, vehicle):
        if vehicle not in self.all_vehicles:
            self.all_vehicles.append(vehicle)

    def scan_for_neighbors(self):
        """
        Checks distances between all vehicles. 
        If two vehicles are within range, they 'hear' each other.
        """

        while True:
            for i, v1 in enumerate(self.all_vehicles):
                for v2 in self.all_vehicles[i+1:]:
                    # Calculate distance using the GPS module
                    dist = v1.distance_to(v2.position())
                    
                    if (not v1.is_in_platoon() and v2.is_in_platoon()) and (dist <= self.discovery_range_m):
                        # Trigger automatic HELLO exchange
                        self.exchange_hello(v1, v2)

    def exchange_hello(self, v1, v2):
        """Simulates the wireless handshake when cars get close"""
        # V1 sends HELLO to V2
        msg1 = messages.HELLO_message(v1)
        v2.receive_message(msg1)