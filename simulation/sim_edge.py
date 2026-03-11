"""
SimEdge -- Non-threaded Edge for TraCI simulation.

Bypasses Edge.__init__ (which unconditionally spawns a background thread)
and instead computes parameters on demand via refresh().
"""

from vehicle.edge import Edge


class SimEdge(Edge):
    """Edge that computes parameters on demand instead of in a thread."""

    def __init__(self, source, destination):
        # Skip Edge.__init__ entirely -- it spawns a thread unconditionally.
        self.source = source
        self.destination = destination
        self.distance = 0
        self.transfer_efficiency = 0
        self.energy_loss = 0.0
        self.edge_cost = 0
        self._running = False
        self.refresh()

    def refresh(self):
        """Recompute edge parameters (same math as Edge.update_parameters)."""
        self.distance = self.get_distance()
        self.transfer_efficiency = self.calculate_transfer_efficiency()
        self.energy_loss = self.energy_loss_percentage(self.distance)
        self.edge_cost = self.calculate_cost()

    def stop(self):
        """No-op -- there is no background thread to stop."""
        pass
