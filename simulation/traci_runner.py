"""
TraCI live runner -- MVCCP over TAPASCologne with sumo-gui.

Usage::

    python -m simulation.traci_runner

Opens sumo-gui showing Cologne traffic.  A cluster of nearby vehicles
is selected, wrapped in TraciVehicle objects, and run through the full
MVCCP protocol.  Protocol logs print to the terminal in real time.
"""

import logging
import os
import random
import time

import traci
import traci.constants as tc

from simulation.traci_vehicle import TraciVehicle
from simulation.sim_network import SimNetwork
from network.platoon import Platoon
from protocol import messages

logger = logging.getLogger(__name__)

# --- Paths ---------------------------------------------------------------
_SUMO_CFG = os.path.join("TAPASCologne-0.32.0", "cologne6to8.sumocfg")

# --- Simulation window ----------------------------------------------------
_SUMO_BEGIN = 21600  # 06:00
_SUMO_END = 22800    # 06:20

# --- Protocol / battery constants -----------------------------------------
_DSRC_RANGE_M = 100.0
_MAX_VEHICLES = 6
_NUM_CLUSTERS = 10
_BATTERY_CAPACITY_KWH = 80.0
_MIN_ENERGY_KWH = 10.0
_ENERGY_RANGE = (15.0, 45.0)
_LEADER_MIN_ENERGY_KWH = 50.0
_TIME_SCALE = 60.0
_MAX_TRANSFER_RATE_IN = 50.0
_MAX_TRANSFER_RATE_OUT = 50.0

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

# --- Warmup / timing ------------------------------------------------------
_WARMUP_STEPS = 500
_MIN_VEHICLES_FOR_CLUSTER = 150


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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[traci] %(levelname)s %(message)s",
    )

    if not os.path.isfile(_SUMO_CFG):
        logger.error("SUMO config not found: %s", _SUMO_CFG)
        raise SystemExit(1)

    # 1. Start sumo-gui via TraCI
    logger.info("Starting sumo-gui ...")
    traci.start([
        "sumo-gui", "-c", _SUMO_CFG,
        "--begin", str(_SUMO_BEGIN),
        "--end", str(_SUMO_END),
        "--start",
        "--quit-on-end",
    ], numRetries=120)

    logger.info("Waiting for GUI to render the network ...")
    # Pump ~100 simulation steps instead of sleeping 10s so the GUI stays
    # responsive while the Cologne map renders.
    for _ in range(100):
        traci.simulationStep()
        time.sleep(0.1)

    try:
        # 2. Warmup -- step until enough vehicles exist
        logger.info("Warming up (%d steps) ...", _WARMUP_STEPS)
        for _ in range(_WARMUP_STEPS):
            traci.simulationStep()
            if len(traci.vehicle.getIDList()) >= _MIN_VEHICLES_FOR_CLUSTER:
                break
            time.sleep(0.01)  # let sumo-gui process window events

        # 3. Find multiple clusters of nearby vehicles
        all_clusters = _find_clusters(_DSRC_RANGE_M, _MAX_VEHICLES, _NUM_CLUSTERS)
        if not all_clusters:
            logger.error("Could not find any vehicle clusters -- aborting.")
            return

        logger.info("Found %d clusters, total %d vehicles.",
                     len(all_clusters), sum(len(c) for c in all_clusters))

        # 4. Create TraciVehicle objects + platoons + network
        net = SimNetwork(scan_interval=max(0.5, 1.0 / _TIME_SCALE))
        net.start_threads()

        colors = _cluster_colors(len(all_clusters))
        vehicles = {}       # sumo_id -> TraciVehicle
        platoons = []       # list of Platoon objects
        vehicle_color = {}  # sumo_id -> RGBA tuple
        last_color = {}     # sumo_id -> last RGBA sent (cache to avoid redundant setColor)

        for cluster_idx, cluster_ids in enumerate(all_clusters):
            platoon_id = f"COLOGNE_PLT_{cluster_idx + 1:02d}"
            platoon = Platoon(platoon_id)
            platoons.append(platoon)
            color = colors[cluster_idx]

            for member_idx, sid in enumerate(cluster_ids):
                x, y = traci.vehicle.getPosition(sid)
                speed = traci.vehicle.getSpeed(sid)
                angle = traci.vehicle.getAngle(sid)

                is_leader = member_idx == 0
                initial_energy = (
                    _LEADER_MIN_ENERGY_KWH + 5.0 if is_leader
                    else random.uniform(*_ENERGY_RANGE)
                )

                v = TraciVehicle(
                    time_scale=_TIME_SCALE,
                    vehicle_id=sid,
                    battery_capacity_kwh=_BATTERY_CAPACITY_KWH,
                    initial_energy_kwh=initial_energy,
                    min_energy_kwh=_MIN_ENERGY_KWH,
                    max_transfer_rate_in=_MAX_TRANSFER_RATE_IN,
                    max_transfer_rate_out=_MAX_TRANSFER_RATE_OUT,
                    connection_range=_DSRC_RANGE_M,
                    latitude=x,
                    longitude=y,
                    heading=angle,
                    velocity=speed,
                    is_leader=is_leader,
                )

                net.register_vehicle(v)
                if is_leader:
                    platoon.add_vehicle(v)

                if is_leader:
                    logger.info("[%s] Leader: %s  (SOC=%.1f kWh)",
                                platoon_id, sid, initial_energy)

                v.start_threads()
                vehicles[sid] = v
                vehicle_color[sid] = color

                # Subscribe to position/speed/angle to avoid per-vehicle
                # getter calls in the main loop (~240 TCP round-trips → ~2).
                traci.vehicle.subscribe(sid, [
                    tc.VAR_POSITION,
                    tc.VAR_SPEED,
                    tc.VAR_ANGLE,
                ])

                try:
                    traci.vehicle.setColor(sid, color)
                    traci.vehicle.setLength(sid, 15.0)   # ~3.5x real size
                    traci.vehicle.setWidth(sid, 5.0)     # wider for visibility
                except traci.TraCIException:
                    pass

        # Zoom the GUI to the first cluster's leader so vehicles are visible
        first_leader_id = all_clusters[0][0]
        view_id = traci.gui.getIDList()[0]
        traci.gui.trackVehicle(view_id, first_leader_id)
        traci.gui.setZoom(view_id, 800)

        logger.info(
            "%d vehicles in %d platoons running.  Waiting for HELLO -> JOIN cycle ...",
            len(vehicles), len(platoons),
        )

        # 5. Main simulation loop
        charge_triggered = False
        wall_start = time.monotonic()

        while True:
            try:
                if traci.simulation.getMinExpectedNumber() <= 0:
                    logger.info("No more vehicles expected -- ending simulation.")
                    break
                traci.simulationStep()
            except traci.exceptions.FatalTraCIError:
                logger.info("SUMO closed the connection -- ending simulation.")
                break

            active_ids = set(traci.vehicle.getIDList())

            # Read all subscription results in one batch (replaces
            # ~240 individual getter calls with a single dict lookup).
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

                    # Main-loop-driven work (replaces tick + status threads)
                    veh.sim_tick(now)
                    veh.maybe_send_status(now)
                    veh.refresh_edges()

                # Color platoon members by cluster, unassigned red
                # Only send setColor when the color actually changes.
                if sid in active_ids:
                    color = vehicle_color.get(sid, _COLOR_DEFAULT) if veh.platoon is not None else _COLOR_DEFAULT
                    if last_color.get(sid) != color:
                        try:
                            traci.vehicle.setColor(sid, color)
                            last_color[sid] = color
                        except traci.TraCIException:
                            pass

            # After ~30 s wall-clock, trigger CHARGE_RQST per platoon
            elapsed = now - wall_start
            if not charge_triggered and elapsed >= 30.0:
                charge_triggered = True
                _trigger_charges(vehicles, platoons)

            time.sleep(0.01)  # yield briefly -- main thread needs GIL time

    finally:
        traci.close()
        logger.info("TraCI connection closed.")


def _trigger_charges(vehicles, platoons):
    """Send one CHARGE_RQST per platoon from its lowest-energy non-leader."""
    for platoon in platoons:
        non_leaders = [
            v for v in platoon.vehicles
            if not v.is_leader
        ]

        if not non_leaders:
            logger.warning("[%s] No non-leader members -- skipping CHARGE_RQST.",
                           platoon.platoon_id)
            continue

        consumer = min(non_leaders, key=lambda v: v.available_energy())
        logger.info(
            "[%s] CHARGE_RQST from %s (SOC=%.1f kWh, demand=20 kWh)",
            platoon.platoon_id,
            consumer.vehicle_id,
            consumer.available_energy(),
        )
        consumer.send_protocol_message(
            messages.CHARGE_RQST_message, consumer.vehicle_id, 20
        )


if __name__ == "__main__":
    main()
