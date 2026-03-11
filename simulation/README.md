# MVCCP Simulation — SUMO + TraCI Integration

Live traffic simulation of the **Multi-hop VANET Charging Coordination Protocol (MVCCP)** over the TAPASCologne (Cologne, Germany) dataset. Vehicles are spawned by SUMO, clustered into platoons, and run through the full MVCCP protocol stack — neighbor discovery, platoon joining, and wireless energy transfer negotiation — with real-time GUI visualization.

## Architecture

```
┌──────────────────────────────────────────────────┐
│  SUMO-GUI  (TAPASCologne 6:00–6:20 AM traffic)  │
└────────────────────┬─────────────────────────────┘
                     │ TraCI API
                     ▼
┌──────────────────────────────────────────────────┐
│  traci_runner.py  (orchestrator)                 │
│   1. Warmup (500 steps)                          │
│   2. Cluster discovery (17 × 6 vehicles)         │
│   3. Vehicle + platoon initialization            │
│   4. Main loop: position sync, charge triggers   │
└───────┬──────────────┬───────────────────────────┘
        │              │
        ▼              ▼
  SimNetwork      TraciVehicle ──► Platoon
  (neighbor       (battery +       (leader +
   scanning)       position)        members)
        │              │
        └──────┬───────┘
               ▼
    Protocol Stack (MVCCP)
    HELLO → JOIN_OFFER → JOIN_ACCEPT → ACK
    CHARGE_RQST → CHARGE_RSP → SYN → ACK → ENERGY_PACKET → FIN
```

## Module Files

| File | Role |
|------|------|
| `traci_runner.py` | Main orchestrator — cluster discovery, vehicle init, simulation loop, charge triggering |
| `sim_network.py` | `Network` subclass with configurable neighbor scan interval (default ~17 ms for 60x speedup) |
| `traci_vehicle.py` | `Vehicle` subclass whose position is driven externally by TraCI; only battery drain runs locally |
| `__init__.py` | Package init |

## Prerequisites

1. **Python 3.10+**

2. **SUMO** with GUI support:
   ```bash
   sudo apt install sumo sumo-gui sumo-tools
   ```

3. **Python dependencies**:
   ```bash
   pip install -r requirements.txt   # traci >= 1.18.0
   ```

4. **TAPASCologne 0.32.0** dataset — must be present at `TAPASCologne-0.32.0/` relative to the project root. Key files:
   - `cologne6to8.sumocfg` (SUMO config)
   - `cologne.net.xml` (~73 MB network)
   - `cologne.trips.xml` (~145 MB routes)

## How to Run

```bash
cd /path/to/Capstone
python -m simulation.traci_runner
```

The SUMO GUI opens automatically. The simulation runs for a 20-minute simulated window (06:00–06:20) at 60x real-time speedup.

## Simulation Workflow

1. **Launch** — Opens `sumo-gui` via TraCI; waits 10 s for the Cologne map to render
2. **Warmup** — Steps SUMO up to 500 times until >= 150 vehicles exist
3. **Cluster discovery** — Scans all SUMO vehicles for spatial clusters within DSRC range (100 m). Greedily selects up to 17 clusters with max 6 vehicles each
4. **Vehicle initialization** — Creates `TraciVehicle` objects with randomized battery state (15–45 kWh for members, 55 kWh for leaders). Leaders are added to platoons; members join via the HELLO handshake
5. **Main loop** — Each iteration:
   - Advances SUMO by one timestep
   - Syncs positions (x, y, speed, angle) from SUMO to each `TraciVehicle`
   - Updates GUI colors (cluster color if in platoon, red if unassigned)
   - Sleeps 50 ms (~20 fps GUI refresh)
6. **Charge trigger** — After ~30 s wall-clock, the lowest-SOC non-leader in each platoon sends a `CHARGE_RQST` for 20 kWh
7. **Exit** — Ends when SUMO reports no more expected vehicles or the connection closes

## Key Constants

Defined at the top of `traci_runner.py`:

| Constant | Value | Description |
|----------|-------|-------------|
| `_DSRC_RANGE_M` | 100.0 | Radio range for neighbor discovery (meters) |
| `_MAX_VEHICLES` | 6 | Max vehicles per cluster/platoon |
| `_NUM_CLUSTERS` | 17 | Target number of clusters |
| `_BATTERY_CAPACITY_KWH` | 80.0 | Battery capacity per vehicle (kWh) |
| `_MIN_ENERGY_KWH` | 10.0 | Minimum allowed energy (kWh) |
| `_ENERGY_RANGE` | (15.0, 45.0) | Random initial SOC range for members (kWh) |
| `_LEADER_MIN_ENERGY_KWH` | 50.0 | Leader starting energy baseline (kWh) |
| `_TIME_SCALE` | 60.0 | Simulation speedup factor (60x real-time) |
| `_MAX_TRANSFER_RATE_IN` | 50.0 | Max charging power (kW) |
| `_MAX_TRANSFER_RATE_OUT` | 50.0 | Max discharging power (kW) |

## Project Dependencies

The simulation module imports from these internal packages:

| Package | Key Module | Role |
|---------|-----------|------|
| `vehicle/` | `vehicle.py`, `energy_manager.py`, `gps.py`, `edge.py` | Vehicle model with battery, GPS positioning, and edge-cost calculations |
| `network/` | `inter_discovery.py`, `platoon.py` | Neighbor scanning and platoon membership management |
| `protocol/` | `messages.py`, `message_handler.py`, `info_table.py` | MVCCP message builders, dispatcher, and leader info tables |
| `AI/` | `Smart_Decision.py` | Provider selection logic (donor/charger picking) |

## GUI Visualization

- **Vehicle colors**: 17 distinct HSV-spaced hues, one per cluster. Unassigned vehicles appear red
- **Vehicle size**: Tracked vehicles are scaled to 15 m x 5 m (~3.5x real size) for visibility against normal traffic
- **Camera**: Auto-tracks the first cluster's leader at 800x zoom
- **Background traffic**: All other TAPASCologne vehicles render at normal size and default color
