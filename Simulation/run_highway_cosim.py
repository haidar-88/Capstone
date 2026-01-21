#!/usr/bin/env python3
"""
MVCCP Highway Co-Simulation Runner

This script runs a complete SUMO + ns-3 + MVCCP co-simulation on the highway scenario.

Features:
- 20+ vehicles with varying battery states
- 2 RREHs at fixed positions (km 3 and km 7)
- Automatic role assignment (Consumer/PlatoonHead) based on energy
- Protocol message logging and statistics

Usage:
    # Full co-simulation (requires ns-3 with Python bindings)
    python Simulation/run_highway_cosim.py

    # SUMO-only mode with mock networking (for testing without ns-3)
    python Simulation/run_highway_cosim.py --mock-ns3

    # Use SUMO-GUI for visualization
    python Simulation/run_highway_cosim.py --gui

    # Custom duration
    python Simulation/run_highway_cosim.py --duration 600

Requirements:
    - SUMO installed with TraCI (pip install traci sumolib)
    - ns-3 with Python bindings (optional, use --mock-ns3 without)
    - MVCCP protocol package (this repository)
"""

import argparse
import logging
import os
import struct
import sys
from pathlib import Path
from typing import Dict, Optional, List, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import SUMO tools
try:
    import traci
    import sumolib
    TRACI_AVAILABLE = True
except ImportError:
    TRACI_AVAILABLE = False
    print("Warning: traci/sumolib not available - install with: pip install traci sumolib")

# Import ns-3 (optional)
try:
    # ns-3 with cppyy bindings uses 'from ns import ns' pattern
    from ns import ns as ns3
    NS3_AVAILABLE = True
except ImportError:
    NS3_AVAILABLE = False
    ns3 = None

# Import MVCCP components
from Simulation.cosim_orchestrator import CoSimOrchestrator
from Simulation.route_provider import (
    RouteProvider, SUMORouteProvider, EuclideanRouteProvider,
    configure_sumo_routing, get_route_provider
)
from src.protocol.config import ProtocolConfig
from src.protocol.node_registry import register_node, get_node_name

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('highway_cosim')


# =============================================================================
# Vehicle Configuration
# =============================================================================

# Battery configurations by vehicle prefix (kWh)
VEHICLE_BATTERY_CONFIG = {
    'veh_low': {'min': 20.0, 'max': 35.0, 'willingness': 2},
    'veh_mid': {'min': 45.0, 'max': 60.0, 'willingness': 4},
    'veh_high': {'min': 70.0, 'max': 90.0, 'willingness': 6},
}

# RREH configurations (fixed positions on 1km highway)
RREH_CONFIG = [
    {
        'id': 'rreh_0',
        'position': (300.0, 105.0),   # 300m on highway (near west)
        'available_power': 150.0,      # kW
        'max_sessions': 4,
        'renewable_fraction': 1.0,
    },
    {
        'id': 'rreh_1', 
        'position': (700.0, 105.0),   # 700m on highway (near east)
        'available_power': 200.0,      # kW
        'max_sessions': 6,
        'renewable_fraction': 0.85,
    },
]

# Destination for all vehicles (west end of 1km highway)
# y=105.0 places destination on westbound lanes for proper SUMO edge resolution
DESTINATION = (0.0, 105.0)

# =============================================================================
# ns-3 Application Factory
# =============================================================================

def create_ns3_application(node_id: bytes, ns3_node, is_rreh: bool = False):
    """
    Create a real MVCCPApplication using ns-3.
    
    Args:
        node_id: 6-byte node identifier
        ns3_node: ns-3 Node object
        is_rreh: True if this is an RREH node
    
    Returns:
        MVCCPApplication instance
    """
    from Simulation.ns3_adapter import MVCCPApplication
    return MVCCPApplication(node_id, ns3_node, is_rreh)



# =============================================================================
# Highway Co-Simulation Runner
# =============================================================================

class HighwayCosimRunner:
    """
    Main runner for the highway co-simulation scenario.
    Requires ns-3 with Python bindings for protocol execution.
    """
    
    def __init__(self, 
                 use_gui: bool = False,
                 duration: float = 300.0,
                 step_size: float = 0.5):
        """
        Initialize the co-simulation runner.
        
        Args:
            use_gui: If True, use sumo-gui instead of sumo
            duration: Simulation duration in seconds
            step_size: SUMO step size in seconds
        """
        self.use_gui = use_gui
        self.duration = duration
        self.step_size = step_size
        
        # Paths
        self.scenario_dir = PROJECT_ROOT / "Simulation" / "scenarios" / "sumo_files" / "highway"
        self.sumo_config = self.scenario_dir / "highway.sumocfg"
        
        # State
        self.orchestrator: Optional[CoSimOrchestrator] = None
        self.mvccp_apps: Dict[str, 'MVCCPApplication'] = {}  # From ns3_adapter
        self.ns3_nodes = None
        
        # Statistics
        self.stats = {
            'total_ticks': 0,
            'role_changes': 0,
            'platoons_formed': 0,
        }
    
    def setup(self):
        """Set up the co-simulation environment."""
        logger.info("=" * 60)
        logger.info("MVCCP Highway Co-Simulation Setup")
        logger.info("=" * 60)
        
        # Validate SUMO files
        if not self.sumo_config.exists():
            raise FileNotFoundError(f"SUMO config not found: {self.sumo_config}")
        
        logger.info(f"SUMO config: {self.sumo_config}")
        logger.info(f"Duration: {self.duration}s")
        logger.info(f"Step size: {self.step_size}s")
        
        # Create orchestrator
        self.orchestrator = CoSimOrchestrator(step_size=self.step_size)
        
        # Require ns-3
        if not NS3_AVAILABLE:
            raise RuntimeError(
                "ns-3 Python bindings not available. "
                "Install ns-3 with Python support to run the simulation."
            )
        self._setup_ns3_network()
        
        # Create RREH applications
        self._create_rreh_applications()
        
        logger.info("Setup complete")
    
    def _setup_ns3_network(self):
        """Set up ns-3 network with 802.11p WiFi."""
        logger.info("Setting up ns-3 network...")
        
        # This would set up:
        # - NodeContainer for vehicles
        # - 802.11p (WAVE) WiFi configuration
        # - YansWifiChannel with propagation loss model
        # - Mobility models linked to SUMO positions
        
        # Note: Full ns-3 setup requires ns-3 Python bindings
        # The MVCCPApplication from ns3_adapter.py handles the protocol
        
        self.orchestrator.initialize_ns3()
        logger.info("✓ ns-3 network initialized")
    
    def _create_rreh_applications(self):
        """Create MVCCP applications for RREHs."""
        logger.info("Creating RREH applications...")
        
        for rreh_cfg in RREH_CONFIG:
            rreh_id = rreh_cfg['id']
            node_id = self._generate_node_id(rreh_id)
            
            # Create ns-3 node and MVCCP application
            ns3_node = self.orchestrator.create_ns3_node(rreh_id)
            app = create_ns3_application(node_id, ns3_node, is_rreh=True)
            
            # Configure RREH
            app.proxy_node.latitude = rreh_cfg['position'][1]
            app.proxy_node.longitude = rreh_cfg['position'][0]
            app.proxy_node.battery_energy_kwh = rreh_cfg['available_power']
            
            self.mvccp_apps[rreh_id] = app
            self.orchestrator.add_mvccp_application(rreh_id, app)
            
            # Register node name for logging
            register_node(node_id, rreh_id)
            
            logger.info(f"  ✓ {rreh_id} @ ({rreh_cfg['position'][0]:.0f}, {rreh_cfg['position'][1]:.0f})")
    
    def _generate_node_id(self, vehicle_id: str) -> bytes:
        """Generate a 6-byte node ID from vehicle ID string."""
        # Use hash of vehicle ID to generate consistent node ID
        import hashlib
        h = hashlib.md5(vehicle_id.encode()).digest()
        return h[:6]
    
    def _get_battery_for_vehicle(self, vehicle_id: str) -> Tuple[float, int]:
        """
        Get battery energy and willingness for a vehicle based on its ID prefix.
        
        Returns:
            Tuple of (battery_energy_kwh, willingness)
        """
        import random
        
        for prefix, config in VEHICLE_BATTERY_CONFIG.items():
            if vehicle_id.startswith(prefix):
                # Randomize within range for variety
                energy = random.uniform(config['min'], config['max'])
                return (energy, config['willingness'])
        
        # Default for unknown vehicles
        return (50.0, 3)
    
    def connect_sumo(self):
        """Connect to SUMO and initialize vehicle applications."""
        logger.info("Connecting to SUMO...")
        
        # Build SUMO command
        sumo_binary = "sumo-gui" if self.use_gui else "sumo"
        sumo_cmd = [
            sumo_binary,
            "-c", str(self.sumo_config),
            "--step-length", str(self.step_size),
            "--start",  # Start immediately
            "--quit-on-end",  # Quit when simulation ends
        ]
        
        # Start SUMO with TraCI
        traci.start(sumo_cmd)
        self.orchestrator.sumo_connected = True
        
        logger.info(f"✓ Connected to SUMO ({sumo_binary})")
        
        # Configure SUMO-based routing for accurate road network distances
        configure_sumo_routing(traci)
        # Note: Route provider is now set on the real Node class
        from src.core.node import Node
        Node.route_provider = SUMORouteProvider(traci)
        logger.info("✓ SUMO route provider configured")
    
    def initialize_vehicles(self):
        """Initialize MVCCP applications for vehicles in SUMO."""
        logger.info("Waiting for vehicles to spawn...")
        
        # Step a few times to let vehicles enter
        for _ in range(10):
            traci.simulationStep()
        
        # Get all vehicles currently in simulation
        vehicle_ids = traci.vehicle.getIDList()
        logger.info(f"Found {len(vehicle_ids)} vehicles in SUMO")
        
        for veh_id in vehicle_ids:
            self._create_vehicle_application(veh_id)
    
    def _create_vehicle_application(self, vehicle_id: str):
        """Create MVCCP application for a SUMO vehicle."""
        if vehicle_id in self.mvccp_apps:
            return  # Already created
        
        node_id = self._generate_node_id(vehicle_id)
        battery, willingness = self._get_battery_for_vehicle(vehicle_id)
        
        # Create ns-3 node and MVCCP application
        ns3_node = self.orchestrator.create_ns3_node(vehicle_id)
        app = create_ns3_application(node_id, ns3_node, is_rreh=False)
        
        # Configure vehicle
        app.proxy_node.battery_energy_kwh = battery
        app.proxy_node.willingness = willingness
        app.proxy_node.destination = (DESTINATION[0], DESTINATION[1])
        
        # Get initial position from SUMO
        pos = traci.vehicle.getPosition(vehicle_id)
        app.proxy_node.longitude = pos[0]
        app.proxy_node.latitude = pos[1]
        
        self.mvccp_apps[vehicle_id] = app
        self.orchestrator.add_mvccp_application(vehicle_id, app)
        
        # Register node name for logging
        register_node(node_id, vehicle_id)
        
        role = "PH" if app.context.is_platoon_head() else "C"
        logger.debug(f"  ✓ {vehicle_id} [{role}] E={battery:.1f}kWh W={willingness}")
    
    def run(self):
        """Run the co-simulation."""
        logger.info("=" * 60)
        logger.info("Starting Co-Simulation")
        logger.info("=" * 60)
        
        current_time = 0.0
        step_count = 0
        
        try:
            while current_time < self.duration:
                # Check for new vehicles entering simulation
                for veh_id in traci.vehicle.getIDList():
                    if veh_id not in self.mvccp_apps:
                        self._create_vehicle_application(veh_id)
                
                # Sync positions from SUMO to MVCCP
                self._sync_sumo_to_mvccp()
                
                # Step SUMO
                traci.simulationStep()
                current_time += self.step_size
                step_count += 1
                
                # Tick all MVCCP applications
                for veh_id, app in self.mvccp_apps.items():
                    if veh_id.startswith('rreh') or veh_id in traci.vehicle.getIDList():
                        app.tick(current_time)
                
                # Progress reporting
                if step_count % 20 == 0:  # Every 10 seconds
                    active_vehicles = len(traci.vehicle.getIDList())
                    ph_count = sum(1 for a in self.mvccp_apps.values() if a.context.is_platoon_head())
                    logger.info(f"[t={current_time:.1f}s] Vehicles: {active_vehicles}, PlatoonHeads: {ph_count}")
                
                # Check if simulation should end early
                if traci.simulation.getMinExpectedNumber() <= 0:
                    logger.info("All vehicles have completed their routes")
                    break
                
                self.stats['total_ticks'] += len(self.mvccp_apps)
            
        except traci.exceptions.FatalTraCIError as e:
            logger.error(f"TraCI error: {e}")
        except KeyboardInterrupt:
            logger.info("Simulation interrupted by user")
        
        self.orchestrator.current_time = current_time
        self.orchestrator.steps_completed = step_count
    
    def _sync_sumo_to_mvccp(self):
        """Sync vehicle positions from SUMO to MVCCP applications."""
        for veh_id in traci.vehicle.getIDList():
            if veh_id not in self.mvccp_apps:
                continue
            
            app = self.mvccp_apps[veh_id]
            
            # Get position from SUMO
            pos = traci.vehicle.getPosition(veh_id)
            app.proxy_node.longitude = pos[0]
            app.proxy_node.latitude = pos[1]
            
            # Get speed
            speed = traci.vehicle.getSpeed(veh_id)
            app.proxy_node.velocity = (speed, 0.0)
    
    def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up...")
        
        if traci.isLoaded():
            traci.close()
            logger.info("✓ SUMO connection closed")
    
    def print_statistics(self):
        """Print simulation statistics."""
        logger.info("=" * 60)
        logger.info("Simulation Statistics")
        logger.info("=" * 60)
        
        logger.info(f"Duration: {self.orchestrator.current_time:.1f}s")
        logger.info(f"Steps completed: {self.orchestrator.steps_completed}")
        logger.info(f"Total MVCCP nodes: {len(self.mvccp_apps)}")
        
        # Count by role
        consumers = sum(1 for a in self.mvccp_apps.values() if a.context.is_consumer())
        platoon_heads = sum(1 for a in self.mvccp_apps.values() if a.context.is_platoon_head())
        rrehs = sum(1 for a in self.mvccp_apps.values() if a.is_rreh)
        
        logger.info(f"Final roles: Consumers={consumers}, PlatoonHeads={platoon_heads}, RREHs={rrehs}")
        
        # Energy statistics
        energies = [a.proxy_node.battery_energy_kwh for a in self.mvccp_apps.values() if not a.is_rreh]
        if energies:
            logger.info(f"Battery range: {min(energies):.1f} - {max(energies):.1f} kWh")
        
        # Route provider info
        from src.core.node import Node
        provider = getattr(Node, 'route_provider', None)
        if provider:
            provider_type = "SUMO" if isinstance(provider, SUMORouteProvider) else "Euclidean"
            logger.info(f"Route provider: {provider_type}")
        
        logger.info("=" * 60)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Run MVCCP Highway Co-Simulation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--gui', 
        action='store_true',
        help='Use SUMO-GUI for visualization'
    )
    
    parser.add_argument(
        '--duration', 
        type=float, 
        default=300.0,
        help='Simulation duration in seconds (default: 300)'
    )
    
    parser.add_argument(
        '--step-size', 
        type=float, 
        default=0.5,
        help='SUMO step size in seconds (default: 0.5)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        # Also enable DEBUG for MVCCP protocol loggers
        for logger_name in ['mvccp.layer_a', 'mvccp.layer_b', 'mvccp.consumer', 
                           'mvccp.platoon_head', 'mvccp.layer_d']:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
    
    # Check prerequisites
    if not TRACI_AVAILABLE:
        print("ERROR: TraCI not available. Install with: pip install traci sumolib")
        sys.exit(1)
    
    # Create and run simulation
    runner = HighwayCosimRunner(
        use_gui=args.gui,
        duration=args.duration,
        step_size=args.step_size,
    )
    
    try:
        runner.setup()
        runner.connect_sumo()
        runner.initialize_vehicles()
        runner.run()
        runner.print_statistics()
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Simulation error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        runner.cleanup()
    
    logger.info("Simulation completed successfully")


if __name__ == '__main__':
    main()
