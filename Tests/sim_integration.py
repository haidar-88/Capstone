from Protocol.context import MVCCPContext
from Protocol.LayerA_NeighborDiscovery import NeighborDiscoveryHandler
from Protocol.LayerB_ProviderAnnouncement import ProviderAnnouncementHandler
from Protocol.LayerC_ChargingCoordination import ChargingCoordinationHandler, ConsumerState
from messages import PAMessage

class MockPhysicalNode:
    def __init__(self, node_id):
        self.node_id = node_id
        self.velocity = (10.0, 0.0)
        self.battery_capacity_kwh = 100.0
        self.battery_energy_kwh = 80.0
        self.latitude = 0.0
        self.longitude = 0.0
        self.etx = 1.0
        self.willingness = 3
        self.lane_weight = 0.5
        self.link_stability = 1.0

def run_sim():
    print("--- Starting Integration Simulation ---")
    
    # Setup Node A (Consumer)
    node_a = MockPhysicalNode(b'NODE_A')
    ctx_a = MVCCPContext(node_a)
    l1_a = NeighborDiscoveryHandler(ctx_a)
    l2_a = ProviderAnnouncementHandler(ctx_a)
    l3_a = ChargingCoordinationHandler(ctx_a)
    
    # Setup Node B (Provider)
    node_b = MockPhysicalNode(b'NODE_B')
    ctx_b = MVCCPContext(node_b)
    
    # 1. Neighbor Discovery Simulation
    # Assume A receives HELLO from B
    print("\n[Step 1] Neighbor Discovery")
    # Manually populating table for brevity
    # USE NEW KEYS
    attrs = {
        'battery_energy_kwh': 90.0,
        'etx': 1.0,
        'velocity': (10.0, 0.0)
    }
    l1_a.neighbor_table.update_neighbor(b'NODE_B', attrs, [])
    print(f"Node A Neighbors: {list(l1_a.neighbor_table.neighbors.keys())}")
    
    # 2. Provider Announcement
    print("\n[Step 2] Provider Announcement")
    # B sends PA -> A receives
    pa_msg = PAMessage(ttl=4, seq_num=1, sender_id=b'NODE_B', provider_id=b'NODE_B', energy_available=b'\xFF')
    l2_a.handle_pa(pa_msg)
    
    best = l2_a.provider_table.get_best_provider()
    if best:
        print(f"Node A discovered provider: {best.provider_id}")
    
    # 3. Charging Coordination
    print("\n[Step 3] Charging Logic")
    # Trigger A to look for provider
    l3_a.process_discovery()
    
    if ctx_a.consumer_state == ConsumerState.WAIT_ACCEPT:
        print("SUCCESS: Node A transitioned to WAIT_ACCEPT")
    else:
        print(f"FAILURE: Node A state is {ctx_a.consumer_state}")

if __name__ == "__main__":
    run_sim()
