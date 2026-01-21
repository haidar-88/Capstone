# MVCCP - Multi-hop VANET Charging Coordination Protocol

A decentralized protocol for autonomous electric vehicles (AEVs) operating in a vehicular ad-hoc network (VANET), enabling wireless charging coordination while driving.

## Features

- Neighbor discovery and local topology maintenance (Layer A)
- Provider advertisement for mobile EVs and fixed RREHs (Layer B)
- Charging session negotiation between consumers and providers (Layer C)
- Platoon-based wireless energy transfer while driving (Layer D)

## Prerequisites

### Ubuntu/WSL Installation

#### 1. SUMO (Required)

SUMO (Simulation of Urban MObility) is required for vehicle mobility simulation.

```bash
# Install SUMO from apt
sudo apt-get update
sudo apt-get install sumo sumo-tools

# Set SUMO_HOME environment variable (add to ~/.bashrc)
echo 'export SUMO_HOME="/usr/share/sumo"' >> ~/.bashrc
source ~/.bashrc

# Install Python TraCI bindings
pip install traci sumolib
```

#### 2. ns-3 (Required for Full Simulation)

ns-3 is required for realistic 802.11p (WAVE) network simulation.

```bash
# Install build dependencies
sudo apt-get install git g++ cmake python3-dev python3-pip

# Clone ns-3 (pinned to tested commit for reproducibility)
git clone https://gitlab.com/nsnam/ns-3-dev.git
cd ns-3-dev
git checkout a90c406a09c204a1c8a044521d4b6b49650e5614

# Install cppyy for Python bindings
pip install cppyy

# Configure with Python bindings
./ns3 configure -G "Unix Makefiles" --enable-python-bindings --enable-examples

# Build (this takes a while)
./ns3 build
```

**Important:** Add ns-3 Python bindings to your PYTHONPATH. Add this to your `~/.bashrc` or `~/.zshrc`:

```bash
# Replace /path/to with the actual path to your ns-3-dev directory
export PYTHONPATH="/path/to/ns-3-dev/build/bindings/python:$PYTHONPATH"
```

Then reload your shell: `source ~/.bashrc`

#### 3. Python Dependencies

```bash
pip install -r requirements.txt
```

## Running the Simulation

Ensure your virtual environment is activated and PYTHONPATH is set (see ns-3 installation above).

```bash
cd /path/to/CAPSTONE
source .venv/bin/activate

# Basic run (default 300s)
python Simulation/run_highway_cosim.py

# Custom duration
python Simulation/run_highway_cosim.py --duration 60

# With SUMO GUI visualization
python Simulation/run_highway_cosim.py --gui

# With GUI and custom duration
python Simulation/run_highway_cosim.py --gui --duration 120

# Verbose logging
python Simulation/run_highway_cosim.py -v
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `--gui` | Use SUMO-GUI for visualization |
| `--duration <seconds>` | Simulation duration (default: 300) |
| `--step-size <seconds>` | SUMO step size (default: 0.5) |
| `-v, --verbose` | Enable verbose logging |

## Configuration

### Protocol Parameters

All protocol constants are defined in `src/protocol/config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `HELLO_INTERVAL` | 1.0s | Layer A neighbor discovery interval |
| `PA_INTERVAL` | 5.0s | Provider announcement interval |
| `BEACON_INTERVAL` | 2.0s | Platoon beacon interval |
| `NEIGHBOR_TIMEOUT` | 5.0s | Stale neighbor removal timeout |
| `PLATOON_MAX_SIZE` | 6 | Maximum vehicles per platoon |
| `PA_TTL_DEFAULT` | 4 | Multi-hop forwarding limit (hops) |
| `ENERGY_CONSUMPTION_RATE` | 0.15 kWh/km | EV energy efficiency |
| `PH_ENERGY_THRESHOLD_PERCENT` | 0.60 | Battery threshold to become Platoon Head |
| `PH_WILLINGNESS_THRESHOLD` | 4 | Minimum willingness to become Platoon Head (0-7) |
| `JOIN_ACCEPT_TIMEOUT` | 5.0s | Consumer waiting for JOIN_ACCEPT |
| `PROVIDER_TIMEOUT` | 10.0s | Stale provider entry removal |

### Vehicle Configuration

Vehicle battery and willingness settings are in `Simulation/run_highway_cosim.py`:

```python
VEHICLE_BATTERY_CONFIG = {
    'veh_low':  {'min': 20.0, 'max': 35.0, 'willingness': 2},  # Low battery vehicles
    'veh_mid':  {'min': 45.0, 'max': 60.0, 'willingness': 4},  # Medium battery
    'veh_high': {'min': 70.0, 'max': 90.0, 'willingness': 6},  # High battery (providers)
}
```

### RREH Configuration

Roadside Renewable Energy Hubs are configured in the same file:

```python
RREH_CONFIG = [
    {
        'id': 'rreh_0',
        'position': (3000.0, 100.0),  # km 3 on highway
        'available_power': 150.0,      # kW
        'max_sessions': 4,
    },
    {
        'id': 'rreh_1',
        'position': (7000.0, 100.0),  # km 7 on highway
        'available_power': 200.0,      # kW
        'max_sessions': 6,
    },
]
```

### ns-3 Network Parameters

802.11p (WAVE) settings are in `Simulation/ns3_adapter.py`:

- **Frequency**: 5.9 GHz (WAVE band)
- **Propagation Model**: Friis free-space
- **TX Power**: 20 dBm (~300m range)
- **MAC Mode**: Ad-hoc (for V2V communication)

## Project Structure

```
CAPSTONE/
├── src/
│   ├── core/
│   │   ├── node.py          # Node representation
│   │   ├── edge.py          # Wireless charging edge model
│   │   └── platoon.py       # Platoon management
│   ├── messages/
│   │   └── messages.py      # All message type definitions
│   └── protocol/
│       ├── config.py        # Protocol constants
│       ├── context.py       # Shared protocol context
│       ├── layer_a/         # Neighbor Discovery (HELLO)
│       ├── layer_b/         # Provider Announcements (PA)
│       ├── layer_c/         # Charging Coordination
│       └── layer_d/         # Platoon Coordination
├── Simulation/
│   ├── run_highway_cosim.py # Main simulation runner
│   ├── cosim_orchestrator.py# SUMO + ns-3 orchestration
│   ├── ns3_adapter.py       # ns-3 integration adapter
│   ├── route_provider.py    # Road network distance calculation
│   └── scenarios/
│       └── sumo_files/      # SUMO network and route files
├── ns-3-dev/                # ns-3 simulator (cloned separately)
├── tests/                   # Unit tests
├── docs/                    # Documentation
└── requirements.txt         # Python dependencies
```

**Note:** The `ns-3-dev/` directory is cloned separately as part of the installation process (see Prerequisites). It is not included in the repository.

## Architecture

### Protocol Layers

```
┌─────────────────────────────────────┐
│  Layer D - Platoon Coordination     │
├─────────────────────────────────────┤
│  Layer C - Charging Coordination    │
├─────────────────────────────────────┤
│  Layer B - Provider Announcements   │
├─────────────────────────────────────┤
│  Layer A - Neighbor Discovery       │
└─────────────────────────────────────┘
```

### Co-Simulation Model

- **SUMO**: Vehicle mobility (position, speed, routes)
- **ns-3**: 802.11p wireless communication (optional)
- **MVCCP**: Protocol logic in Python

The orchestrator steps SUMO at 0.5s intervals while ns-3 processes sub-step packet events.

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## License

[Add license information here]
