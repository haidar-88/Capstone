# MVCCP Benchmark Comparison

Comparison of MVCCP simulation results against the two reference papers whose
parameter sets are encoded as scenarios in `run_batch.py`. Our scenarios use
those papers' vehicle counts, DSRC range, demand, and energy distributions —
**but on Cologne urban traffic instead of their highway / grid topologies**.
This is a same-operating-point comparison, not a superiority claim. See
`docs/METRICS.md` for the full methodology and caveat list.

**Latest results**: `results/latest_summary.md` (run `20260420_182428`).
**Reproduce**: `python run_batch.py --only baseline abualola_low_load abualola_high_load tang2024_urban`

---

## Reference papers

| Tag | Paper | Role |
|-----|-------|------|
| **P3** | Abualola 2021, *"V2V Charging Allocation over QoS-OLSR"* | Primary benchmark. Same architecture: QoS-OLSR + MPR, provider/consumer allocation, payoff model. Scenarios: `abualola_low_load`, `abualola_high_load`. |
| **P4** | Tang 2024, *"Discharging Driven Energy Sharing"* | Secondary benchmark. Reports P3 numbers as its "V2V-CA" baseline and introduces `min_consumer_soc` (Table 3). Scenario: `tang2024_urban`. |

`tang2023_aligned` (Tang 2023, *"Dynamic Path-Planning and Charging
Optimization"*) is **not** benchmarked here: it targets V2I infrastructure
routing rather than V2V peer allocation, so its reported numbers are not
comparable. It is retained in the scenario matrix purely as a parameter-
alignment sanity check (`run_batch.py:147-149`, `docs/METRICS.md:179`).

---

## P3 — Abualola 2021

Paper-reported ranges pulled from `docs/METRICS.md:187-193` and §6 of the
paper. Our values from `results/summary.csv`.

| Metric | P3 reported | `abualola_low_load` (ours) | `abualola_high_load` (ours) | Notes |
|---|---|---|---|---|
| Unicast PDR | 90 – 98 % | — † | 100 % | PHY layer abstracted in our stack (no NS-3). Any value < 100 % indicates a bookkeeping bug, not channel loss. See `METRICS.md` §Known Limitations. |
| RQST → packet gap | 20 – 80 ms (DSRC E2E) | — † | 12.0 s | **Different metric**. Ours is sim-time protocol-handshake gap quantised to `step_length = 1 s`. Not a DSRC latency. |
| Allocation rate | Per P3 §6.3 formula | — † | 0.5000 | `#completed_pairs / min(#providers, #consumers_with_demand)`. Same formula, urban topology. |
| Jain's fairness index | 0.78 – 0.92 (SOTA) | — † | 1.0000 | JFI trivially = 1 when each platoon resolves exactly one session with uniform demand. See `METRICS.md` limitations. |
| Avg payoff (¢) | 15 / 8 / 10 cent defaults (eqn 3) | — † | 139.84 | Payoff formula matches P3 eqn 3: `(sell − buy) · energy − time · duration`. |
| Vehicles tracked | 50 – 300 sweep | — † | 45 | `max_vehicles=10` × `num_clusters=30`. |

† `abualola_low_load` was not in the latest run. Re-run with
`python run_batch.py --only abualola_low_load` to populate this column.

### Interpretation

- **PDR at 100 %** is expected and documented in `METRICS.md:210-211`. P3's
  90–98 % figure reflects IEEE 802.11p losses we deliberately don't model.
- **Gap (seconds, not ms)**: P3's ~50 ms is MAC-layer propagation inside
  NS-3. Ours is the simulated delay between a consumer's `CHARGE_RQST` and
  the first `ENERGY_PACKET`, bounded by SUMO's 1-second step. The two
  numbers measure different things — **do not compare magnitudes**.
- **Allocation at 0.5** under the `abualola_high_load` configuration:
  consumers outnumber feasible donors after the `min_energy + demand`
  feasibility gate. P3 does not publish an absolute target — this is a
  directional metric.
- **Jain's FI = 1.0** is expected when each platoon produces one session
  with identical demand. To produce variance (and a more meaningful FI)
  draw `charge_demand_kwh` per consumer from a distribution.

---

## P4 — Tang 2024

Tang 2024 states its simulation dataset is confidential (`METRICS.md:205`),
so only the metric framework is comparable.

| Metric | P4 reported | `tang2024_urban` (ours) | Notes |
|---|---|---|---|
| Min consumer SoC (post-session) | Reported as P4 Table 3 | 0.2190 | `min(final_energy[c]) / battery_capacity` across consumers with completed sessions. |
| Allocation rate (V2V-CA baseline ≈ P3) | Reports P3 as baseline | 0.2500 | One consumer satisfied against 4 candidates. |
| Unicast PDR | P4 echoes P3's 90–98 % | 100 % | Same PHY caveat as P3. |
| Sessions completed | — | 1 | Single transfer triggered under low `energy_range_high = 24 kWh`. |

### Interpretation

- **Min SoC = 0.22** means the consumer ended at 22 % SoC. Below P4's
  target threshold, which suggests `charge_demand_kwh = 10` underfeeds
  consumers who started near `energy_range_low = 8`. Raising demand or
  lowering `min_energy` would lift this number.
- We cannot reproduce P4's exact numeric results (their NS-2 grid dataset
  is confidential); we can only show our values operate in the same
  framework.

---

## Baseline (for context)

The `baseline` scenario is not paper-aligned — it uses the project's
default parameter set — but it anchors the other rows:

| Metric | Value |
|---|---|
| Vehicles | 23 |
| Sessions | 3 |
| Jain's FI | 0.9000 |
| Allocation rate | 0.6000 |
| Unicast PDR | 100 % |
| Avg payoff (¢) | 139.85 |
| Min consumer SoC | 0.2520 |

---

## Caveats

Authoritative list: `docs/METRICS.md:199-218`. Key points:

1. **PHY layer is not modelled.** P3 uses NS-3 + IEEE 802.11p; we pass
   messages in-memory with no channel. PDR losses visible in P3 cannot
   appear in our numbers.
2. **Topology mismatch.** P3 simulates a 10 km, 3-lane highway; we run
   Cologne urban traffic via TAPASCologne. Any allocation-rate delta may
   be topology-driven rather than protocol-driven.
3. **P4's dataset is confidential** — exact numeric comparison is not
   possible, only framework-level.
4. **Quantised delay.** `step_length = 1 s` in `SimConfig` means the
   `avg_rqst_to_packet_gap_s` metric lives on 1-second boundaries.
   Sub-second resolution would need `step_length < 1.0`.
5. **Jain's FI needs variation to be informative.** Uniform demand + one
   session per platoon → FI = 1.0 trivially.
6. **Allocation-rate provider pool is a proxy.** MVCCP does not broadcast
   PA messages the way P3 does; we count non-leader vehicles whose init
   energy passes the `pick_a_donor` feasibility gate.

---

## How to reproduce

```bash
# Full paper-aligned sweep (plus baseline for context)
python run_batch.py --only baseline abualola_low_load abualola_high_load tang2024_urban

# Single scenario
python run_batch.py --only abualola_low_load
```

Results land in:

- `results/summary.csv` — full per-scenario row (all 25 columns).
- `results/latest_summary.md` — markdown-rendered view of the most recent run.
- `results/archive/summary_<timestamp>.csv` + `.md` — snapshots of every
  historical run.
