"""
Co-Simulation Orchestrator for MVCCP (SUMO + ns-3)

This module coordinates SUMO mobility simulation with ns-3 network simulation,
ensuring proper time synchronization and state updates.

Architecture:
- SUMO steps at Δt = 0.5s per step
- ns-3 runs sub-step events inside each [t, t+Δt) interval
- MVCCP protocol uses simulation time only (no wall-clock)
- Mobility/energy state synced at SUMO boundaries

Target Usage:
    orchestrator = CoSimOrchestrator(sumo_port=8813, step_size=0.5)
    orchestrator.add_mvccp_application(app)
    orchestrator.run(duration=100.0)  # Run for 100 seconds
"""

try:
    import traci
    _TRACI_AVAILABLE = True
except ImportError:
    _TRACI_AVAILABLE = False
    print("Warning: traci not available - SUMO integration disabled")

try:
    # ns-3 with cppyy bindings uses 'from ns import ns' pattern
    from ns import ns as ns3
    _NS3_AVAILABLE = True
except ImportError:
    _NS3_AVAILABLE = False
    ns3 = None
    print("Warning: ns-3 Python bindings not available")


class CoSimOrchestrator:
    """
    Orchestrator for SUMO + ns-3 + MVCCP co-simulation.
    
    Responsibilities:
    - Step SUMO at fixed intervals (Δt)
    - Run ns-3 until next SUMO boundary
    - Sync mobility/energy from SUMO to MVCCP nodes
    - Call MVCCP tick() at boundaries
    - Preserve sub-step ns-3 packet event times
    """
    
    def __init__(self, sumo_port=8813, step_size=0.5):
        """
        Initialize co-simulation orchestrator.
        
        Args:
            sumo_port: TraCI port for SUMO connection
            step_size: SUMO step size in seconds (default 0.5s)
        """
        self.sumo_port = sumo_port
        self.step_size = step_size
        
        # SUMO connection
        self.sumo_connected = False
        
        # ns-3 simulator reference
        self.ns3_simulator = None
        
        # MVCCP applications (MVCCPApplication instances from ns3_adapter.py)
        # Keyed by SUMO vehicle ID or node identifier
        self.mvccp_apps = {}
        
        # Simulation state
        self.current_time = 0.0
        self.running = False
        
        # Statistics
        self.steps_completed = 0
        self.total_packets = 0
    
    def connect_sumo(self, sumo_config=None, sumo_cmd=None):
        """
        Connect to SUMO via TraCI.
        
        Args:
            sumo_config: Path to SUMO .sumocfg file (if starting SUMO)
            sumo_cmd: Pre-built SUMO command list (e.g., ["sumo", "-c", "scenario.sumocfg"])
        """
        if not _TRACI_AVAILABLE:
            raise RuntimeError("traci module not available - cannot connect to SUMO")
        
        try:
            if sumo_cmd:
                # Start SUMO with provided command
                traci.start(sumo_cmd + ["--remote-port", str(self.sumo_port)])
            elif sumo_config:
                # Start SUMO with config file
                traci.start([
                    "sumo",
                    "-c", sumo_config,
                    "--step-length", str(self.step_size),
                    "--remote-port", str(self.sumo_port)
                ])
            else:
                # Connect to already-running SUMO
                traci.connect(self.sumo_port)
            
            self.sumo_connected = True
            print(f"✓ Connected to SUMO on port {self.sumo_port}")
            
        except Exception as e:
            raise RuntimeError(f"Failed to connect to SUMO: {e}")
    
    def initialize_ns3(self):
        """
        Initialize ns-3 simulator reference.
        
        Note: ns-3 objects (nodes, devices, applications) should be created
        BEFORE calling this method. This just captures the simulator reference.
        """
        if not _NS3_AVAILABLE:
            raise RuntimeError("ns-3 Python bindings not available")
        
        self.ns3_simulator = ns3.Simulator
        self.ns3_node_container = ns3.NodeContainer()
        self.ns3_nodes_by_id = {}  # Map vehicle_id -> ns-3 Node
        print("✓ ns-3 simulator initialized")
    
    def create_ns3_node(self, node_id: str):
        """
        Create an ns-3 Node for a vehicle or RREH.
        
        Args:
            node_id: Unique identifier for the node (SUMO vehicle ID or RREH ID)
            
        Returns:
            ns3.Node: The created ns-3 Node
        """
        if not _NS3_AVAILABLE:
            raise RuntimeError("ns-3 not available - cannot create node")
        
        # Create new node
        node = ns3.Node()
        self.ns3_node_container.Add(node)
        self.ns3_nodes_by_id[node_id] = node
        
        return node

    
    def add_mvccp_application(self, vehicle_id, mvccp_app):
        """
        Register an MVCCP application instance.
        
        Args:
            vehicle_id: SUMO vehicle ID or unique node identifier
            mvccp_app: MVCCPApplication instance from ns3_adapter.py
        """
        self.mvccp_apps[vehicle_id] = mvccp_app
    
    def step(self):
        """
        Execute one co-simulation step.
        
        Order of operations:
        1. Calculate next boundary time (t_next = t + Δt)
        2. Run ns-3 until t_next (sub-step packet events processed)
        3. Step SUMO to t_next
        4. Apply mobility/energy updates from SUMO to MVCCP NodeProxy
        5. Call tick(t_next) on all MVCCP applications
        
        Returns:
            True if step successful, False if simulation should end
        """
        if not self.sumo_connected:
            raise RuntimeError("SUMO not connected - call connect_sumo() first")
        
        # 1. Calculate next boundary
        t_next = self.current_time + self.step_size
        
        # 2. Run ns-3 until t_next (preserves sub-step packet events)
        if _NS3_AVAILABLE and self.ns3_simulator:
            # Use relative time for Stop() - run for step_size seconds from now
            # This ensures sub-step packet events are processed with their exact times
            self.ns3_simulator.Stop(ns3.Seconds(self.step_size))
            self.ns3_simulator.Run()
            # Reset for next step - ns-3 maintains internal time correctly
        
        # 3. Step SUMO to t_next
        if self.sumo_connected:
            traci.simulationStep(t_next)
        
        # 4. Apply mobility/energy updates from SUMO
        self._sync_sumo_to_mvccp(t_next)
        
        # 5. Call tick(t_next) on all MVCCP applications
        for vehicle_id, app in self.mvccp_apps.items():
            try:
                app.tick(t_next)
            except Exception as e:
                print(f"Error in tick() for vehicle {vehicle_id}: {e}")
        
        # Update orchestrator state
        self.current_time = t_next
        self.steps_completed += 1
        
        # Check if SUMO simulation ended
        if self.sumo_connected:
            min_expected_vehicles = traci.simulation.getMinExpectedNumber()
            if min_expected_vehicles <= 0:
                print(f"SUMO simulation ended at t={t_next:.2f}s")
                return False
        
        return True
    
    def _sync_sumo_to_mvccp(self, timestamp):
        """
        Sync mobility and energy state from SUMO to MVCCP NodeProxy instances.

        Args:
            timestamp: Current simulation time
        """
        if not self.sumo_connected:
            return

        # Handle vehicle departures/arrivals first
        self._handle_vehicle_events(timestamp)

        for vehicle_id, app in self.mvccp_apps.items():
            try:
                # Check if vehicle exists in SUMO
                if vehicle_id not in traci.vehicle.getIDList():
                    continue

                # Get position from SUMO (returns (x, y) in SUMO coordinates)
                sumo_pos = traci.vehicle.getPosition(vehicle_id)

                # Convert SUMO coordinates to lat/lon
                lat, lon = self._sumo_to_geo(sumo_pos[0], sumo_pos[1])
                app.proxy_node.latitude = lat
                app.proxy_node.longitude = lon

                # Get speed from SUMO (m/s)
                speed = traci.vehicle.getSpeed(vehicle_id)

                # Get heading angle from SUMO (degrees)
                angle = traci.vehicle.getAngle(vehicle_id)
                # Convert to velocity vector (angle 0 = North, clockwise)
                import math
                rad = math.radians(90 - angle)  # Convert to standard math angle
                vx = speed * math.cos(rad)
                vy = speed * math.sin(rad)
                app.proxy_node.velocity = (vx, vy)

                # Update energy based on distance traveled (simplified model)
                # Energy consumption: ~0.15 kWh/km
                if hasattr(app, '_last_position') and app._last_position:
                    last_x, last_y = app._last_position
                    dist_m = math.sqrt((sumo_pos[0] - last_x)**2 + (sumo_pos[1] - last_y)**2)
                    dist_km = dist_m / 1000.0
                    energy_used = dist_km * 0.15  # kWh/km
                    app.proxy_node.battery_energy_kwh = max(
                        0, app.proxy_node.battery_energy_kwh - energy_used
                    )
                app._last_position = sumo_pos

            except Exception as e:
                print(f"Warning: Failed to sync {vehicle_id} from SUMO: {e}")

    def _sumo_to_geo(self, x: float, y: float):
        """
        Convert SUMO Cartesian coordinates to lat/lon.

        Args:
            x: SUMO x coordinate (meters)
            y: SUMO y coordinate (meters)

        Returns:
            Tuple of (latitude, longitude)
        """
        if self.sumo_connected:
            try:
                # Use SUMO's built-in coordinate conversion
                lon, lat = traci.simulation.convertGeo(x, y, fromGeo=False)
                return (lat, lon)
            except Exception:
                pass

        # Fallback: rough approximation (assumes reference at origin)
        # 1 degree latitude ≈ 111 km
        # 1 degree longitude ≈ 111 km * cos(lat)
        lat = y / 111000.0  # Approximate conversion
        lon = x / 111000.0
        return (lat, lon)

    def _handle_vehicle_events(self, timestamp):
        """
        Handle vehicles entering and leaving the simulation.

        Args:
            timestamp: Current simulation time
        """
        if not self.sumo_connected:
            return

        # Handle newly departed (entered) vehicles
        for veh_id in traci.simulation.getDepartedIDList():
            if veh_id not in self.mvccp_apps:
                self._on_vehicle_depart(veh_id, timestamp)

        # Handle arrived (left) vehicles
        for veh_id in traci.simulation.getArrivedIDList():
            if veh_id in self.mvccp_apps:
                self._on_vehicle_arrive(veh_id, timestamp)

    def _on_vehicle_depart(self, vehicle_id: str, timestamp: float):
        """
        Handle a vehicle entering the simulation.

        Args:
            vehicle_id: SUMO vehicle ID
            timestamp: Current simulation time
        """
        # This is called when a new vehicle appears in SUMO
        # In a full implementation, this would create a new MVCCP application
        # For now, we assume vehicles are pre-registered
        print(f"[t={timestamp:.1f}s] Vehicle {vehicle_id} entered simulation")

    def _on_vehicle_arrive(self, vehicle_id: str, timestamp: float):
        """
        Handle a vehicle leaving the simulation.

        Args:
            vehicle_id: SUMO vehicle ID
            timestamp: Current simulation time
        """
        # Vehicle reached destination or left simulation
        print(f"[t={timestamp:.1f}s] Vehicle {vehicle_id} left simulation")

        # Stop the MVCCP application
        if vehicle_id in self.mvccp_apps:
            app = self.mvccp_apps[vehicle_id]
            try:
                app.StopApplication()
            except Exception:
                pass
            # Optionally remove from tracking
            # del self.mvccp_apps[vehicle_id]
    
    def run(self, duration):
        """
        Run co-simulation for specified duration.
        
        Args:
            duration: Simulation duration in seconds
        """
        if not self.sumo_connected:
            raise RuntimeError("SUMO not connected - call connect_sumo() first")
        
        self.running = True
        self.current_time = 0.0
        
        print("=" * 60)
        print(f"Starting co-simulation (Δt={self.step_size}s, duration={duration}s)")
        print(f"MVCCP nodes: {len(self.mvccp_apps)}")
        print("=" * 60)
        
        try:
            while self.running and self.current_time < duration:
                success = self.step()
                if not success:
                    break
                
                # Progress reporting every 10 steps
                if self.steps_completed % 10 == 0:
                    print(f"[t={self.current_time:.1f}s] Steps: {self.steps_completed}")
            
            print("=" * 60)
            print("Co-simulation completed")
            print(f"Total time: {self.current_time:.2f}s")
            print(f"Total steps: {self.steps_completed}")
            print("=" * 60)
            
        except KeyboardInterrupt:
            print("\nCo-simulation interrupted by user")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources (close SUMO connection, etc.)."""
        if self.sumo_connected:
            try:
                traci.close()
                print("✓ SUMO connection closed")
            except Exception as e:
                print(f"Warning: Error closing SUMO: {e}")
            self.sumo_connected = False
        
        # ns-3 cleanup is handled by ns-3 Simulator::Destroy()
        self.running = False
    
    def get_statistics(self):
        """
        Get orchestrator statistics.
        
        Returns:
            dict: Statistics including steps, time, vehicles
        """
        return {
            'current_time': self.current_time,
            'steps_completed': self.steps_completed,
            'step_size': self.step_size,
            'num_vehicles': len(self.mvccp_apps),
            'running': self.running
        }


# Convenience function for simple scenarios
def create_basic_orchestrator(step_size=0.5):
    """
    Create a basic orchestrator instance with default settings.
    
    Args:
        step_size: SUMO step size in seconds (default 0.5s)
    
    Returns:
        CoSimOrchestrator instance
    """
    orchestrator = CoSimOrchestrator(step_size=step_size)
    return orchestrator
