class Node:
    """
    Represents an autonomous vehicle / energy node.
    Battery model uses REAL physical units only.
    """

    def __init__(
            self,
            node_id,
            battery_capacity_kwh,          # Total battery capacity (kWh)
            initial_energy_kwh,            # Current energy (kWh)
            min_energy_kwh,                # Minimum allowed energy (kWh)
            max_transfer_rate_in=50.0,     # Max charge power (kW)
            max_transfer_rate_out=50.0,    # Max discharge power (kW)
            latitude=0.0,
            longitude=0.0,
            velocity=0.0,                  # m/s
            platoon_id=None,
            is_leader=False,
            battery_health=1.0,            # 0.0 → 1.0
        ):
        
        # Identity
        self.node_id = node_id

        # Battery (REAL units)
        self.battery_capacity_kwh = battery_capacity_kwh
        self.battery_energy_kwh = min(initial_energy_kwh, battery_capacity_kwh)
        self.min_energy_kwh = min_energy_kwh

        self.max_transfer_rate_in = max_transfer_rate_in
        self.max_transfer_rate_out = max_transfer_rate_out
        self.battery_health = battery_health

        # GPS & motion
        self.latitude = latitude
        self.longitude = longitude
        self.velocity = velocity

        # Platoon info
        self.platoon_id = platoon_id
        self.is_leader = is_leader

        # Connections
        self.connections_list = []

    def available_energy(self):
        """Energy currently available (kWh)."""
        return self.battery_energy_kwh
    
    def can_transfer(self, power_kw):
        """
        Check if discharge is allowed (1 second assumed).
        """

        if self.battery_health <= 0.0:
            return False

        power_kw = min(power_kw, self.max_transfer_rate_out)

        energy_required = power_kw / 3600.0  # kWh for 1 second

        return (self.battery_energy_kwh - energy_required) >= self.min_energy_kwh
    
    def drain_power(self, power_kw):
        """
        Drain battery assuming EXACTLY 1 second per call.
        power_kw : discharge power (kW)
        """

        if not self.can_transfer(power_kw):
            self.battery_energy_kwh = self.min_energy_kwh
            return False

        power_kw = min(power_kw, self.max_transfer_rate_out)

        energy_used = power_kw / 3600.0  # kWh per second

        self.battery_energy_kwh -= energy_used
        return True

    def charge_power(self, power_kw):
        """
        Charge battery assuming EXACTLY 1 second per call.
        """

        power_kw = min(power_kw, self.max_transfer_rate_in)

        energy_added = power_kw / 3600.0  # kWh

        self.battery_energy_kwh = min(
            self.battery_energy_kwh + energy_added,
            self.battery_capacity_kwh
        )
        return True

    def position(self):
        return (self.latitude, self.longitude)

    def add_connection(self, node):
        if node not in self.connections_list:
            self.connections_list.append(node)
        return True

    def remove_connection(self, node):
        if node in self.connections_list:
            self.connections_list.remove(node)
            return True
        return False


