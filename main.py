import time
from vehicle.vehicle import Vehicle
from network.platoon import Platoon
from network.inter_discovery import Network

def run_simulation(duration_seconds=30):
    # 1. Setup the Wireless Network (10m discovery range)
    airwaves = Network(discovery_range_m=10.0)

    # 2. Create a Platoon
    highway_platoon = Platoon(id="PLT_Alpha")

    # 3. Initialize Vehicles
    # Car A: Stationary Leader
    leader = Vehicle(
        vehicle_id="Leader_1", 
        battery_capacity_kwh=100, initial_energy_kwh=80, min_energy_kwh=10,
        latitude=33.8938, longitude=35.5018, heading=90, velocity=0,
        is_leader=True, platoon=highway_platoon
    )
    
    # Car B: Moving toward the leader to join
    traveler = Vehicle(
        vehicle_id="Traveler_1", 
        battery_capacity_kwh=75, initial_energy_kwh=15, min_energy_kwh=5,
        latitude=33.8937, longitude=35.5016, heading=90, velocity=2.0 # Moving slowly East
    )

    # Register in the simulation
    highway_platoon.add_vehicle(leader)
    airwaves.register_vehicle(leader)
    airwaves.register_vehicle(traveler)

    print(f"--- Simulation Starting: {duration_seconds}s ---")

    # 4. Main Loop
    for t in range(duration_seconds):
        print(f"\n[TIME: {t}s]")

        # A. Movement & Physics
        for v in airwaves.all_vehicles:
            v.tick(time_step_s=1) # Updates GPS and drains energy
        
        # B. Automated Proximity Discovery
        # If cars get within 10m, Network will force a HELLO exchange
        airwaves.scan_for_neighbors()

        # C. Process Communication
        for v in airwaves.all_vehicles:
            v.process_messages()

        # D. Logic Checks (AI Behavior)
        # If Traveler is low on energy and has discovered a provider, request charge
        if traveler.battery.energy_kwh < 20:
            best_p = traveler.provider_table.get_best_provider()
            if best_p:
                print(f"Traveler_1: Low energy! Found provider {best_p}. Requesting energy...")
                # Logic to trigger protocol 5.5 CHARGE_RQST would go here

        # E. Reporting
        print(leader)
        print(traveler)
        
        time.sleep(0.1) # Speed up simulation for real-time viewing

if __name__ == "__main__":
    run_simulation()