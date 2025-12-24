class Platoon:
    """
    Represents a Platoon of Nodes
    """

    def __init__(self, id):
        self.platoon_id = id
        self.nodes = []
        self.node_number = 0
        self.max_nodes = 6
        self.total_energy_demand = 0
        self.available_charger_power = 0
        self.platoon_mobility_pattern = 0 #(Expected length of time the platoon stays together)

    def can_add_node(self):
        return self.max_nodes < self.node_number

    def add_node(self, node):
        self.node_number = self.node_number + 1
        self.nodes.append(node)
        self.update_available_charger_power(node.battery_energy_kwh)
        return True

    def remove_node(self, node):
        self.node_number = self.node_number - 1
        self.nodes.pop(node)
        self.update_available_charger_power(node.battery_energy_kwh)
        return True
    
    def update_available_charger_power(self, power):
        self.available_charger_power = self.available_charger_power + power
        return True

    def update_total_energy_demand(self, request):
        self.total_energy_demand = self.total_energy_demand + request
        return True
    
    def __str__(self):
        node_ids = [getattr(node, "node_id", "N/A") for node in self.nodes]

        return (
            f"Platoon Status:\n"
            f"----------------\n"
            f"Platoon ID            : {self.platoon_id}\n"
            f"Nodes in platoon      : {self.node_number}/{self.max_nodes}\n"
            f"Node IDs              : {node_ids}\n"
            f"Total energy demand   : {self.total_energy_demand:.2f} kWh\n"
            f"Available charger pow : {self.available_charger_power:.2f} kW\n"
            f"Mobility pattern time : {self.platoon_mobility_pattern}"
        )