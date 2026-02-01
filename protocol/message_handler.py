class MessageHandler:
    def __init__(self, vehicle):
        self.vehicle = vehicle

    def handle(self, message):
        msg_type = message["type"]

        if msg_type == "PA":
            self.handle_pa(message)

        elif msg_type == "JOIN_OFFER":
            self.handle_join_offer(message)

    def handle_pa(self, msg):
        self.vehicle.provider_table.update(
            msg["provider_id"], msg["energy_available"]
        )

    def handle_join_offer(self, msg):

        needed = msg["needed_energy"]
        consumer_id = msg["consumer_id"]

        if self.vehicle.energy_manager.can_share(needed):
            print(f"{self.vehicle.id} ACCEPTS {consumer_id}")
            self.vehicle.energy_manager.consume(needed)



