"""
MetricsCollector -- thread-safe event recorder and KPI calculator.

Attached to each vehicle as ``vehicle.metrics`` so that protocol handlers
can call recording methods without importing this module directly.

After a simulation run, call ``export()`` to write CSV files.
"""

import csv
import math
import os
import threading
import time
from collections import defaultdict


# Message types that are fan-out broadcasts in this implementation.
# Their PDR is not meaningful on its own because one send yields N
# deliveries; see METRICS.md "Known limitations".
_BROADCAST_TYPES = frozenset({"CHARGE_RQST", "CHARGE_RSP", "STATUS"})

# Message types whose PDR is reported individually in the summary CSV.
# These are all unicast in MVCCP.
_TRACKED_UNICAST_TYPES = (
    "HELLO",
    "JOIN_OFFER",
    "JOIN_ACCEPT",
    "ACK",
    "CHARGE_SYN",
    "CHARGE_ACK",
    "ENERGY_PACKET",
    "CHARGE_FIN",
)


class MetricsCollector:
    """Collect per-vehicle / per-platoon events and compute aggregate KPIs."""

    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()

        # Vehicle snapshots
        self._vehicle_init: dict[str, dict] = {}       # vid -> {energy, is_leader}
        self._vehicle_final: dict[str, float] = {}      # vid -> final energy
        self._vehicle_platoon: dict[str, str] = {}       # vid -> platoon_id

        # Message log
        self._messages: list[dict] = []

        # Energy accounting
        self._energy_sent: dict[str, float] = defaultdict(float)      # provider -> kWh
        self._energy_received: dict[str, float] = defaultdict(float)  # consumer -> kWh

        # Session tracking
        self._charge_sessions: list[dict] = []

        # Send/delivery tracking for PDR
        self._send_counts: dict[str, int] = defaultdict(int)
        self._delivery_counts: dict[str, int] = defaultdict(int)

        # Allocation tracking
        self._charge_assignments: set[tuple[str, str]] = set()

        # Per-session energy for payoff
        self._session_energy: dict[tuple[str, str], float] = defaultdict(float)

        # Timing
        self._sim_start = time.monotonic()
        self._sim_time: float = 0.0

    def set_sim_time(self, t: float):
        """Update the current simulation time (called from main loop)."""
        with self._lock:
            self._sim_time = t

    def sim_time(self) -> float:
        """Return the most recently recorded simulation time (seconds).

        Protocol hooks should use this rather than ``time.monotonic()``
        so that all stored timestamps live in the same SUMO time base.
        """
        with self._lock:
            return self._sim_time

    # ------------------------------------------------------------------
    # Recording methods (called from hooks)
    # ------------------------------------------------------------------

    def record_vehicle_init(self, vid: str, energy_kwh: float, is_leader: bool):
        with self._lock:
            self._vehicle_init[vid] = {
                "energy": energy_kwh,
                "is_leader": is_leader,
            }

    def record_vehicle_final(self, vid: str, energy_kwh: float):
        with self._lock:
            self._vehicle_final[vid] = energy_kwh

    def record_vehicle_platoon(self, vid: str, platoon_id: str):
        with self._lock:
            self._vehicle_platoon[vid] = platoon_id

    def record_message(self, msg_type: str, sender_id: str,
                       receiver_id: str):
        with self._lock:
            self._messages.append({
                "type": msg_type,
                "sender": sender_id,
                "receiver": receiver_id,
                "timestamp": self._sim_time,
            })

    def record_energy_sent(self, provider_id: str, kwh: float):
        with self._lock:
            self._energy_sent[provider_id] += kwh

    def record_energy_received(self, consumer_id: str, kwh: float):
        with self._lock:
            self._energy_received[consumer_id] += kwh

    def record_charge_session_end(self, provider_id: str,
                                  consumer_id: str, timestamp: float):
        with self._lock:
            self._charge_sessions.append({
                "provider": provider_id,
                "consumer": consumer_id,
                "end_time": timestamp,
            })

    def record_platoon_join(self, vid: str, platoon_id: str,
                            timestamp: float):
        with self._lock:
            self._vehicle_platoon[vid] = platoon_id

    def record_send_attempt(self, msg_type: str):
        with self._lock:
            self._send_counts[msg_type] += 1

    def record_delivery(self, msg_type: str):
        with self._lock:
            self._delivery_counts[msg_type] += 1

    def record_charge_assignment(self, provider_id: str,
                                 consumer_id: str):
        with self._lock:
            self._charge_assignments.add((provider_id, consumer_id))

    def record_session_energy(self, provider_id: str, consumer_id: str,
                              kwh: float):
        with self._lock:
            self._session_energy[(provider_id, consumer_id)] += kwh

    # ------------------------------------------------------------------
    # Metric computations
    # ------------------------------------------------------------------

    def arrival_rate(self) -> float:
        """Fraction of vehicles whose final energy > min_energy_kwh."""
        if not self._vehicle_final:
            return 0.0
        threshold = self.config.min_energy_kwh
        above = sum(1 for e in self._vehicle_final.values() if e > threshold)
        return above / len(self._vehicle_final)

    def transfer_efficiency(self) -> float:
        """Total energy received / total energy sent.

        Retained for future use, but **not exported** to the summary
        CSV: without any layer-3 transport modelling the ratio is 1.0
        by construction (``handle_energy_packet`` records the same
        ``actual_received`` on both sides). Re-add to the summary once
        a packet-loss / efficiency model exists.
        """
        total_sent = sum(self._energy_sent.values())
        total_recv = sum(self._energy_received.values())
        return total_recv / total_sent if total_sent > 0 else 0.0

    def avg_rqst_to_packet_gap_s(self) -> float:
        """Average sim-time elapsed between a consumer's CHARGE_RQST and
        the first ENERGY_PACKET it receives.

        This measures protocol handshake latency in simulation time
        only — no layer-3 transport is simulated, so this value is
        **not** comparable to the wireless-layer latencies reported in
        the DSRC literature. Timestamps come from ``record_message``,
        which stamps each event with ``self._sim_time`` (SUMO seconds);
        with ``step_length=1.0`` the resolution floor is 1 second.
        """
        rqst_times: dict[str, float] = {}
        packet_times: dict[str, float] = {}

        for m in self._messages:
            if m["type"] == "CHARGE_RQST":
                sid = m["sender"]
                if sid not in rqst_times or m["timestamp"] < rqst_times[sid]:
                    rqst_times[sid] = m["timestamp"]
            elif m["type"] == "ENERGY_PACKET":
                rid = m["receiver"]
                if rid not in packet_times or m["timestamp"] < packet_times[rid]:
                    packet_times[rid] = m["timestamp"]

        gaps = []
        for vid, t_rqst in rqst_times.items():
            t_pkt = packet_times.get(vid)
            if t_pkt is not None and t_pkt >= t_rqst:
                gaps.append(t_pkt - t_rqst)

        return sum(gaps) / len(gaps) if gaps else 0.0

    def jains_fairness(self) -> float:
        """Jain's Fairness Index over energy contributed by each provider."""
        vals = list(self._energy_sent.values())
        n = len(vals)
        if n == 0:
            return 0.0
        if n == 1:
            return 1.0
        sum_x = sum(vals)
        sum_x2 = sum(x * x for x in vals)
        if sum_x2 == 0:
            return 1.0
        return (sum_x ** 2) / (n * sum_x2)

    def pdr_by_type(self) -> dict[str, float]:
        """Per-message-type application-layer PDR.

        Broadcast message types (``_BROADCAST_TYPES``) are excluded: one
        send yields N deliveries, so the ratio is not comparable to the
        literature definition.  For unicast types the ratio is
        ``deliveries / sends``; values outside ``[0, 1]`` indicate a
        bookkeeping bug (usually a missing ``record_send_attempt`` hook).
        """
        with self._lock:
            sends = dict(self._send_counts)
            deliveries = dict(self._delivery_counts)
        out = {}
        for msg_type in _TRACKED_UNICAST_TYPES:
            sent = sends.get(msg_type, 0)
            delivered = deliveries.get(msg_type, 0)
            out[msg_type] = delivered / sent if sent > 0 else float("nan")
        return out

    def pdr_unicast_avg(self) -> float:
        """Arithmetic mean of per-type PDRs over tracked unicast messages.

        Types with zero sends are ignored.  Returns NaN if no unicast
        message has a valid ratio.
        """
        per_type = self.pdr_by_type()
        valid = [v for v in per_type.values() if not math.isnan(v)]
        return sum(valid) / len(valid) if valid else float("nan")

    def allocation_rate(self) -> float:
        """Fraction of demand satisfied (P3 Abualola 2021 §6.3).

        ``AR = #completed_pairs / min(#providers_in_network, #consumers_with_demand)``.

        - **consumers**: distinct senders of ``CHARGE_RQST``.
        - **providers**: distinct non-leader vehicles whose initial
          energy would pass the ``pick_a_donor`` feasibility gate, i.e.
          ``energy >= min_energy_kwh + charge_demand_kwh``.  We do not
          have PA broadcasts in this protocol, so we proxy the provider
          pool from ``_vehicle_init``; this is documented in METRICS.md.
        """
        threshold = self.config.min_energy_kwh + self.config.max_charge_demand_kwh
        with self._lock:
            consumers = {
                m["sender"] for m in self._messages
                if m["type"] == "CHARGE_RQST" and m["sender"]
            }
            providers = {
                vid for vid, init in self._vehicle_init.items()
                if not init["is_leader"]
                and init["energy"] >= threshold
            }
            completed = {
                (s["provider"], s["consumer"]) for s in self._charge_sessions
            }
        denom = min(len(providers), len(consumers))
        if denom == 0:
            return float("nan")
        return len(completed) / denom

    def avg_payoff_cents(self) -> float:
        """Average provider payoff using P3 (Abualola 2021) eqn 3."""
        cfg = self.config
        with self._lock:
            sessions = list(self._charge_sessions)
            session_energy = dict(self._session_energy)
        if not sessions:
            return float("nan")
        payoffs = []
        for s in sessions:
            pair = (s["provider"], s["consumer"])
            energy = session_energy.get(pair, 0.0)
            duration_h = self._session_duration_hours(pair)
            payoff = (
                (cfg.selling_price_cents_per_kwh
                 - cfg.original_price_cents_per_kwh) * energy
                - cfg.time_value_cents_per_hour * duration_h
            )
            payoffs.append(payoff)
        return sum(payoffs) / len(payoffs) if payoffs else float("nan")

    def _session_duration_hours(self, pair: tuple[str, str]) -> float:
        """CHARGE_SYN → CHARGE_FIN elapsed time in _messages.

        Consumer sends CHARGE_SYN (handle_charge_rsp), Provider sends
        CHARGE_FIN (vehicle.start_charging).  Both recorded via _record()
        so sender field is the originator.
        """
        provider, consumer = pair
        with self._lock:
            messages = list(self._messages)
        syn_time = None
        fin_time = None
        for m in messages:
            if m["type"] == "CHARGE_SYN" and m["sender"] == consumer:
                if syn_time is None or m["timestamp"] < syn_time:
                    syn_time = m["timestamp"]
            elif m["type"] == "CHARGE_FIN" and m["sender"] == provider:
                if fin_time is None or m["timestamp"] > fin_time:
                    fin_time = m["timestamp"]
        if syn_time is not None and fin_time is not None and fin_time >= syn_time:
            return (fin_time - syn_time) / 3600.0
        return 0.0

    def min_consumer_soc(self) -> float:
        """Min final SoC across all consumers (P4 Tang 2024 metric).

        Returns ``NaN`` when no charge session has completed; that is
        distinct from a real 0 % SoC reading.
        """
        with self._lock:
            consumers = {s["consumer"] for s in self._charge_sessions}
            if not consumers:
                return float("nan")
            finals = {c: self._vehicle_final.get(c, 0.0) for c in consumers}
        capacity = self.config.battery_capacity_kwh
        if capacity <= 0:
            return float("nan")
        return min(finals.values()) / capacity

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export(self):
        """Write per_vehicle.csv and seed_metrics.csv under results/<scenario>/seed_<N>/."""
        base = os.path.join(
            self.config.output_dir,
            self.config.scenario_name,
            f"seed_{self.config.seed}",
        )
        os.makedirs(base, exist_ok=True)

        self._write_per_vehicle(base)
        self._write_seed_metrics(base)

    def _write_per_vehicle(self, base_dir: str):
        path = os.path.join(base_dir, "per_vehicle.csv")
        header = [
            "vehicle_id", "platoon_id", "is_leader",
            "initial_energy_kwh", "final_energy_kwh",
            "energy_sent_kwh", "energy_received_kwh",
            "above_threshold",
        ]
        rows = []
        for vid, init in self._vehicle_init.items():
            final_e = self._vehicle_final.get(vid, init["energy"])
            rows.append({
                "vehicle_id": vid,
                "platoon_id": self._vehicle_platoon.get(vid, ""),
                "is_leader": init["is_leader"],
                "initial_energy_kwh": f"{init['energy']:.2f}",
                "final_energy_kwh": f"{final_e:.2f}",
                "energy_sent_kwh": f"{self._energy_sent.get(vid, 0.0):.2f}",
                "energy_received_kwh": f"{self._energy_received.get(vid, 0.0):.2f}",
                "above_threshold": final_e > self.config.min_energy_kwh,
            })

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

    def _write_seed_metrics(self, base_dir: str):
        """Write one-row CSV with all KPIs for this seed to base_dir/seed_metrics.csv."""
        seed_path = os.path.join(base_dir, "seed_metrics.csv")
        pdr_cols = [f"pdr_{t.lower()}" for t in _TRACKED_UNICAST_TYPES]
        header = [
            "scenario_name", "seed", "num_vehicles", "num_clusters",
            "energy_range_low", "energy_range_high", "max_charge_demand_kwh",
            "arrival_rate",
            "avg_rqst_to_packet_gap_s", "jains_fairness",
            "total_energy_sent_kwh", "total_energy_received_kwh",
            "num_charge_sessions",
            *pdr_cols, "pdr_unicast_avg",
            "allocation_rate", "avg_payoff_cents",
            "min_consumer_soc",
        ]

        pdr_per_type = self.pdr_by_type()

        row = {
            "scenario_name": self.config.scenario_name,
            "seed": self.config.seed,
            "num_vehicles": len(self._vehicle_init),
            "num_clusters": self.config.num_clusters,
            "energy_range_low": self.config.energy_range_low,
            "energy_range_high": self.config.energy_range_high,
            "max_charge_demand_kwh": self.config.max_charge_demand_kwh,
            "arrival_rate": f"{self.arrival_rate():.4f}",
            "avg_rqst_to_packet_gap_s": f"{self.avg_rqst_to_packet_gap_s():.2f}",
            "jains_fairness": f"{self.jains_fairness():.4f}",
            "total_energy_sent_kwh": f"{sum(self._energy_sent.values()):.2f}",
            "total_energy_received_kwh": f"{sum(self._energy_received.values()):.2f}",
            "num_charge_sessions": len(self._charge_sessions),
            "pdr_unicast_avg": _fmt(self.pdr_unicast_avg(), "{:.4f}"),
            "allocation_rate": _fmt(self.allocation_rate(), "{:.4f}"),
            "avg_payoff_cents": _fmt(self.avg_payoff_cents(), "{:.2f}"),
            "min_consumer_soc": _fmt(self.min_consumer_soc(), "{:.4f}"),
        }
        for msg_type in _TRACKED_UNICAST_TYPES:
            row[f"pdr_{msg_type.lower()}"] = _fmt(
                pdr_per_type.get(msg_type, float("nan")), "{:.4f}"
            )

        with open(seed_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerow(row)

    def print_summary(self):
        """Print a human-readable summary to stdout."""
        print("\n" + "=" * 60)
        print(f"  Scenario: {self.config.scenario_name}")
        print("=" * 60)
        print(f"  Vehicles tracked    : {len(self._vehicle_init)}")
        print(f"  Charge sessions     : {len(self._charge_sessions)}")
        print(f"  Total messages      : {len(self._messages)}")
        print(f"  ---")
        print(f"  Arrival Rate        : {self.arrival_rate():.2%}")
        print(f"  RQST→Packet Gap     : {self.avg_rqst_to_packet_gap_s():.2f} s")
        print(f"  Jain's Fairness     : {self.jains_fairness():.4f}")
        print("=" * 60 + "\n")


def _fmt(value: float, spec: str) -> str:
    """Format a float, writing 'N/A' for NaN so CSVs stay unambiguous."""
    if isinstance(value, float) and math.isnan(value):
        return "N/A"
    return spec.format(value)
