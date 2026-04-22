# MVCCP Capstone — Claude Guide

## Project Overview

Academic capstone project implementing **MVCCP** (Multi-hop VANET Charging Coordination
Protocol) — a wireless energy transfer coordination protocol for electric vehicle platoons.
Vehicles discover each other, form platoons, and negotiate energy transfer over a DSRC
radio network. The simulation runs over real Cologne, Germany traffic data (TAPASCologne)
using SUMO and the TraCI API.

## How to Run

### Prerequisites

```bash
sudo apt install sumo sumo-gui sumo-tools
pip install -r requirements.txt   # traci >= 1.18.0
```

The TAPASCologne dataset must be present at `TAPASCologne-0.32.0/` in the project root.

### Main simulation (SUMO GUI)

```bash
python -m simulation.traci_runner
```

Opens SUMO-GUI, warms up until ≥150 vehicles exist, discovers 10 clusters of up to 6
vehicles, runs the full MVCCP protocol stack over 60 simulated minutes (06:00–07:00).
Charging is triggered organically: each non-leader vehicle autonomously requests power
when its SoC drops below 50%.

### Batch simulation (headless, multi-seed)

```bash
python run_batch.py                                          # all scenarios, 20 seeds each
python run_batch.py --only baseline abualola_low_load        # specific scenarios
python run_batch.py --only baseline --seeds 1               # quick single-seed validation
```

Results are written to `results/<scenario>/seed_<N>/` per seed, with per-scenario
`aggregate.csv` (mean ± std) and a final `results/summary.csv`.

### Standalone test (no SUMO)

```bash
python main.py
```

Creates 6 in-memory vehicles, starts threads, runs the protocol loop — useful for
testing protocol logic without SUMO.

## Module Structure

| Module | Purpose |
|--------|---------|
| `vehicle/` | Vehicle model: battery (`energy_manager.py`), GPS (`gps.py`), wireless edge costs (`edge.py`) |
| `network/` | Neighbor scanning (`inter_discovery.py`), platoon membership (`platoon.py`) |
| `protocol/` | MVCCP messages (`messages.py`), message dispatcher (`message_handler.py`), leader info table (`info_table.py`) |
| `AI/` | Provider/donor selection logic (`smart_decision.py`, `Smart_Decision.py`) |
| `simulation/` | SUMO/TraCI integration — orchestrator (`traci_runner.py`), config (`sim_config.py`), metrics (`metrics.py`), network adapter (`sim_network.py`), TraCI vehicle (`traci_vehicle.py`) |
| `run_batch.py` | Headless multi-scenario, multi-seed batch runner |
| `TAPASCologne-0.32.0/` | Cologne traffic dataset — **do not modify** |
| `docs/` | Architecture diagrams, protocol definition, benchmark comparisons |

## MVCCP Protocol Layers

- **Layer A — Neighbor Discovery**: HELLO beacons, neighbor table, QoS-OLSR MPR selection
- **Layer B — Provider Announcements**: PA / GRID_STATUS messages, dedup cache, MPR forwarding
- **Layer C — Charging Coordination**: Role manager (Consumer / PlatoonHead / RREH), JOIN handshake, energy negotiation
- **Layer D — Platoon Coordination**: Position beacons, formation optimization via Dijkstra energy paths

**Protocol time is simulation-time only** — all protocol logic uses `MVCCPContext.current_time`
advanced by `context.update_time(timestamp)`. Never use `time.time()` inside protocol code.

**Forwarding identity**: `MessageHeader.sender_id` is always the **originator ID**.
Forwarders update the `PREVIOUS_HOP` TLV; they never change `sender_id`.

## Environment

- **Python**: 3.13 (system Python, no virtual environment)
- **Key dependency**: `traci >= 1.18.0`
- **OS**: Linux (WSL2)
- **No linter or formatter configured**

## Off-Limits — Ask Before Changing

These files have stable interfaces shared across the team. Modify only after discussion:

- **`protocol/messages.py`** — Defines all MVCCP message types and TLV encodings. Changing
  field names, types, or structure breaks encode/decode symmetry across all handlers.
- **`AI/smart_decision.py`** (and `AI/Smart_Decision.py`) — Provider scoring and selection
  algorithm. Changes affect simulation outcomes and research validity.

## Key Constants and Config (simulation/sim_config.py)

All simulation parameters live in `SimConfig`. Key defaults:

| Parameter | Default | Notes |
|-----------|---------|-------|
| `dsrc_range_m` | 100.0 m | Radio range for neighbor discovery and PDR checks |
| `max_vehicles` | 6 | Max vehicles per platoon |
| `num_clusters` | 10 | Target cluster count |
| `battery_capacity_kwh` | 80.0 kWh | Per vehicle |
| `time_scale` | 60.0 | Simulation speedup factor |
| `sumo_end` | 25200 | 07:00 (1 hour window from 06:00) |
| `charge_soc_target` | 0.5 | SoC fraction that triggers autonomous charge request |
| `charge_cooldown_s` | 300.0 | Min sim-seconds between requests per vehicle |
| `max_charge_demand_kwh` | 20.0 | Cap on demand per session |

`SimConfig.from_dict(d)` ignores unknown keys, so scenario dicts in `run_batch.py` are
safe to have partial overrides.

## Architecture Reference

See `docs/Architecture.md` for full Mermaid diagrams of:
- Co-simulation control plane (SUMO + ns-3 target)
- MVCCP internal layer architecture
- Event ordering sequence
- Intra-platoon edge graph (Dijkstra energy routing)

## Dataset

`TAPASCologne-0.32.0/` — Cologne, Germany morning traffic (06:00–08:00).
Use `cologne6to8.sumocfg` for the 6–8 AM window; `cologne6to8.trips.xml` for routes.
The network file (`cologne.net.xml`, ~73 MB) and trips file (~145 MB) must be present.
