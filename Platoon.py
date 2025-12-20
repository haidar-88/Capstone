class Platoon:
    """
    Represents a Platoon of Nodes
    """

    def __init__(self):
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
        self.update_total_energy_demand()
        self.update_available_charger_power()
        return True

    def remove_node(self, node):
        self.node_number = self.node_number - 1
        self.nodes.pop(node)
        self.update_total_energy_demand()
        self.update_available_charger_power()
        return True
    
    def update_available_charger_power(self):
        return

    def update_total_energy_demand(self):
        return