import time
import threading 
import math

class Edge:
    """
    Represents a connection between two Nodes with dynamic energy transfer.
    """

    def __init__(self, source, destination):
        self.source = source
        self.destination = destination
        self.distance = 0  # meters, metadata only
        self.transfer_efficiency = 0
        self.energy_loss = 0.0  # kWh lost in transfer
        self.edge_cost = 0
        t1 = threading.Thread(target=self.update_parameters, args=(), daemon=True)
        t1.start()

    def update_parameters(self):
        while True:
            self.distance = self.get_distance()
            self.transfer_efficiency = self.calculate_transfer_efficiency()
            self.energy_loss = self.energy_loss_percentage(self.distance)
            self.edge_cost = self.calculate_cost()
            time.sleep(1)

    def energy_loss_percentage(self, distance_m, 
                               max_efficiency=0.95, 
                               decay_factor=0.05, 
                               hardware_efficiency=0.9):
        """
        Estimate percentage of energy lost as a function of distance.

        :param distance_m: Distance between source and destination (meters)
        :param max_efficiency: Efficiency at zero distance (0 → 1)
        :param decay_factor: Efficiency decay per meter
        :param hardware_efficiency: Base efficiency of source/destination
        :return: Energy lost as a fraction (0 → 1)

        In wireless charging for batteries, even if your source and receiver are perfectly aligned and right next to each other, you still dont get 100% energy transfer because:

        Coils aren’t perfect → some resistive losses

        Power electronics (inverter/converter) have losses

        Circuitry inefficiencies (AC/DC conversion, rectifiers, etc.)
        """
        total_efficiency = max_efficiency * math.exp(-decay_factor * distance_m) * hardware_efficiency
        percentage_lost = 1.0 - total_efficiency
        return max(0.0, min(percentage_lost, 1.0))

    def get_distance(self):
        return self.source.distance_to(self.destination)
        
    def calculate_transfer_efficiency(self):
        """
        Efficiency ratio (0 → 1) based on node hardware limits.
        Example: ratio of destination max input vs source max output
        """
        source_out = self.source.battery.get_max_transfer_rate_out()
        dest_in = self.destination.battery.get_max_transfer_rate_in()

        efficiency = dest_in / max(source_out, dest_in)
        return min(max(efficiency, 0.0), 1.0)
    
    def calculate_cost(self):
        w1 = 0.3
        w2 = 0.5
        w3 = 0.2
        cost = w1 * self.distance + w2 * self.energy_loss + w3 * self.transfer_efficiency
        return cost