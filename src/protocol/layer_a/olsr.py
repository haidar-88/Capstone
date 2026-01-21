import math
from src.protocol.config import ProtocolConfig

class QoS_OLSR:
    """
    Implements QoS-based Multipoint Relay (MPR) Selection.
    Refers to Section 7.3 and 7.4 of Protocol Definition.
    """

    @staticmethod
    def calculate_mobility_similarity(my_vel: tuple, neighbor_vel: tuple) -> float:
        # Dot product of velocity vectors to check alignment
        # Simple scalar similarity for now: 1.0 if same speed/direction, less otherwise
        # (vx1*vx2 + vy1*vy2) / (|v1|*|v2|)
        
        v1_mag = math.sqrt(my_vel[0]**2 + my_vel[1]**2)
        v2_mag = math.sqrt(neighbor_vel[0]**2 + neighbor_vel[1]**2)
        
        if v1_mag == 0 or v2_mag == 0:
            return 0.5 # Neutral
            
        dot = (my_vel[0]*neighbor_vel[0] + my_vel[1]*neighbor_vel[1])
        cosine_sim = dot / (v1_mag * v2_mag)
        
        # Normalize -1 to 1 -> 0 to 1
        return (cosine_sim + 1) / 2.0

    @staticmethod
    def calculate_qos_score(neighbor_data: dict, my_state: dict) -> float:
        """
        Calculates a composite QoS score for a neighbor to determine its suitability as MPR.
        Higher is better.
        
        Args:
            neighbor_data: Dictionary containing neighbor attributes:
                - battery_capacity_kwh: float
                - battery_energy_kwh: float
                - velocity: tuple (vx, vy)
                - etx: float
                - delay: float (ms)
                - willingness: int
                - lane_weight: float
                - link_stability: float
            my_state: Dictionary containing own state:
                - velocity: tuple (vx, vy)
        
        Returns:
            QoS score (higher is better)
        """
        # Weights are validated at module load time
        weights = ProtocolConfig.OLSR_WEIGHTS
        
        # 1. Battery: Calculate fraction from capacity
        battery_capacity = neighbor_data.get('battery_capacity_kwh', 100.0)
        battery_energy = neighbor_data.get('battery_energy_kwh', 50.0)
        if battery_capacity > 0:
            score_battery = min(battery_energy / battery_capacity, 1.0)
        else:
            score_battery = 0.5
        
        # 2. ETX: 1 / ETX (1.0 is perfect)
        etx = max(neighbor_data.get('etx', 1.0), 1.0)
        score_etx = 1.0 / etx
        
        # 3. Delay: Lower is better (Section 7.4)
        # Normalize delay: assume max acceptable delay is 100ms
        delay = max(neighbor_data.get('delay', 0.0), 0.0)
        max_delay = 100.0  # ms
        score_delay = max(0.0, 1.0 - (delay / max_delay))
        
        # 4. Mobility - velocity is already normalized to tuple in snapshot
        n_vel = neighbor_data.get('velocity', (0.0, 0.0))
        if not isinstance(n_vel, tuple):
            # Fallback: convert to tuple
            if isinstance(n_vel, (int, float)):
                n_vel = (float(n_vel), 0.0)
            else:
                n_vel = (0.0, 0.0)
        
        my_vel = my_state.get('velocity', (0.0, 0.0))
        if not isinstance(my_vel, tuple):
            # Normalize my_vel to tuple
            if isinstance(my_vel, (int, float)):
                my_vel = (float(my_vel), 0.0)
            else:
                my_vel = (0.0, 0.0)
        
        score_mobility = QoS_OLSR.calculate_mobility_similarity(my_vel, n_vel)
        
        # 5. Willingness (0-7): Higher is better
        willingness = neighbor_data.get('willingness', 3)
        score_willingness = max(0, min(willingness, 7)) / 7.0
        
        # 6. Lane Weight (Traffic Congestion) - Lower is better
        lane_weight = neighbor_data.get('lane_weight', 0.5)
        score_congestion = 1.0 - max(0.0, min(lane_weight, 1.0))
        
        # 7. Link Stability - Higher is better
        link_stability = neighbor_data.get('link_stability', 1.0)
        score_stability = max(0.0, min(link_stability, 1.0))
        
        total_score = (weights['battery'] * score_battery) + \
                      (weights['etx'] * score_etx) + \
                      (weights['delay'] * score_delay) + \
                      (weights['mobility'] * score_mobility) + \
                      (weights['willingness'] * score_willingness) + \
                      (weights['congestion'] * score_congestion) + \
                      (weights['stability'] * score_stability)
                      
        return total_score

    @staticmethod
    def select_mprs(context, neighbor_table):
        """
        Greedy Algorithm for MPR Selection (Standard OLSR + QoS Tie-breaking).
        Goal: Cover all strict 2-hop neighbors.
        
        Thread-safe: Uses snapshot to avoid race conditions.
        """
        
        # 1. Get thread-safe snapshot of neighbor data
        snapshot = neighbor_table.get_snapshot()
        
        # 2. Identify N1 (One-hop) and N2 (Strict Two-hop) from snapshot
        N1 = set(snapshot.keys())
        
        # Calculate N2 from snapshot
        N2 = set()
        for data in snapshot.values():
            N2.update(data['two_hop_neighbors'])
        N2.discard(context.node_id)
        N2.difference_update(N1)
        
        MPR_set = set()
        
        # Helper: Get N1 neighbors that cover a specific node in N2
        def get_covering_neighbors(n2_node):
            coverers = []
            for n1_node, data in snapshot.items():
                if n2_node in data['two_hop_neighbors']:
                    coverers.append(n1_node)
            return coverers
        
        # 3. Essential MPRs: Neighbors that are the ONLY path to some node in N2
        covered_N2 = set()
        
        for n2_node in N2:
            coverers = get_covering_neighbors(n2_node)
            if len(coverers) == 1:
                mpr = coverers[0]
                MPR_set.add(mpr)
                # Mark all N2 nodes reached by this MPR as covered
                for reached in snapshot[mpr]['two_hop_neighbors']:
                    if reached in N2:
                        covered_N2.add(reached)
                        
        remaining_N2 = N2 - covered_N2
        
        # 4. Greedy Selection for remaining N2
        while remaining_N2:
            candidates = [n for n in N1 if n not in MPR_set]
            if not candidates:
                break
                
            best_candidate = None
            best_coverage_count = -1
            best_qos_score = -1.0
            
            # Normalize velocity to tuple (vx, vy)
            vel = context.node.velocity
            if isinstance(vel, (int, float)):
                vel = (float(vel), 0.0)
            elif isinstance(vel, (list, tuple)) and len(vel) >= 2:
                vel = (float(vel[0]), float(vel[1]))
            else:
                vel = (0.0, 0.0)
                
            my_state = {'velocity': vel}
            
            for candidate in candidates:
                data = snapshot[candidate]
                
                # Calculate coverage
                provides_coverage = sum(
                    1 for reached in data['two_hop_neighbors'] 
                    if reached in remaining_N2
                )
                
                # Calculate QoS directly with dict
                qos = QoS_OLSR.calculate_qos_score(data, my_state)
                
                if provides_coverage > best_coverage_count:
                    best_coverage_count = provides_coverage
                    best_candidate = candidate
                    best_qos_score = qos
                elif provides_coverage == best_coverage_count:
                    if qos > best_qos_score:
                        best_candidate = candidate
                        best_qos_score = qos
                        
            if best_candidate and best_coverage_count > 0:
                MPR_set.add(best_candidate)
                # Update remaining
                for reached in snapshot[best_candidate]['two_hop_neighbors']:
                    remaining_N2.discard(reached)
            else:
                break
                
        return MPR_set



