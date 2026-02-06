import math

class InformationTable:
    def __init__(self):
        # Key: v_id, Value: {energy, health, connections, etc.}
        self.table = {}

    def update(self, mssg):
        """Updates the main table from the heartbeat message."""
        self.table[mssg["vehicle_id"]] = mssg

    def get_effective_stats(self, start_node, target_node):
        """
        Finds the path from target_node to start_node and calculates 
        cumulative distance and efficiency.
        """
        # 1. Find the path (BFS algorithm is best for 'hops')
        path = self._find_path(start_node, target_node)
        if not path:
            return None, 0.0, 0.0 # No connection found
        
        total_dist = 0.0
        total_eff = 1.0
        
        # 2. Step through the path to accumulate stats
        # Path looks like: ['CarA', 'CarB', 'CarC']
        for i in range(len(path) - 1):
            u = path[i]
            v = path[i+1]
            
            # Distance logic: dist(u,v)
            # (Assuming you have a helper to get distance between neighbors)
            d = self._get_neighbor_dist(u, v)
            e = self._get_neighbor_eff(u, v)
            
            total_dist += d
            total_eff *= e
            
        return path, total_dist, total_eff

    def _find_path(self, start, end):
        """Standard BFS to find the shortest hop-path between two cars."""
        queue = [[start]]
        visited = set()
        
        while queue:
            path = queue.pop(0)
            node = path[-1]
            
            if node == end:
                return path
            
            if node not in visited:
                # Look at neighbors from the 'connections' in your table
                neighbors = self.table.get(node, {}).get("connections", [])
                for neighbor in neighbors:
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append(new_path)
                visited.add(node)
        return None

    def _get_neighbor_dist(self, u_id, v_id):
        """Logic to get distance between two DIRECT neighbors."""
        # You can calculate this via X,Y coordinates if you add them to STATUS
        # or a default platoon spacing (e.g., 10 meters)
        return 10.0 

    def _get_neighbor_eff(self, u_id, v_id):
        """Logic to get efficiency between two DIRECT neighbors."""
        u_info = self.table[u_id]
        v_info = self.table[v_id]
        # Your original formula: ratio of capacities * health
        hw_eff = v_info["battery_capacity"] / max(u_info["battery_capacity"], v_info["battery_capacity"])
        return hw_eff * ((u_info["battery_health"] + v_info["battery_health"]) / 2.0)