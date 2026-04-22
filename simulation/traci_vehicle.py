"""
TraciVehicle -- Vehicle subclass for live TraCI mode.

Position is pushed externally by the orchestrator each SUMO step.
Thread count is minimized: only process_messages runs in a thread.
Battery drain and status broadcasts are driven from the main loop.
"""

import time

from vehicle.vehicle import Vehicle
from simulation.sim_edge import SimEdge
from protocol.messages import STATUS_message


class TraciVehicle(Vehicle):
    """Vehicle whose position is driven by TraCI (sumo-gui)."""

    def __init__(self, time_scale=1.0, charge_soc_target=0.5,
                 charge_cooldown_s=300.0, max_charge_demand_kwh=20.0, **kwargs):
        super().__init__(**kwargs)
        self._time_scale = time_scale
        self._last_tick = time.monotonic()
        self._last_status = 0.0
        self._charge_requested = False
        self._last_charge_sim_time = 0.0
        self._charge_soc_target = charge_soc_target
        self._charge_cooldown_s = charge_cooldown_s
        self._max_charge_demand_kwh = max_charge_demand_kwh

    # --- Thread overrides (reduce from 3 threads to 1) -------------------

    def start_threads(self):
        """Only start process_messages thread. Skip tick and status_update."""
        import threading
        t = threading.Thread(target=self.process_messages, args=(), daemon=True)
        t.start()
        return True

    def tick(self, time_step_s=1):
        """No-op -- battery drain is handled by sim_tick() from main loop."""
        pass

    def status_update_message(self):
        """No-op -- status broadcasts are handled by maybe_send_status()."""
        pass

    # --- Main-loop-driven methods ----------------------------------------

    def sim_tick(self, now, sim_time=0.0):
        """Drain battery and fire organic charge requests. Called from main loop."""
        dt = now - self._last_tick
        self._last_tick = now
        driving_load_kw = 15.0 if self.velocity > 0 else 0.1
        self.drain_power(driving_load_kw, duration_s=dt * self._time_scale)

        if (self.platoon is not None
                and not self.is_leader
                and not self._charge_requested
                and sim_time - self._last_charge_sim_time >= self._charge_cooldown_s):
            target_kwh = self._charge_soc_target * self.battery_capacity()
            if self.available_energy() < target_kwh:
                demand = min(target_kwh - self.available_energy(),
                             self._max_charge_demand_kwh)
                self.request_power(demand)
                self._charge_requested = True
                self._last_charge_sim_time = sim_time

    def maybe_send_status(self, now):
        """Send STATUS broadcast if 20s elapsed and vehicle is in a platoon."""
        if self.platoon and (now - self._last_status) >= 20.0:
            self._last_status = now
            msg = STATUS_message(self)
            self.platoon.broadcast(self, msg)

    def refresh_edges(self):
        """Recompute parameters on all SimEdge connections."""
        for edge in self.connections_list.values():
            if hasattr(edge, 'refresh'):
                edge.refresh()

    # --- Connection override (use SimEdge instead of Edge) ---------------

    def add_connection(self, vehicle):
        """Use SimEdge (no thread) instead of Edge (spawns a thread)."""
        if vehicle not in self.connections_list:
            self.connections_list[vehicle] = SimEdge(self, vehicle)
        return True

    # --- Position update (unchanged) -------------------------------------

    def update_position(self, x, y, speed, angle):
        """Called by traci_runner each simulation step."""
        self.gps.latitude = x
        self.gps.longitude = y
        self.velocity = speed
        self.gps.heading = angle
