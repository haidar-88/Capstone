class Edge:
    """
    Represents a connection between two Nodes with dynamic energy transfer.
    """

    def __init__(self, source, destination, distance):
        self.source = source
        self.destination = destination
        self.distance = distance  # meters/kilometers, metadata only
        self.transfer_efficiency = self.calculate_transfer_efficiency()
        self.energy_loss = 0.0  # kWh lost in last transfer
        self.expected_transfer_time = 0.0  # seconds, updated dynamically
        self.edge_cost = self.calculate_cost()

    def calculate_transfer_efficiency(self):
        """
        Efficiency ratio (0 → 1) based on node hardware limits.
        Example: ratio of destination max input vs source max output
        """
        source_out = self.source.max_transfer_rate_out
        dest_in = self.destination.max_transfer_rate_in

        efficiency = dest_in / max(source_out, dest_in)
        return min(max(efficiency, 0.0), 1.0)

    def update_expected_transfer_time(self, requested_energy_kwh):
        """
        Calculate expected transfer time for requested energy (kWh)
        based on min(source max out, destination max in)
        """
        max_power = min(self.source.max_transfer_rate_out, self.destination.max_transfer_rate_in)
        if max_power <= 0:
            self.expected_transfer_time = float('inf')  # cannot transfer
        else:
            # time in hours × 3600 = seconds
            self.expected_transfer_time = (requested_energy_kwh / max_power) * 3600.0
        return self.expected_transfer_time
    
    def calculate_cost(self):
        w1 = 0.3
        w2 = 0.5
        w3 = 0.2
        w4 = 0.1
        cost = w1 * self.distance + w2 * self.energy_loss + w3 * self.expected_transfer_time + w4 * self.transfer_efficiency
        return cost