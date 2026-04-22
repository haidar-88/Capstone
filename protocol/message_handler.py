from protocol import messages
from AI.smart_decision import pick_a_donor


class MessageHandler:
    def __init__(self, vehicle):
        self.vehicle = vehicle

    def _record(self, msg_type, sender_id):
        """Log a message event to the metrics collector, if attached."""
        m = getattr(self.vehicle, "metrics", None)
        if m is not None:
            m.record_message(msg_type, sender_id,
                             self.vehicle.vehicle_id)
            m.record_delivery(msg_type)

    def _record_send(self, msg_type: str):
        m = getattr(self.vehicle, "metrics", None)
        if m is not None:
            m.record_send_attempt(msg_type)

    def _sim_time(self) -> float:
        """Return current simulation time, or 0 if no metrics attached."""
        m = getattr(self.vehicle, "metrics", None)
        return m.sim_time() if m is not None else 0.0

    def handle(self, message):
        """
        Main dispatcher for incoming messages.
        """
        msg_type = message.get("type")
        self._record(msg_type, message.get("vehicle_id", ""))

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
        elif msg_type == "ENERGY_PACKET":
            self.handle_energy_packet(message)
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
        
        print(f"{sender_id} sent HELLO to {self.vehicle.vehicle_id}")
        # Only the Platoon Head (or designated recruiter) usually responds
        if self.vehicle.platoon is not None and self.vehicle.platoon.can_add_vehicle():

            self._record_send("JOIN_OFFER")
            # Construct the offer using your builder function
            response = messages.JOIN_OFFER_message(self.vehicle, sender_id)
            
            # Send unicast back to the specific vehicle
            self.vehicle.unicast(msg["vehicle"], response)
            print(f"[{self.vehicle.vehicle_id}] Sent JOIN_OFFER to {sender_id}\n")

    def handle_join_offer(self, msg):
        """
        5.2 JOIN_OFFER: Received by the Independent Vehicle.
        Action: Evaluate the platoon offer. If good, send JOIN_ACCEPT.
        """
        platoon_id = msg["platoon_id"]
        
        if platoon_id in self.vehicle.offers: # Discard other offers from same platoon
            return
        
        if self.vehicle.platoon is not None:
            return  # Already joined, ignore
        
        self.vehicle.offers.add(platoon_id)
        
        # Logic to decide if we want to join (based on destination, energy, etc.)
        should_join = self.vehicle.evaluate_platoon_offer(msg)

        if should_join:
            self._record_send("JOIN_ACCEPT")
            response = messages.JOIN_ACCEPT_message(self.vehicle, platoon_id)
            self.vehicle.unicast(msg["vehicle"], response)
            print(f"[{self.vehicle.vehicle_id}] Accepted offer from Platoon {platoon_id}\n")

    def handle_join_accept(self, msg):
        """
        5.3 JOIN_ACCEPT: Received by the Platoon Node
        Action: Add vehicle to platoon registry and send ACK.
        """
        new_member_id = msg["vehicle_id"]
        platoon_id = msg["platoon_id"]
        new_member = msg["vehicle"]

        platoon = self.vehicle.get_platoon()

        if new_member in self.vehicle.platoon.vehicles:
            return  # Already added
        
        if msg["accept"] and platoon.platoon_id == platoon_id:
            self._record_send("ACK")
            # Logic to add the member to the local platoon structure
            self.vehicle.platoon.add_vehicle(new_member)
            
            # Send 5.4 ACK
            response = messages.ACK_message(platoon, new_member_id)
            self.vehicle.unicast(new_member, response)
            print(f"[{self.vehicle.vehicle_id}] Sent ACK to new member {new_member_id}\n")

    def handle_ack(self, msg):
        """
        5.4 ACK: Received by the Joining Vehicle.
        """
        if msg["vehicle_id"] == self.vehicle.vehicle_id:
            platoon = msg["platoon"]
            self.vehicle.join_platoon(platoon)
            self.vehicle.offers.remove(platoon.platoon_id)
            print(f"[{self.vehicle.vehicle_id}] Joined Platoon {msg['platoon']} successfully.\n")
            m = getattr(self.vehicle, "metrics", None)
            if m is not None:
                m.record_platoon_join(self.vehicle.vehicle_id,
                                      platoon.platoon_id, self._sim_time())

    def handle_charge_rqst(self, msg):
        """
        5.5 CHARGE_RQST: Received by Platoon Head.
        Action: Match the request with an available provider.
        """
        # Only the Head processes requests to assign a provider
        if self.vehicle.is_leader:
            consumer_id = msg["vehicle_id"]
            demand = msg["energy_demand_kwh"]

            # Logic to find a suitable provider in the platoon
            provider = pick_a_donor(self.vehicle, demand, exclude_id=consumer_id)

            if provider:
                self._record_send("CHARGE_RSP")
                m = getattr(self.vehicle, "metrics", None)
                if m is not None:
                    m.record_charge_assignment(provider.vehicle_id, consumer_id)
                print(f"Car {provider.vehicle_id} will send {consumer_id} {demand}kwh of energy")
                # 5.6 CHARGE_RSP (Broadcast so both Provider and Consumer see it)
                # Note: 'provider' here implies an object, we need the ID or object depending on your logic
                # Assuming 'provider' is a vehicle object available to the head's logic
                response = messages.CHARGE_RSP_message(provider.vehicle_id, consumer_id, demand) 
                self.vehicle.platoon.broadcast(self.vehicle.vehicle_id, response)

    def handle_charge_rsp(self, msg):
        """
        5.6 CHARGE_RSP: Received by All (Broadcast).
        Action:
        - Consumer: send CHARGE_SYN to the selected provider.
        - Others (including the provider): no-op here; the provider
          reacts to the SYN it receives next.
        """
        provider_id = msg["provider_vehicle_id"]
        consumer_id = msg["consumer_vehicle_id"]
        demand = msg["energy_amount_kwh"]

        # Only the designated consumer initiates the handshake.
        if self.vehicle.vehicle_id == consumer_id:
            self._record_send("CHARGE_SYN")
            syn_msg = messages.CHARGE_SYN_message(self.vehicle, demand)
            self.vehicle.platoon.unicast(provider_id, syn_msg, sender_id=self.vehicle.vehicle_id)
            print(f"Consumer [{self.vehicle.vehicle_id}] sending SYN to provider.")

    def handle_charge_syn(self, msg):
        """
        5.7 CHARGE_SYN: Received by Provider.
        Action: Start physical charging simulation and send ACK.
        """
        consumer_id = msg["vehicle_id"]
        demand = msg["energy_amount_kwh"]
        consumer_max_transfer_rate_in = msg["max_transfer_rate_in"]

        self._record_send("CHARGE_ACK")
        # Send 5.8 CHARGE_ACK
        ack_msg = messages.CHARGE_ACK_message(self.vehicle, 0)
        self.vehicle.platoon.unicast(msg["vehicle_id"], ack_msg, sender_id=self.vehicle.vehicle_id)
        
        print(f"[{self.vehicle.vehicle_id}] SYN received. Sending ACK and starting charge.")
        self.vehicle.start_charging(consumer_id, demand, consumer_max_transfer_rate_in)

    def handle_charge_ack(self, msg):
        """
        5.8 CHARGE_ACK: Received by Provider.
        Action: Keep sending energy, update transfer counters.
        """
        provider_id = msg["vehicle_id"]
        print(f"[{self.vehicle.vehicle_id}] received charging ACK from [{provider_id}]")

    def handle_energy_packet(self, pckt):
        provider_id = pckt["vehicle_id"]
        consumer_id = pckt["consumer_id"]
        packet_nb = pckt["packet_number"]
        energy = pckt["energy_amount_kwh"]
        energy_before = self.vehicle.available_energy()
        self.vehicle.charge_energy(energy)
        actual_received = self.vehicle.available_energy() - energy_before
        m = getattr(self.vehicle, "metrics", None)
        if m is not None and actual_received > 0:
            m.record_energy_received(consumer_id, actual_received)
            m.record_energy_sent(provider_id, actual_received)
            m.record_session_energy(provider_id, consumer_id, actual_received)
        print(f"[{consumer_id}] Charged {energy:.4f} kWh from [{provider_id}]. Packet #{packet_nb}")
        # NOTE: CHARGE_ACK sends are counted at the single emission site
        # inside handle_charge_syn / here; handle_charge_syn records the
        # initial ACK, and this path records one ACK per ENERGY_PACKET.
        self._record_send("CHARGE_ACK")
        ack_msg = messages.CHARGE_ACK_message(self.vehicle, packet_nb)
        self.vehicle.platoon.unicast(provider_id, ack_msg, sender_id=self.vehicle.vehicle_id)

    def handle_charge_fin(self, msg):
        """
        5.9 CHARGE_FIN: Received by Consumer.
        Action: Terminate charging session.
        """
        provider_id = msg["vehicle_id"]
        print(f"Ending Charging. Signaled by FIN mssg from [{provider_id}]")
        if hasattr(self.vehicle, '_charge_requested'):
            self.vehicle._charge_requested = False
        m = getattr(self.vehicle, "metrics", None)
        if m is not None:
            m.record_charge_session_end(provider_id,
                                        self.vehicle.vehicle_id,
                                        self._sim_time())


    def handle_platoon_status(self, msg):
        """
        5.10 PLATOON_STATUS: leader-side aggregation is handled by
        ``InformationTable.update`` from ``Vehicle.process_messages``,
        so the dispatcher path is intentionally a no-op.
        """
        return

    def handle_aim(self, msg):
        """
        5.11 AIM: Infrastructure Message.
        Action: Update local knowledge of nearby charging hubs.
        """
        self.vehicle.navigation.update_infrastructure_info(msg)