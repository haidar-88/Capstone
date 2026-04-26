# MVCCP Benchmark Comparison

Comparison of MVCCP simulation results against the three reference papers whose
parameter sets are encoded as scenarios in `run_batch.py`. Our scenarios use
those papers' vehicle counts, DSRC range, demand, and energy distributions —
**but on Cologne urban traffic instead of their highway / grid topologies**.
This is a same-operating-point comparison, not a superiority claim. See
`docs/METRICS.md` for the full methodology and caveat list.

**Latest results**: `results/latest_summary.md` (run `20260425_183801`).
**Reproduce**: `python run_batch.py --only abualola_low_load abualola_high_load tang2024_urban tang2023_aligned`

All values below are **mean +/- std over 20 random seeds** per scenario.

---

## Reference papers

| Tag | Paper | Role |
|-----|-------|------|
| **P3** | Abualola 2021, *"V2V Charging Allocation over QoS-OLSR"* | Primary benchmark. Same architecture: QoS-OLSR + MPR, provider/consumer allocation, payoff model. Scenarios: `abualola_low_load`, `abualola_high_load`. |
| **P4** | Tang 2024, *"Discharging Driven Energy Sharing"* | Secondary benchmark. Reports P3 numbers as its "V2V-CA" baseline and introduces `min_consumer_soc` (Table 3). Scenario: `tang2024_urban`. |
| **P1** | Tang 2023, *"Dynamic Path-Planning and Charging Optimization"* | **Parameter-alignment only** — targets V2I infrastructure routing rather than V2V peer allocation. Not a charging-allocation benchmark. Scenario: `tang2023_aligned`. |

---

## P3 — Abualola 2021

Paper-reported ranges from Section 6 (NS3 + SUMO, 10 km highway, IEEE 802.11p).
Our values from 20-seed runs on Cologne urban traffic.

| Metric | P3 reported | `abualola_low_load` (ours) | `abualola_high_load` (ours) |
|---|---|---|---|
| Unicast PDR | >90% | 86.4% +/- 2.5% | 86.0% +/- 2.9% |
| E2E delay / RQST-gap | 5-15 ms (MAC layer) | 15.1 +/- 2.0 s | 18.5 +/- 3.8 s |
| Allocation rate | >84%, ~100% at 30% consumers | 55.4% +/- 18.8% | 49.7% +/- 27.5% |
| Jain's fairness index | 0.78-0.92 (SOTA range) | 0.92 +/- 0.04 | 0.79 +/- 0.06 |
| Avg payoff (cents) | within 4.6% of centralized | 111.9 +/- 11.9 | 111.1 +/- 9.0 |
| Charge sessions | not reported | 6.8 +/- 0.4 | 16.8 +/- 2.9 |
| Vehicles tracked | 75-300 sweep | 16 | 45 |
| Min consumer SoC | not reported | 15.4% +/- 4.3% | 13.2% +/- 1.8% |

### Why our numbers differ

1. **Topology**: P3 simulates a 10 km highway — vehicles travel in one direction at
   60-120 km/h and stay within 250 m radio range for extended periods. Cologne urban
   traffic spreads vehicles across a city where they turn at intersections and scatter.
   This directly depresses allocation rate and PDR.

2. **PHY layer**: P3 models IEEE 802.11p channel fading in NS3. MVCCP passes messages
   in-memory with only a range check. Our ~86% PDR comes from **mobility-driven
   out-of-range events** (vehicles physically leaving DSRC range during handshakes),
   not channel loss. See `METRICS.md` Known Limitations.

3. **Scale**: P3 has 75-300 vehicles on a 1D highway (dense). We have 16-45 vehicles
   in 2D urban clusters (sparse). Fewer vehicles means fewer viable donor candidates,
   which depresses allocation rate.

4. **Delay is a different metric**: P3's 5-15 ms is MAC-layer propagation inside NS3.
   Our 15-18 s gap is sim-time from CHARGE_RQST to the first ENERGY_PACKET, covering
   the full protocol handshake (RQST -> RSP -> SYN -> ACK -> ENERGY_PACKET), quantised
   to SUMO's 1-second step. **Do not compare magnitudes** — these measure different things.

5. **Payoff formula matches** P3 Equation 3 (`(sell - buy) * energy - time * duration`),
   but parameter magnitudes differ (their prices: 10-20 cents/kWh). Directionally consistent.

---

## P4 — Tang 2024

Tang 2024 uses NS2 on a 2000 m x 2000 m grid with 500 m-spaced intersections.
Their dataset is **confidential** (stated in the paper), so only the metric
framework is comparable.

| Metric | P4 reported | `tang2024_urban` (ours) |
|---|---|---|
| Unicast PDR | >95% (100 vehicles, 35 km/h) | 85.7% +/- 2.9% |
| E2E delay | 1-2 s | 20.3 +/- 4.0 s |
| Allocation rate | >95% (DDES, balanced weights) | 29.9% +/- 14.7% |
| Min consumer SoC | Fig 13, varies with DEV/CEV % | 12.5% +/- 0.0% |
| Avg payoff (cents) | not directly reported | 70.2 +/- 1.4 |
| Jain's fairness index | not reported | 0.82 +/- 0.01 |
| Charge sessions | not reported | 15.8 +/- 3.1 |
| Vehicles | 100-350 | 45 |

### Why our numbers differ

Same topology/PHY reasons as P3, plus:

1. **Confidential dataset**: we cannot reproduce P4's exact scenario. `tang2024_urban`
   uses their published parameters (250 m range, 30-60 km/h, 10-20 cents/kWh) but on
   Cologne traffic, not their grid.

2. **Grid vs urban**: P4's dense 2 km grid guarantees vehicles stay near each other.
   Cologne's real road network is sparse and irregular.

3. **Allocation rate (95% vs 30%)**: In P4's dense grid, nearly every discharging EV
   finds a charging partner. In Cologne, the `pick_a_donor` feasibility gate
   (`available_energy - demand >= min_energy`) filters out most candidates because
   non-leaders start with limited energy (8-24 kWh range, demand = 10 kWh).

4. **Min SoC at 12.5%**: P4 optimises for selecting CEVs with the lowest SoC (lambda_2
   weight). Our 12.5% = 10 kWh floor / 80 kWh battery, which is the `min_energy`
   safety clamp, not a selection outcome.

---

## P1 — Tang 2023 (Parameter Alignment Only)

Tang 2023 addresses **dynamic path-planning and V2I charging station selection** for
autonomous EVs. It reports travel time, charging time, and cost — not V2V charging
metrics (PDR, allocation rate, payoff, sessions). It is retained in the scenario
matrix purely as a parameter-alignment sanity check.

| Metric | `tang2023_aligned` (ours) |
|---|---|
| Vehicles | 4 |
| Charge sessions | 2.0 +/- 0.0 |
| PDR (unicast) | 94.7% +/- 5.6% |
| Allocation rate | 100.0% +/- 0.0% |
| Jain's fairness | 1.00 +/- 0.00 |
| Avg payoff (cents) | 31.5 +/- 0.03 |
| Min consumer SoC | 22.2% +/- 0.0% |

The low vehicle count (4) reflects the short simulation window (`sumo_begin=25200` to
`sumo_end=26200`, ~17 min) and fixed energy range (18 kWh for all non-leaders). The
100% allocation rate and Jain's FI = 1.0 are trivially achieved with one session per
platoon of uniform demand.

---

## Summary

| Comparison | Comparable? | Key obstacle |
|---|---|---|
| MVCCP vs Abualola 2021 | **Framework-comparable** | Highway topology, PHY layer abstracted, different delay metric |
| MVCCP vs Tang 2024 | **Framework-only** | Confidential dataset, grid vs urban topology |
| MVCCP vs Tang 2023 | **Not comparable** | Different problem domain (V2I path planning, not V2V allocation) |

Metrics are **directionally consistent** (same formulas, same concepts) but
**numerically different** due to highway/dense-grid + 802.11p vs urban Cologne
+ in-memory messaging.

---

## Caveats

Authoritative list: `docs/METRICS.md`. Key points:

1. **PHY layer is not modelled.** P3 uses NS-3 + IEEE 802.11p; we pass messages
   in-memory with range checks only. PDR losses visible in P3/P4 cannot appear in
   our numbers. Our PDR < 100% comes from mobility-driven range violations.
2. **Topology mismatch.** P3: 10 km highway; P4: 2 km grid; us: Cologne urban.
   Allocation-rate deltas are likely topology-driven, not protocol-driven.
3. **P4's dataset is confidential** — exact numeric comparison is not possible.
4. **Quantised delay.** `step_length = 1 s` in `SimConfig` means the
   `avg_rqst_to_packet_gap_s` metric lives on 1-second boundaries.
5. **Jain's FI needs variation to be informative.** Uniform demand + one session
   per platoon -> FI = 1.0 trivially.
6. **Allocation-rate provider pool is a proxy.** MVCCP does not broadcast PA messages
   the way P3 does; we count non-leader vehicles whose init energy passes the
   `pick_a_donor` feasibility gate.

---

## How to reproduce

```bash
# Full paper-aligned sweep
python run_batch.py --only abualola_low_load abualola_high_load tang2024_urban tang2023_aligned

# Single scenario
python run_batch.py --only abualola_low_load

# Resume interrupted run (skip completed seeds)
python run_batch.py --only tang2024_urban --skip-existing
```

Results land in:

- `results/<scenario>/seed_<N>/seed_metrics.csv` — raw per-seed metrics
- `results/<scenario>/aggregate.csv` — mean +/- std per scenario
- `results/summary.csv` — all scenarios in one row
- `results/latest_summary.md` — markdown table
- `results/archive/` — timestamped snapshots
