"""
TraCI live runner -- MVCCP over TAPASCologne.

Usage::

    python -m simulation.traci_runner                 # GUI mode (defaults)
    python -m simulation.traci_runner --headless      # headless mode
    python -m simulation.traci_runner --headless --energy-range-low 10

When imported, call ``main(config)`` with a SimConfig instance.
"""

import logging
import os
import random
import time

import traci
import traci.constants as tc

from simulation.traci_vehicle import TraciVehicle
from simulation.sim_network import SimNetwork
from simulation.sim_config import SimConfig, build_config_from_args
from simulation.metrics import MetricsCollector
from network.platoon import Platoon

logger = logging.getLogger(__name__)

# --- Paths ---------------------------------------------------------------
_SUMO_CFG = os.path.join("TAPASCologne-0.32.0", "cologne6to8.sumocfg")

# --- GUI appearance -------------------------------------------------------
_COLOR_DEFAULT = (255, 0, 0, 255)   # red (unassigned vehicles)


def _cluster_colors(n):
    """Generate *n* visually distinct RGBA colors using HSV spacing."""
    if n == 0:
        return []
    colors = []
    for i in range(n):
        hue = i / n
        # Convert HSV (hue, 0.9, 0.9) to RGB
        r, g, b = _hsv_to_rgb(hue, 0.9, 0.9)
        colors.append((int(r * 255), int(g * 255), int(b * 255), 255))
    return colors


def _hsv_to_rgb(h, s, v):
    """Pure-Python HSV→RGB (avoids importing colorsys)."""
    if s == 0.0:
        return (v, v, v)
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    if i == 0:
        return (v, t, p)
    if i == 1:
        return (q, v, p)
    if i == 2:
        return (p, v, t)
    if i == 3:
        return (p, q, v)
    if i == 4:
        return (t, p, v)
    return (v, p, q)

def _find_clusters(radius_m, max_per_cluster, num_clusters):
    """Scan live SUMO vehicles and return multiple clusters of nearby IDs.

    Uses pairwise Euclidean distance on TraCI positions.  Greedily picks
    the hub with the most neighbors, extracts up to *max_per_cluster*
    vehicles, removes them from the pool, and repeats up to *num_clusters*
    times.

    Returns a list of clusters (each a list of SUMO IDs).
    """
    all_ids = traci.vehicle.getIDList()
    if len(all_ids) < 2:
        return []

    positions = {}
    for vid in all_ids:
        positions[vid] = traci.vehicle.getPosition(vid)

    # Build neighbor sets (O(n^2) pairwise scan, squared distances)
    neighbor_sets = {}
    id_list = list(positions.keys())
    radius_sq = radius_m * radius_m
    for i in range(len(id_list)):
        for j in range(i + 1, len(id_list)):
            v1, v2 = id_list[i], id_list[j]
            x1, y1 = positions[v1]
            x2, y2 = positions[v2]
            dx, dy = x1 - x2, y1 - y2
            if dx * dx + dy * dy <= radius_sq:
                neighbor_sets.setdefault(v1, set()).add(v2)
                neighbor_sets.setdefault(v2, set()).add(v1)

    if not neighbor_sets:
        logger.warning("No vehicles within %.0f m -- falling back to sequential groups.", radius_m)
        flat = list(all_ids)
        clusters = []
        for start in range(0, len(flat), max_per_cluster):
            chunk = flat[start:start + max_per_cluster]
            if len(chunk) >= 2:
                clusters.append(chunk)
            if len(clusters) >= num_clusters:
                break
        return clusters

    # Greedy extraction: pick densest hub, extract cluster, repeat
    remaining = set(positions.keys())
    clusters = []

    while len(clusters) < num_clusters and remaining:
        # Rebuild candidate neighbor counts within remaining vehicles
        best_hub = None
        best_count = 0
        for vid in remaining:
            neighbors_in_pool = neighbor_sets.get(vid, set()) & remaining
            if len(neighbors_in_pool) > best_count:
                best_count = len(neighbors_in_pool)
                best_hub = vid

        if best_hub is None or best_count == 0:
            break

        neighbors_in_pool = neighbor_sets[best_hub] & remaining
        cluster = [best_hub] + list(neighbors_in_pool)
        cluster = cluster[:max_per_cluster]

        clusters.append(cluster)
        remaining -= set(cluster)

    return clusters


def main(config: SimConfig | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[traci] %(levelname)s %(message)s",
    )

    if config is None:
        config = build_config_from_args()

    random.seed(config.seed)

    if not os.path.isfile(_SUMO_CFG):
        logger.error("SUMO config not found: %s", _SUMO_CFG)
        raise SystemExit(1)

    # 1. Start SUMO (headless or GUI)
    sumo_cmd = "sumo" if config.headless else "sumo-gui"
    logger.info("Starting %s ...", sumo_cmd)
    traci.start([
        sumo_cmd, "-c", _SUMO_CFG,
        "--begin", str(config.sumo_begin),
        "--end", str(config.sumo_end),
        "--step-length", str(config.step_length),
        "--start",
        "--quit-on-end",
        "--no-warnings",
    ], numRetries=120)

    if not config.headless:
        logger.info("Waiting for GUI to render the network ...")
        for _ in range(100):
            traci.simulationStep()
            time.sleep(0.1)

    metrics = MetricsCollector(config)

    try:
        # 2. Warmup -- step until enough vehicles exist
        logger.info("Warming up (%d steps) ...", config.warmup_steps)
        for _ in range(config.warmup_steps):
            traci.simulationStep()
            if len(traci.vehicle.getIDList()) >= config.min_vehicles_for_cluster:
                break
            if not config.headless:
                time.sleep(0.01)

        # 3. Find multiple clusters of nearby vehicles
        all_clusters = _find_clusters(
            config.dsrc_range_m, config.max_vehicles, config.num_clusters,
        )
        if not all_clusters:
            logger.error("Could not find any vehicle clusters -- aborting.")
            return

        logger.info("Found %d clusters, total %d vehicles.",
                     len(all_clusters), sum(len(c) for c in all_clusters))

        # 4. Create TraciVehicle objects + platoons + network
        net = SimNetwork(scan_interval=max(0.5, 1.0 / config.time_scale))
        net.start_threads()

        colors = _cluster_colors(len(all_clusters))
        vehicles = {}       # sumo_id -> TraciVehicle
        platoons = []       # list of Platoon objects
        vehicle_color = {}  # sumo_id -> RGBA tuple
        last_color = {}     # sumo_id -> last RGBA sent (cache to avoid redundant setColor)

        for cluster_idx, cluster_ids in enumerate(all_clusters):
            platoon_id = f"COLOGNE_PLT_{cluster_idx + 1:02d}"
            platoon = Platoon(platoon_id, max_vehicles=config.max_vehicles)
            platoons.append(platoon)
            color = colors[cluster_idx]

            for member_idx, sid in enumerate(cluster_ids):
                x, y = traci.vehicle.getPosition(sid)
                speed = traci.vehicle.getSpeed(sid)
                angle = traci.vehicle.getAngle(sid)

                is_leader = member_idx == 0
                initial_energy = (
                    config.leader_min_energy_kwh + 5.0 if is_leader
                    else random.uniform(config.energy_range_low,
                                        config.energy_range_high)
                )

                v = TraciVehicle(
                    time_scale=config.time_scale,
                    charge_soc_target=config.charge_soc_target,
                    charge_cooldown_s=config.charge_cooldown_s,
                    max_charge_demand_kwh=config.max_charge_demand_kwh,
                    vehicle_id=sid,
                    battery_capacity_kwh=config.battery_capacity_kwh,
                    initial_energy_kwh=initial_energy,
                    min_energy_kwh=config.min_energy_kwh,
                    max_transfer_rate_in=config.max_transfer_rate_in,
                    max_transfer_rate_out=config.max_transfer_rate_out,
                    connection_range=config.dsrc_range_m,
                    latitude=x,
                    longitude=y,
                    heading=angle,
                    velocity=speed,
                    is_leader=is_leader,
                )

                net.register_vehicle(v)
                platoon.add_vehicle(v)

                if is_leader:
                    logger.info("[%s] Leader: %s  (SOC=%.1f kWh)",
                                platoon_id, sid, initial_energy)

                v.metrics = metrics
                v.start_threads()
                vehicles[sid] = v
                vehicle_color[sid] = color
                metrics.record_vehicle_init(sid, initial_energy, is_leader)

                # Subscribe to position/speed/angle to avoid per-vehicle
                # getter calls in the main loop (~240 TCP round-trips → ~2).
                traci.vehicle.subscribe(sid, [
                    tc.VAR_POSITION,
                    tc.VAR_SPEED,
                    tc.VAR_ANGLE,
                ])

                if not config.headless:
                    try:
                        traci.vehicle.setColor(sid, color)
                        traci.vehicle.setLength(sid, 15.0)
                        traci.vehicle.setWidth(sid, 5.0)
                    except traci.TraCIException:
                        pass

        # Zoom the GUI to the first cluster's leader so vehicles are visible
        if not config.headless:
            first_leader_id = all_clusters[0][0]
            view_id = traci.gui.getIDList()[0]
            traci.gui.trackVehicle(view_id, first_leader_id)
            traci.gui.setZoom(view_id, 800)

        logger.info(
            "%d vehicles in %d platoons running.  Waiting for HELLO -> JOIN cycle ...",
            len(vehicles), len(platoons),
        )

        # 5. Main simulation loop
        wall_start = time.monotonic()
        step_count = 0
        _PROGRESS_INTERVAL = 200  # log every 200 steps

        while True:
            try:
                if traci.simulation.getMinExpectedNumber() <= 0:
                    logger.info("No more vehicles expected -- ending simulation.")
                    break
                traci.simulationStep()
            except traci.exceptions.FatalTraCIError:
                logger.info("SUMO closed the connection -- ending simulation.")
                break
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt -- ending simulation early.")
                break

            step_count += 1

            # Enforce configured end time -- SUMO 0.32 doesn't always
            # honour --quit-on-end over TraCI, so we clamp here.
            sim_time = traci.simulation.getTime()
            metrics.set_sim_time(sim_time)
            if sim_time >= config.sumo_end:
                logger.info(
                    "Reached end time %.0f (sim_time=%.0f) -- ending.",
                    config.sumo_end, sim_time,
                )
                break
            if config.headless and step_count % _PROGRESS_INTERVAL == 0:
                n_active = len(traci.vehicle.getIDList())
                elapsed = time.monotonic() - wall_start
                logger.info(
                    "Step %d  sim_time=%.1f  active=%d  wall=%.1fs",
                    step_count, sim_time, n_active, elapsed,
                )

            active_ids = set(traci.vehicle.getIDList())

            # Read all subscription results in one batch
            all_subs = traci.vehicle.getAllSubscriptionResults()

            now = time.monotonic()

            # Push positions for tracked vehicles still in SUMO
            for sid, veh in vehicles.items():
                if sid in active_ids:
                    sub = all_subs.get(sid)
                    if sub is not None:
                        x, y = sub[tc.VAR_POSITION]
                        speed = sub[tc.VAR_SPEED]
                        angle = sub[tc.VAR_ANGLE]
                        veh.update_position(x, y, speed, angle)

                    veh.sim_tick(now, sim_time)
                    veh.maybe_send_status(now)
                    veh.refresh_edges()

                # Color platoon members by cluster, unassigned red
                if not config.headless and sid in active_ids:
                    color = vehicle_color.get(sid, _COLOR_DEFAULT) if veh.platoon is not None else _COLOR_DEFAULT
                    if last_color.get(sid) != color:
                        try:
                            traci.vehicle.setColor(sid, color)
                            last_color[sid] = color
                        except traci.TraCIException:
                            pass

            if not config.headless:
                time.sleep(0.01)

    finally:
        # Record final energy state and export metrics
        for sid, veh in vehicles.items():
            metrics.record_vehicle_final(sid, veh.available_energy())
        metrics.print_summary()
        metrics.export()
        logger.info("Metrics exported to %s/%s/",
                     config.output_dir, config.scenario_name)

        try:
            traci.close()
        except Exception:
            pass
        logger.info("TraCI connection closed.")


if __name__ == "__main__":
    main()
