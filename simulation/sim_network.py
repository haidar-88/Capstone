"""
SimNetwork — Network subclass with configurable scan interval.

Used by simulation.traci_runner to speed up neighbor discovery without
modifying the parent ``network.inter_discovery.Network`` class.
"""

import time

from network.inter_discovery import Network


class SimNetwork(Network):
    """Network with a tunable scan interval for accelerated replay."""

    def __init__(self, scan_interval=1.0):
        super().__init__()
        self._scan_interval = scan_interval

    def scan_for_neighbors(self):
        """Same logic as parent but sleeps for ``_scan_interval`` instead of 1 s."""
        while True:
            for v1 in self.all_vehicles:
                for v2 in self.all_vehicles:
                    try:
                        if v1 == v2:
                            continue
                        dist = v1.distance_to(v2)
                        if v1.get_platoon() is None and v2.get_platoon() is None:
                            continue
                        elif (
                            v1.get_platoon() is None
                            and v2.get_platoon() is not None
                            and dist <= v1.connection_range
                            and v2.platoon.platoon_id not in v1.offers
                            and v2 not in v1.hellos_sent
                        ):
                            self.exchange_hello(v1, v2)
                            v1.hellos_sent.add(v2)
                        elif v1.get_platoon() == v2.get_platoon():
                            if dist <= v1.connection_range:
                                v1.add_connection(v2)
                            else:
                                v1.remove_connection(v2)
                    except Exception as e:
                        print("Exception in scan for neighbors: ", e)
            time.sleep(self._scan_interval)
