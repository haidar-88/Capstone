import math


class Platoon:
    """
    Represents a Platoon of vehicles
    """

    def __init__(self, id, max_vehicles=6):
        self.platoon_id = id
        self.vehicles = []
        self.vehicle_number = 0
        self.max_vehicles = max_vehicles
        self.total_energy_demand = 0
        self.available_charger_power = 0

    def _in_range(self, v1, v2) -> bool:
        dx = v1.gps.latitude - v2.gps.latitude
        dy = v1.gps.longitude - v2.gps.longitude
        return math.sqrt(dx * dx + dy * dy) <= v1.connection_range

    def broadcast(self, sender_id, message):
        sender = next((v for v in self.vehicles if v.vehicle_id == sender_id), None)
        for vehicle in self.vehicles:
            if vehicle.vehicle_id != sender_id:
                if sender is not None and not self._in_range(sender, vehicle):
                    continue
                vehicle.receive_message(message)

    def unicast(self, target_id, message, sender_id=None):
        sender = next((v for v in self.vehicles if v.vehicle_id == sender_id), None) \
                 if sender_id else None
        for vehicle in self.vehicles:
            if vehicle.vehicle_id == target_id:
                if sender is not None and not self._in_range(sender, vehicle):
                    return
                vehicle.receive_message(message)
                return

    def can_add_vehicle(self):
        return self.max_vehicles > self.vehicle_number

    def add_vehicle(self, vehicle):
        if vehicle in self.vehicles:
            return False
        if not self.can_add_vehicle():
            print(f"MAX vehicleS IN PLATOONS REACHED CAN'T ADD MORE CARS TO THE PLATOON WITH ID: {self.platoon_id}")
            return False
        self.vehicle_number = self.vehicle_number + 1
        self.vehicles.append(vehicle)
        vehicle.platoon = self
        self.update_available_charger_power(vehicle.available_energy())
        self.update_total_energy_demand(vehicle.battery_capacity() - vehicle.available_energy())
        return True

    def remove_vehicle(self, vehicle):
        if not vehicle in self.vehicles:
            return False
        self.vehicle_number = self.vehicle_number - 1
        self.vehicles.remove(vehicle)
        self.update_available_charger_power(vehicle.available_energy())
        self.update_total_energy_demand(vehicle.battery_capacity() - vehicle.available_energy())
        return True
    
    def find_provider(self, demand):
        # Basic logic: find first vehicle with enough energy that isn't the leader
        for v in self.vehicles:
            if v.available_energy() > demand:
                return v
        return None
    
    def update_available_charger_power(self, power):
        self.available_charger_power = self.available_charger_power + power
        return True

    def update_total_energy_demand(self, request):
        self.total_energy_demand = self.total_energy_demand + request
        return True
    
    def get_total_energy_available(self):
        return self.available_charger_power
    
    def get_total_energy_demand(self):
        return self.total_energy_demand
    
    def __str__(self):
        vehicle_ids = [getattr(vehicle, "vehicle_id", "N/A") for vehicle in self.vehicles]

        return (
            f"Platoon Status:\n"
            f"----------------\n"
            f"Platoon ID            : {self.platoon_id}\n"
            f"vehicles in platoon   : {self.vehicle_number}/{self.max_vehicles}\n"
            f"vehicle IDs           : {vehicle_ids}\n"
            f"Total energy demand   : {self.total_energy_demand:.2f} kWh\n"
            f"Available charger pow : {self.available_charger_power:.2f} kW\n"
        )