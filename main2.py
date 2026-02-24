import time
import os
import random
from vehicle.vehicle import Vehicle
from network.platoon import Platoon
from network.inter_discovery import Network
from protocol import messages


def main():
    # 1. Setup the Network (Range set to 100m)
    net = Network(discovery_range_m=100.0)
    net.start_threads()

    # 2. Setup the Platoon object
    p1 = Platoon("NYC_PLATOON_01")

    # 3. Create 6 Vehicles (NOW USING X,Y IN METERS)
    vehicles = []
    base_x = 0.0      # meters
    base_y = 0.0      # meters
    spacing = 10.0    # 10 meters between vehicles

    print("--- Initializing 6 Vehicles ---")

    for i in range(6):
        is_leader = (i == 0)

        v = Vehicle(
            vehicle_id=f"CAR_{i:02d}",
            battery_capacity_kwh=80.0,
            initial_energy_kwh=70.0 if is_leader else 30.0,
            min_energy_kwh=10.0,
            max_transfer_rate_in=50.0,
            max_transfer_rate_out=50.0,
            connection_range=10 + i,
            latitude=base_x + (i * spacing),   # NOW X coordinate
            longitude=base_y,                  # NOW Y coordinate
            heading=0.0,                       # 0° = East
            velocity=10.0,                     # m/s
            platoon=None,
            is_leader=is_leader,
            battery_health=1.0
        )

        net.register_vehicle(v)

        if is_leader:
            p1.add_vehicle(v)
            v.platoon = p1
            v.is_leader = True

        v.start_threads()
        vehicles.append(v)

    print("\n--- Starting Protocol Sequence ---")

    v1 = vehicles[2]
    v2 = vehicles[3]

    time.sleep(5)

    try:
        v1.send_protocol_message(
            messages.CHARGE_RQST_message,
            v1.vehicle_id,
            20
        )

    except KeyboardInterrupt:
        print("\nSimulation Terminated.")


if __name__ == "__main__":
    main()