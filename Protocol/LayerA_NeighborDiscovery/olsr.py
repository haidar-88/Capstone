import math

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
    def calculate_qos_score(neighbor_entry, my_state) -> float:
        """
        Calculates a composite QoS score for a neighbor to determine its suitability as MPR.
        Higher is better.
        Metrics:
        - Battery Level (High is better)
        - Link Stability/ETX (Low ETX is better)
        - Mobility Similarity (High is better)
        """
        import random
        # Weights (Randomized as requested for now)
        weights = {
            'battery': random.uniform(0.1, 0.4),
            'etx': random.uniform(0.1, 0.4),
            'mobility': random.uniform(0.1, 0.4),
            'willingness': random.uniform(0.0, 0.2), # Lower impact
            'congestion': random.uniform(0.0, 0.2),
            'stability': random.uniform(0.0, 0.2)
        }
        
        # Normalize weights to sum to 1.0
        total_weight = sum(weights.values())
        for k in weights:
            weights[k] /= total_weight
            
        # 1. Battery: Calculate fraction from Node fields
        # Node has battery_energy_kwh and battery_capacity_kwh
        if neighbor_entry.battery_capacity_kwh > 0:
            score_battery = neighbor_entry.battery_energy_kwh / neighbor_entry.battery_capacity_kwh
        else:
            score_battery = 0.5
        if score_battery > 1.0: score_battery = 1.0
        
        # 2. ETX: 1 / ETX (1.0 is perfect)
        score_etx = 1.0 / max(neighbor_entry.etx, 1.0)
        
        # 3. Mobility
        n_vel = neighbor_entry.velocity
        if isinstance(n_vel, (int, float)):
             n_vel = (n_vel, 0.0)
        score_mobility = QoS_OLSR.calculate_mobility_similarity(
            my_state['velocity'], n_vel
        )
        
        # 4. Willingness (0-7): Higher is better
        score_willingness = neighbor_entry.willingness / 7.0
        
        # 5. Lane Weight (Traffic Congestion) - Lower is better
        score_congestion = 1.0 - neighbor_entry.lane_weight
        
        # 6. Link Stability - Higher is better
        score_stability = neighbor_entry.link_stability
        
        total_score = (weights['battery'] * score_battery) + \
                      (weights['etx'] * score_etx) + \
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
        """
        
        # 1. Identify N1 (One-hop) and N2 (Strict Two-hop)
        N1 = neighbor_table.get_one_hop_set()
        N2 = neighbor_table.get_two_hop_set()
        
        MPR_set = set()
        
        # Helper: Get N1 neighbors that cover a specific node in N2
        def get_covering_neighbors(n2_node):
            coverers = []
            for n1_node in N1:
                entry = neighbor_table.neighbors[n1_node]
                if n2_node in entry.two_hop_neighbors:
                    coverers.append(n1_node)
            return coverers
            
        # 2. Essential MPRs: Neighbors that are the ONLY path to some node in N2
        covered_N2 = set()
        
        for n2_node in N2:
            coverers = get_covering_neighbors(n2_node)
            if len(coverers) == 1:
                mpr = coverers[0]
                MPR_set.add(mpr)
                # Mark all N2 nodes reached by this MPR as covered
                entry = neighbor_table.neighbors[mpr]
                for reached in entry.two_hop_neighbors:
                    if reached in N2:
                        covered_N2.add(reached)
                        
        remaining_N2 = N2 - covered_N2
        
        # 3. Greedy Selection for remaining N2
        while remaining_N2:
            # Candidate set: N1 nodes not yet in MPR_set
            candidates = [n for n in N1 if n not in MPR_set]
            if not candidates:
                break # Should not happen if graph is connected
                
            best_candidate = None
            best_coverage_count = -1
            best_qos_score = -1.0
            
            # Ensure velocity is a tuple (vx, vy)
            vel = context.node.velocity
            if isinstance(vel, (int, float)):
                vel = (vel, 0.0) # Assume X-axis alignment if scalar
                
            my_state_dummy = {'velocity': vel}
            
            for candidate in candidates:
                # Calculate how many UNCOVERED N2 nodes this candidate covers
                entry = neighbor_table.neighbors[candidate]
                provides_coverage = 0
                for reached in entry.two_hop_neighbors:
                    if reached in remaining_N2:
                        provides_coverage += 1
                        
                # Selection Criteria 1: Coverage Count
                # Selection Criteria 2: QoS Score
                qos = QoS_OLSR.calculate_qos_score(entry, my_state_dummy)
                
                if provides_coverage > best_coverage_count:
                    best_coverage_count = provides_coverage
                    best_candidate = candidate
                    best_qos_score = qos
                elif provides_coverage == best_coverage_count:
                    # Tie-break with QoS
                    if qos > best_qos_score:
                        best_candidate = candidate
                        best_qos_score = qos
                        
            if best_candidate and best_coverage_count > 0:
                MPR_set.add(best_candidate)
                # Update covered set
                entry = neighbor_table.neighbors[best_candidate]
                for reached in entry.two_hop_neighbors:
                    if reached in remaining_N2:
                        remaining_N2.remove(reached)
            else:
                # No candidate improves coverage (shouldn't happen)
                break
                
        return MPR_set
