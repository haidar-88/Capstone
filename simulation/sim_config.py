"""
SimConfig -- dataclass holding all tuneable simulation parameters.

Used by traci_runner.main() and run_batch.py to parameterise scenarios
without editing source code.
"""

import argparse
import dataclasses


@dataclasses.dataclass
class SimConfig:
    """All tuneable simulation parameters with sensible defaults."""

    # Protocol / battery
    dsrc_range_m: float = 100.0
    max_vehicles: int = 6
    num_clusters: int = 10
    battery_capacity_kwh: float = 80.0
    min_energy_kwh: float = 10.0
    energy_range_low: float = 15.0
    energy_range_high: float = 45.0
    leader_min_energy_kwh: float = 50.0
    time_scale: float = 60.0
    max_transfer_rate_in: float = 50.0
    max_transfer_rate_out: float = 50.0
    max_charge_demand_kwh: float = 20.0
    charge_soc_target: float = 0.5
    charge_cooldown_s: float = 300.0

    # Pricing model (P3 Abualola 2021 eqn 3)
    selling_price_cents_per_kwh: float = 15.0
    original_price_cents_per_kwh: float = 8.0
    time_value_cents_per_hour: float = 10.0

    # Simulation window
    sumo_begin: int = 21600      # 06:00
    sumo_end: int = 25200        # 07:00
    step_length: float = 1.0    # seconds per SUMO step (raise to 2-5 for faster runs)
    warmup_steps: int = 500
    min_vehicles_for_cluster: int = 150

    # Runtime
    headless: bool = False       # True = "sumo" (no GUI)
    seed: int = 42
    scenario_name: str = "default"
    output_dir: str = "results"

    @classmethod
    def from_dict(cls, d: dict) -> "SimConfig":
        """Build a SimConfig from a dict, ignoring unknown keys."""
        valid_keys = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


def build_config_from_args(argv=None) -> SimConfig:
    """Parse CLI flags into a SimConfig.  Every field becomes a flag."""
    parser = argparse.ArgumentParser(description="MVCCP simulation runner")

    for field in dataclasses.fields(SimConfig):
        flag = f"--{field.name.replace('_', '-')}"
        if field.type is bool:
            parser.add_argument(flag, action="store_true", default=field.default)
        else:
            parser.add_argument(flag, type=field.type, default=field.default)

    args = parser.parse_args(argv)
    return SimConfig(**vars(args))
