import time
from protocol import messages
import threading

class Network:
    def __init__(self):
        self.all_vehicles = []

    def start_threads(self):
        t1 = threading.Thread(target=self.scan_for_neighbors, args=(), daemon=True)
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
            for v1 in self.all_vehicles:
                for v2 in self.all_vehicles:
                    try:
                        if v1 == v2:
                            continue
                        # Calculate distance using the GPS module
                        dist = v1.distance_to(v2)
                        #print(f"Distance between {v1.vehicle_id} and {v2.vehicle_id} is {dist}")
                        if (v1.get_platoon() == None and v2.get_platoon() == None):
                            continue
                        elif (
                                v1.get_platoon() is None and
                                v2.get_platoon() is not None and
                                dist <= v1.connection_range and
                                v2.platoon.platoon_id not in v1.offers and
                                not v2 in v1.hellos_sent
                            ):
                            self.exchange_hello(v1, v2)
                            v1.hellos_sent.add(v2)
                        elif (v1.get_platoon() == v2.get_platoon()):
                            if (dist <= v1.connection_range):
                                v1.add_connection(v2)
                            else:
                                v1.remove_connection(v2)
                    except Exception as e:
                        print('Exception in scan for neighbors: ', e)
            time.sleep(1)            

    def exchange_hello(self, v1, v2):
        """Simulates the wireless handshake when cars get close"""
        # V1 sends HELLO to V2
        msg1 = messages.HELLO_message(v1)
        v2.receive_message(msg1)