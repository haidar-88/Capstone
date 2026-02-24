import time
import os
from vehicle.vehicle import Vehicle
from network.platoon import Platoon
from network.inter_discovery import Network

def main():
    # 1. Setup the Network (Range set to 100m)
    net = Network(discovery_range_m=5.0)
    net.start_threads()

    # 2. Setup the Platoon object
    p1 = Platoon("NYC_PLATOON_01")

    # 3. Create 6 Vehicles using Cartesian coordinates (meters)
    vehicles = []
    base_x = 0.0
    base_y = 0.0
    spacing = 10.0   # 10 meters between vehicles

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
            latitude=base_x + (i * spacing),  # X coordinate (meters)
            longitude=base_y,                 # Y coordinate (meters)
            heading=0.0,                      # 0° = East
            velocity=10.0,                    # m/s
            platoon=None,
            is_leader=is_leader,
            battery_health=1.0
        )

        v.network = net
        net.register_vehicle(v)

        if is_leader:
            p1.add_vehicle(v)
            v.is_leader = True

        v.start_threads()
        vehicles.append(v)

    print("Simulation Running... (Press Ctrl+C to stop)")

    # 4. Simulation Loop
    try:
        while True:

            print(f"=== PLATOON: {p1.platoon_id} ===")
            print(f"Members Joined: {p1.vehicle_number}/{p1.max_vehicles}")
            print("-" * 60)

            for v in vehicles:
                p_status = "LEADER" if v.is_leader else ("MEMBER" if v.platoon else "SCANNING")
                energy_val = v.battery.energy_kwh

                print(
                    f"[{v.vehicle_id}] | {p_status:8} | "
                    f"Bat: {energy_val:.2f} kWh | "
                    f"Pos: (x={v.gps.latitude:.2f}, y={v.gps.longitude:.2f})"
                )

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nSimulation Terminated.")
        return


if __name__ == "__main__":
    main()