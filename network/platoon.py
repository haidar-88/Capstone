from network import network

class Platoon:
    """
    Represents a Platoon of vehicles
    """

    def __init__(self, id):
        self.platoon_id = id
        self.vehicles = []
        self.vehicle_number = 0
        self.max_vehicles = 6
        self.total_energy_demand = 0
        self.available_charger_power = 0
        self.platoon_mobility_pattern = self.calculate_mobility_pattern() #(Expected length of time the platoon stays together)

        self.network = network.Network()

    def broadcast(self, sender, message):
        for vehicle in self.vehicles:
            if vehicle.vehicle_id != sender.vehicle_id:
                vehicle.receive_message(message)

    def calculate_mobility_pattern():
        return 0

    def can_add_vehicle(self):
        return self.max_vehicles > self.vehicle_number

    def add_vehicle(self, vehicle):
        if not self.can_add_vehicle():
            print(f"MAX vehicleS IN PLATOONS REACHED CAN'T ADD MORE CARS TO THE PLATOON WITH ID: {self.platoon_id}")
            return False
        self.vehicle_number = self.vehicle_number + 1
        self.vehicles.append(vehicle)
        self.update_available_charger_power(vehicle.available_energy())
        return True

    def remove_vehicle(self, vehicle):
        if not vehicle in self.vehicles:
            return False
        self.vehicle_number = self.vehicle_number - 1
        self.vehicles.pop(vehicle)
        self.update_available_charger_power(vehicle.available_energy())
        return True
    
    def update_available_charger_power(self, power):
        self.available_charger_power = self.available_charger_power + power
        return True

    def update_total_energy_demand(self, request):
        self.total_energy_demand = self.total_energy_demand + request
        return True
    
    def __str__(self):
        vehicle_ids = [getattr(vehicle, "vehicle_id", "N/A") for vehicle in self.vehicles]

        return (
            f"Platoon Status:\n"
            f"----------------\n"
            f"Platoon ID            : {self.platoon_id}\n"
            f"vehicles in platoon      : {self.vehicle_number}/{self.max_vehicles}\n"
            f"vehicle IDs              : {vehicle_ids}\n"
            f"Total energy demand   : {self.total_energy_demand:.2f} kWh\n"
            f"Available charger pow : {self.available_charger_power:.2f} kW\n"
            f"Mobility pattern time : {self.platoon_mobility_pattern}"
        )