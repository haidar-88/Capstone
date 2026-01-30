class Network:
    def __init__(self):
        self.vehicles = {}

    def register(self, vehicle):
        self.vehicles[vehicle.id] = vehicle

    def broadcast(self, sender, message):
        for v in self.vehicles.values():
            if v.id != sender.id:
                v.receive_message(message)

    def send_to(self, sender, target_id, message):
        if target_id in self.vehicles:
            self.vehicles[target_id].receive_message(message)
