from protocol import messages

class MessageHandler:
    def __init__(self, vehicle):
        self.vehicle = vehicle

    def handle(self, message):
        """
        Main dispatcher for incoming messages.
        """
        msg_type = message.get("type")

        # --- Discovery & Joining ---
        if msg_type == "HELLO":
            self.handle_hello(message)
        elif msg_type == "JOIN_OFFER":
            self.handle_join_offer(message)
        elif msg_type == "JOIN_ACCEPT":
            self.handle_join_accept(message)
        elif msg_type == "ACK":
            self.handle_ack(message)

        # --- Energy Trading Handshake ---
        elif msg_type == "CHARGE_RQST":
            self.handle_charge_rqst(message)
        elif msg_type == "CHARGE_RSP":
            self.handle_charge_rsp(message)
        elif msg_type == "CHARGE_SYN":
            self.handle_charge_syn(message)
        elif msg_type == "CHARGE_ACK":
            self.handle_charge_ack(message)
        elif msg_type == "CHARGE_FIN":
            self.handle_charge_fin(message)

        # --- Status & Infrastructure ---
        elif msg_type == "STATUS":
            self.handle_platoon_status(message)
        elif msg_type == "AIM":
            self.handle_aim(message)
        
        else:
            print(f"Unknown message type: {msg_type}")

    # ==========================================
    #           HANDLER IMPLEMENTATIONS
    # ==========================================

    def handle_hello(self, msg):
        """
        5.1 HELLO: Received by a Platoon Member (or Head).
        Action: Check if we can admit new cars. If so, send JOIN_OFFER.
        """
        sender_id = msg["vehicle_id"]
        
        # Only the Platoon Head (or designated recruiter) usually responds
        if self.vehicle.is_platoon_leader and self.vehicle.platoon.can_add_vehicle():
            
            # Construct the offer using your builder function
            response = messages.JOIN_OFFER_message(self.vehicle, sender_id)
            
            # Send unicast back to the specific vehicle
            self.vehicle.unicast(msg["vehicle"], response)
            print(f"[{self.vehicle.vehicle_id}] Sent JOIN_OFFER to {sender_id}")

    def handle_join_offer(self, msg):
        """
        5.2 JOIN_OFFER: Received by the Independent Vehicle.
        Action: Evaluate the platoon offer. If good, send JOIN_ACCEPT.
        """
        platoon_id = msg["platoon_id"]
        
        # Logic to decide if we want to join (based on destination, energy, etc.)
        should_join = self.vehicle.evaluate_platoon_offer(msg)

        if should_join:
            response = messages.JOIN_ACCEPT_message(self.vehicle, platoon_id)
            self.vehicle.unicast(msg["vehicle"], response)
            print(f"[{self.vehicle.vehicle_id}] Accepted offer from Platoon {platoon_id}")

    def handle_join_accept(self, msg):
        """
        5.3 JOIN_ACCEPT: Received by the Platoon Node (Head).
        Action: Add vehicle to platoon registry and send ACK.
        """
        new_member_id = msg["vehicle_id"]
        platoon_id = msg["platoon_id"]
        new_member = msg["vehicle"]

        if msg["accept"]:
            # Logic to add the member to the local platoon structure
            self.vehicle.platoon.add_vehicle(new_member)
            
            # Send 5.4 ACK
            response = messages.ACK_message(platoon_id, new_member_id)
            self.vehicle.unicast(new_member, response)
            print(f"[{self.vehicle.vehicle_id}] Sent ACK to new member {new_member_id}")

    def handle_ack(self, msg):
        """
        5.4 ACK: Received by the Joining Vehicle.
        """
        if msg["vehicle_id"] == self.vehicle.vehicle_id:
            self.vehicle.platoon_id = msg["platoon_id"]
            print(f"[{self.vehicle.vehicle_id}] Joined Platoon {msg['platoon_id']} successfully.")

    def handle_charge_rqst(self, msg):
        """
        5.5 CHARGE_RQST: Received by Platoon Head.
        Action: Match the request with an available provider.
        """
        # Only the Head processes requests to assign a provider
        if self.vehicle.is_platoon_leader:
            consumer_id = msg["vehicle_id"]
            demand = msg["energy_demand_kwh"]

            # Logic to find a suitable provider in the platoon
            provider = self.vehicle.platoon.find_provider(demand)
            
            if provider:
                # 5.6 CHARGE_RSP (Broadcast so both Provider and Consumer see it)
                # Note: 'provider' here implies an object, we need the ID or object depending on your logic
                # Assuming 'provider' is a vehicle object available to the head's logic
                response = messages.CHARGE_RSP_message(provider, demand, transfer_time_s=300) 
                self.vehicle.network.broadcast(response)

    def handle_charge_rsp(self, msg):
        """
        5.6 CHARGE_RSP: Received by All (Broadcast).
        Action: 
        - Provider: Send CHARGE_SYN.
        - Consumer: Prepare to receive.
        """
        provider_id = msg["provider_vehicle_id"]
        
        # If I am the Provider
        if self.vehicle.vehicle_id == provider_id:
            # Send 5.7 SYN to start the handshake
            syn_msg = messages.CHARGE_SYN_message(self.vehicle)
            # Assuming we know who the consumer is (saved from previous state or added to RSP message)
            # For this protocol def, we likely broadcast SYN or target the consumer if known.
            self.vehicle.network.broadcast(syn_msg) 
            print(f"[{self.vehicle.vehicle_id}] Selected as provider. Sending SYN.")

    def handle_charge_syn(self, msg):
        """
        5.7 CHARGE_SYN: Received by Consumer.
        Action: Start physical charging simulation and send ACK.
        """
        # Send 5.8 CHARGE_ACK
        ack_msg = messages.CHARGE_ACK_message(self.vehicle)
        self.vehicle.platoon.unicast(msg["vehicle_id"], ack_msg)
        
        self.vehicle.start_charging_process(msg["vehicle_id"])
        print(f"[{self.vehicle.vehicle_id}] SYN received. Sending ACK and starting charge.")

    def handle_charge_ack(self, msg):
        """
        5.8 CHARGE_ACK: Received by Provider.
        Action: Keep sending energy, update transfer counters.
        """
        # This might happen repeatedly during charging
        if self.vehicle.is_charging_provider:
            self.vehicle.update_energy_transfer(msg["vehicle_id"])
            # If transfer complete:
            # self.vehicle.platoon.unicast(consumer, CHARGE_FIN_message(self.vehicle))

    def handle_charge_fin(self, msg):
        """
        5.9 CHARGE_FIN: Received by Consumer.
        Action: Terminate charging session.
        """
        if self.vehicle.is_charging_consumer:
            self.vehicle.stop_charging_process()
            print(f"[{self.vehicle.vehicle_id}] Charging finished.")

    def handle_platoon_status(self, msg):
        """
        5.10 PLATOON_STATUS: Received by Platoon Head.
        Action: Update the fleet status table.
        """
        if self.vehicle.is_platoon_leader:
            sender_id = msg["vehicle_id"]
            self.vehicle.platoon.update_member_status(
                sender_id, 
                msg["battery_level_percent"], 
                msg["energy_available_kwh"]
            )

    def handle_aim(self, msg):
        """
        5.11 AIM: Infrastructure Message.
        Action: Update local knowledge of nearby charging hubs.
        """
        self.vehicle.navigation.update_infrastructure_info(msg)