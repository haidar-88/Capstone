#!/usr/bin/env python3
"""
Batch runner -- execute multiple MVCCP simulation scenarios headless
and produce a comparison table for the professor.

Usage::

    python run_batch.py              # run all scenarios, 20 seeds each
    python run_batch.py --only baseline low_energy   # run specific ones
    python run_batch.py --seeds 5    # override number of seeds
"""

import argparse
import csv
import math
import os
import shutil
import statistics
import sys
from datetime import datetime

import traci

from simulation.sim_config import SimConfig
from simulation.traci_runner import main as run_sim


# Columns rendered in the console table and in results/latest_summary.md.
# Shared source of truth so the two views cannot drift.
DISPLAY_COLS = [
    ("scenario_name",             "Scenario",           18),
    ("num_vehicles",              "Vehicles",            9),
    ("arrival_rate",              "Arrival %",          10),
    ("avg_rqst_to_packet_gap_s",  "Gap(s)",             10),
    ("jains_fairness",            "Jain's FI",          10),
    ("num_charge_sessions",       "Sessions",            9),
    ("pdr_unicast_avg",           "PDR (uni)",          10),
    ("allocation_rate",           "Alloc %",            10),
    ("avg_payoff_cents",          "Payoff(¢)",          10),
    ("min_consumer_soc",          "Min SoC",            10),
]

RESULTS_DIR = "results"
ARCHIVE_DIR = os.path.join(RESULTS_DIR, "archive")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")
LATEST_MD = os.path.join(RESULTS_DIR, "latest_summary.md")
DEFAULT_SEEDS = 20

# Numeric metrics aggregated with mean ± std
_NUMERIC_METRICS = [
    "arrival_rate",
    "avg_rqst_to_packet_gap_s",
    "jains_fairness",
    "num_charge_sessions",
    "pdr_unicast_avg",
    "allocation_rate",
    "avg_payoff_cents",
    "min_consumer_soc",
]


def _cleanup_traci():
    """Force-remove any stale 'default' connection left by a failed scenario."""
    try:
        traci.close()
    except Exception:
        pass
    # If traci.close() bombed mid-way the 'default' entry lingers in the
    # internal registry, which makes traci.start() raise
    # "Connection 'default' is already active" on the next scenario.
    # Touches a private attribute -- if a future traci release renames
    # it, surface the breakage loudly instead of silently losing
    # scenarios.
    try:
        import traci.main as _tm
        _tm._connections.pop("default", None)
    except AttributeError:
        print(
            "WARNING: traci.main._connections not found -- "
            "cleanup path outdated for this traci version.  "
            "Subsequent scenarios may fail with 'Connection already active'."
        )
    except Exception:
        pass


# ── Experiment matrix ────────────────────────────────────────────────

SCENARIOS = [
    {
        "scenario_name": "baseline",
        # all defaults
    },
    {
        "scenario_name": "low_energy",
        "energy_range_low": 10.0,
        "energy_range_high": 25.0,
        "leader_min_energy_kwh": 30.0,
        # Small transfers only — a provider at SoC=25 kWh can donate 5 kWh and
        # still sit above min_energy=10 kWh.
        "max_charge_demand_kwh": 5.0,
    },
    {
        "scenario_name": "high_energy",
        "energy_range_low": 40.0,
        "energy_range_high": 70.0,
        "leader_min_energy_kwh": 60.0,
    },
    {
        "scenario_name": "large_demand",
        "max_charge_demand_kwh": 40.0,
    },
    {
        "scenario_name": "small_demand",
        "max_charge_demand_kwh": 10.0,
    },
    {
        "scenario_name": "dense_clusters",
        "max_vehicles": 10,
        "num_clusters": 5,
    },
    {
        "scenario_name": "sparse_clusters",
        "max_vehicles": 4,
        "num_clusters": 15,
    },
    {
        "scenario_name": "short_range",
        "dsrc_range_m": 50.0,
    },
    {
        "scenario_name": "long_range",
        "dsrc_range_m": 200.0,
    },

    # ── External benchmark scenarios ─────────────────────────────────

    # P3 (Abualola 2021) — primary benchmark, low load.
    # Demand lowered from 55→20 kWh: Abualola uses 10–50 kWh transfers; 55 kWh
    # exceeds energy_range_high=35, which makes every candidate fail the
    # feasibility gate (available_energy − demand ≥ min_energy).
    {
        "scenario_name": "abualola_low_load",
        "num_clusters": 15,
        "max_vehicles": 5,
        "dsrc_range_m": 250.0,
        "max_charge_demand_kwh": 20.0,
        "max_transfer_rate_in": 40.0,
        "max_transfer_rate_out": 40.0,
        "energy_range_low": 8.0,
        "energy_range_high": 35.0,
        "leader_min_energy_kwh": 56.0,
        "min_vehicles_for_cluster": 75,
    },

    # P3 (Abualola 2021) — primary benchmark, high load. Same demand adjustment
    # as abualola_low_load for the same feasibility reason.
    {
        "scenario_name": "abualola_high_load",
        "num_clusters": 30,
        "max_vehicles": 10,
        "dsrc_range_m": 250.0,
        "max_charge_demand_kwh": 20.0,
        "max_transfer_rate_in": 40.0,
        "max_transfer_rate_out": 40.0,
        "energy_range_low": 8.0,
        "energy_range_high": 35.0,
        "leader_min_energy_kwh": 56.0,
        "min_vehicles_for_cluster": 150,
    },

    # P4 (Tang 2024) — secondary benchmark.
    # Demand lowered from 35→10 kWh: Tang 2024 models small urban top-ups;
    # 35 kWh against energy_range_high=24 left no viable donor.
    {
        "scenario_name": "tang2024_urban",
        "num_clusters": 20,
        "max_vehicles": 5,
        "dsrc_range_m": 250.0,
        "max_charge_demand_kwh": 10.0,
        "energy_range_low": 8.0,
        "energy_range_high": 24.0,
        "leader_min_energy_kwh": 56.0,
    },

    # P1 (Tang 2023) — parameter alignment only, different problem domain.
    # Demand lowered from 22.5→5 kWh: with all non-leaders pinned at 18 kWh
    # (fixed range), a 22.5 kWh demand leaves every candidate at −4.5 kWh,
    # well below min_energy=10. 5 kWh keeps residual SoC at 13 kWh ≥ min.
    {
        "scenario_name": "tang2023_aligned",
        "battery_capacity_kwh": 45.0,
        "energy_range_low": 18.0,
        "energy_range_high": 18.0,
        "leader_min_energy_kwh": 40.5,
        "max_charge_demand_kwh": 5.0,
        "dsrc_range_m": 25.0,
        "max_transfer_rate_in": 70.0,
        "max_transfer_rate_out": 70.0,
        "max_vehicles": 5,
        "num_clusters": 10,
        "sumo_begin": 25200,
        "sumo_end": 26200,
        "min_vehicles_for_cluster": 50,
    },
]


# ── Runner ───────────────────────────────────────────────────────────

def _archive_previous_summary():
    """Copy any existing summary.csv into results/archive/ before overwriting."""
    if not os.path.isfile(SUMMARY_CSV):
        return
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        prev_ts = datetime.fromtimestamp(
            os.path.getmtime(SUMMARY_CSV)
        ).strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(ARCHIVE_DIR, f"summary_{prev_ts}.csv")
        shutil.copy2(SUMMARY_CSV, dest)
    except OSError as e:
        print(f"  [WARN] Could not archive previous summary.csv: {e}")


def _collect_seed_rows(scenario_name, seeds):
    """Read seed_metrics.csv for each completed seed and return list of row dicts."""
    rows = []
    for seed in seeds:
        path = os.path.join(RESULTS_DIR, scenario_name, f"seed_{seed}", "seed_metrics.csv")
        if not os.path.isfile(path):
            continue
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    return rows


def _write_aggregate(scenario_name, seed_rows, summary_path):
    """Compute mean ± std from seed_rows and append one row to summary_path."""
    if not seed_rows:
        return

    first = seed_rows[0]
    write_header = not os.path.isfile(summary_path)

    agg_header = ["scenario_name", "num_seeds", "num_vehicles", "num_clusters",
                  "energy_range_low", "energy_range_high", "max_charge_demand_kwh"]
    for m in _NUMERIC_METRICS:
        agg_header.append(m)
        agg_header.append(f"{m}_std")

    agg_row = {
        "scenario_name": scenario_name,
        "num_seeds": len(seed_rows),
        "num_vehicles": first.get("num_vehicles", ""),
        "num_clusters": first.get("num_clusters", ""),
        "energy_range_low": first.get("energy_range_low", ""),
        "energy_range_high": first.get("energy_range_high", ""),
        "max_charge_demand_kwh": first.get("max_charge_demand_kwh", ""),
    }
    for m in _NUMERIC_METRICS:
        vals = []
        for row in seed_rows:
            v = row.get(m, "")
            if v not in ("N/A", "", "nan"):
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
        if vals:
            mean = statistics.mean(vals)
            std = statistics.stdev(vals) if len(vals) > 1 else 0.0
            agg_row[m] = f"{mean:.4f}"
            agg_row[f"{m}_std"] = f"{std:.4f}"
        else:
            agg_row[m] = "N/A"
            agg_row[f"{m}_std"] = "N/A"

    # Also write per-scenario aggregate CSV
    agg_path = os.path.join(RESULTS_DIR, scenario_name, "aggregate.csv")
    with open(agg_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=agg_header)
        writer.writeheader()
        writer.writerow(agg_row)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(summary_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=agg_header)
        if write_header:
            writer.writeheader()
        writer.writerow(agg_row)


def run_all(selected_names=None, num_seeds=DEFAULT_SEEDS):
    """Run each scenario over multiple seeds in headless mode."""
    scenarios = SCENARIOS
    if selected_names:
        scenarios = [s for s in SCENARIOS
                     if s["scenario_name"] in selected_names]
        if not scenarios:
            print(f"No matching scenarios for: {selected_names}")
            print(f"Available: {[s['scenario_name'] for s in SCENARIOS]}")
            return

    seeds = list(range(num_seeds))
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    _archive_previous_summary()
    if os.path.isfile(SUMMARY_CSV):
        os.remove(SUMMARY_CSV)

    total = len(scenarios)
    for i, scenario_dict in enumerate(scenarios):
        name = scenario_dict.get("scenario_name", f"scenario_{i}")
        print(f"\n{'=' * 60}")
        print(f"  [{i + 1}/{total}]  Scenario: {name}  ({num_seeds} seeds)")
        print(f"{'=' * 60}\n")

        for seed in seeds:
            print(f"  -- seed {seed} --")
            _cleanup_traci()
            config = SimConfig.from_dict({**scenario_dict, "seed": seed, "headless": True})
            try:
                run_sim(config)
            except Exception as e:
                print(f"  [ERROR] Scenario '{name}' seed {seed} failed: {e}")
                _cleanup_traci()
                continue

        seed_rows = _collect_seed_rows(name, seeds)
        _write_aggregate(name, seed_rows, SUMMARY_CSV)
        print(f"  Aggregated {len(seed_rows)} seeds for '{name}'.")

    print_summary_table(run_ts)


def _write_markdown_summary(rows, run_ts):
    """Render `rows` as a markdown table and save to latest_summary.md + archive."""
    if not rows:
        return

    headers = [label for _, label, _ in DISPLAY_COLS]
    lines = [
        f"# MVCCP Batch Results — {run_ts}",
        "",
        f"Run timestamp: `{run_ts}`",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        cells = [str(row.get(key, "N/A")) for key, _, _ in DISPLAY_COLS]
        lines.append("| " + " | ".join(cells) + " |")

    lines += [
        "",
        "Per-type PDR and configuration columns (energy ranges, seed, per-message PDRs) "
        "are in the full CSV at `results/summary.csv`. Timestamped CSV snapshots of every "
        "run live in `results/archive/`.",
        "",
    ]
    content = "\n".join(lines)

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(LATEST_MD, "w") as f:
        f.write(content)
    with open(os.path.join(ARCHIVE_DIR, f"summary_{run_ts}.md"), "w") as f:
        f.write(content)


def _fmt_cell(row, key, width):
    """Format a cell as 'val ± std' if a corresponding _std column exists."""
    val = row.get(key, "N/A")
    std = row.get(f"{key}_std")
    if std and std != "N/A" and val != "N/A":
        text = f"{val} ±{std}"
    else:
        text = str(val)
    return text.center(width)


def print_summary_table(run_ts=None):
    """Read results/summary.csv, print a formatted console table, and save a markdown copy."""
    if not os.path.isfile(SUMMARY_CSV):
        print("\nNo results/summary.csv found -- nothing to display.")
        return

    with open(SUMMARY_CSV, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("\nsummary.csv is empty.")
        return

    header_line = " | ".join(
        label.center(width) for _, label, width in DISPLAY_COLS
    )
    sep = "-+-".join("-" * width for _, _, width in DISPLAY_COLS)

    print(f"\n{'=' * len(header_line)}")
    print("  MVCCP Simulation Results  (mean ± std)")
    print(f"{'=' * len(header_line)}")
    print(header_line)
    print(sep)

    for row in rows:
        cells = [_fmt_cell(row, key, width) for key, _, width in DISPLAY_COLS]
        print(" | ".join(cells))

    print(f"{'=' * len(header_line)}\n")

    if run_ts is None:
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_markdown_summary(rows, run_ts)
    print(f"  Markdown summary: {LATEST_MD}")
    print(f"  Archived copy   : {os.path.join(ARCHIVE_DIR, f'summary_{run_ts}.md')}\n")


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run MVCCP simulation scenarios in batch (headless).",
    )
    parser.add_argument(
        "--only", nargs="*", default=None,
        help="Run only the named scenarios (e.g. --only baseline low_energy)",
    )
    parser.add_argument(
        "--seeds", type=int, default=DEFAULT_SEEDS,
        help=f"Number of random seeds per scenario (default: {DEFAULT_SEEDS})",
    )
    args = parser.parse_args()
    run_all(args.only, num_seeds=args.seeds)


if __name__ == "__main__":
    main()
