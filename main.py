import time
import os
from vehicle.vehicle import Vehicle
from network.platoon import Platoon
from network.inter_discovery import Network

def main():
    # 1. Setup the Network (Range set to 100m)
    net = Network(discovery_range_m=100.0)
    net.start_threads()

    # 2. Setup the Platoon object
    p1 = Platoon("NYC_PLATOON_01")

    # 3. Create 6 Vehicles using your exact __init__ signature
    vehicles = []
    base_lat = 40.0
    base_lon = -74.0

    print("--- Initializing 6 Vehicles ---")
    for i in range(6):
        is_leader = (i == 0)
        
        # Exact arguments from your Vehicle class
        v = Vehicle(
            vehicle_id=f"CAR_{i:02d}",
            battery_capacity_kwh=80.0,
            initial_energy_kwh=70.0 if is_leader else 30.0,
            min_energy_kwh=10.0,
            max_transfer_rate_in=50.0,
            max_transfer_rate_out=50.0,
            latitude=base_lat + (i * 0.0001), # Keeps them within 10-20 meters
            longitude=base_lon,
            heading=0.0,
            velocity=10.0, # m/s
            platoon=None,
            is_leader=is_leader,
            battery_health=1.0
        )
        
        # Hook up the network
        v.network = net
        net.register_vehicle(v)
        
        # Set the first car as the platoon leader so the others have someone to join
        if is_leader:
            p1.add_vehicle(v)
            v.is_platoon_leader = True 
        
        # Fire up the vehicle's internal threads (tick/process_messages)
        v.start_threads()
        vehicles.append(v)

    print("Simulation Running... (Press Ctrl+C to stop)")
    
    # 4. Simulation Loop
    try:
        while True:
            # Clear screen for a clean dashboard view
            #os.system('cls' if os.name == 'nt' else 'clear')
            
            print(f"=== PLATOON: {p1.platoon_id} ===")
            print(f"Members Joined: {p1.vehicle_number}/{p1.max_vehicles}")
            print("-" * 60)
            
            # Show stats for all 6 cars
            for v in vehicles:
                # Check platoon status
                p_status = "LEADER" if v.is_leader else ("MEMBER" if v.platoon else "SCANNING")
                
                # Simple math for battery display
                energy_val = v.battery.energy_kwh
                
                print(f"[{v.vehicle_id}] | {p_status:8} | Bat: {energy_val:.2f} kWh | Pos: ({v.gps.latitude:.5f})")

            # The Network thread will automatically call exchange_hello() 
            # because the cars are close. Your MessageHandler will take it from there.

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nSimulation Terminated.")
        return

if __name__ == "__main__":
    main()