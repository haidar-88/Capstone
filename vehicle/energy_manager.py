class BatteryManager:
    """
    Handles ALL battery and power transfer logic.
    Uses real physical units (kWh, kW, seconds).
    """

    def __init__(
        self,
        capacity_kwh,
        initial_energy_kwh,
        min_energy_kwh,
        max_transfer_rate_in,
        max_transfer_rate_out,
        battery_health=1.0
    ):
        self.capacity_kwh = capacity_kwh
        self.energy_kwh = min(initial_energy_kwh, capacity_kwh)
        self.min_energy_kwh = min_energy_kwh

        self.max_transfer_rate_in = max_transfer_rate_in
        self.max_transfer_rate_out = max_transfer_rate_out
        self.battery_health = battery_health

    # -------------------------
    # STATE QUERIES
    # -------------------------

    def available_energy(self):
        return self.energy_kwh

    def can_transfer(self, power_kw, duration_s=1):
        if self.battery_health <= 0.4:
            return False

        power_kw = min(power_kw, self.max_transfer_rate_out)
        energy_required = (power_kw * duration_s) / 3600.0

        return (self.energy_kwh - energy_required) >= self.min_energy_kwh

    # -------------------------
    # ENERGY FLOW
    # -------------------------

    def drain(self, power_kw, duration_s=1):
        if not self.can_transfer(power_kw, duration_s):
            self.energy_kwh = self.min_energy_kwh
            return False

        power_kw = min(power_kw, self.max_transfer_rate_out)
        energy_used = (power_kw * duration_s) / 3600.0
        self.energy_kwh -= energy_used
        return True

    def charge(self, power_kw, duration_s=1):
        power_kw = min(power_kw, self.max_transfer_rate_in)
        energy_added = (power_kw * duration_s) / 3600.0

        self.energy_kwh = min(self.energy_kwh + energy_added, self.capacity_kwh)
        return True
