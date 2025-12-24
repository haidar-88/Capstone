import unittest
from Protocol.context import MVCCPContext
from Protocol.LayerA_NeighborDiscovery.neighbor_table import NeighborTable
from Protocol.LayerA_NeighborDiscovery.olsr import QoS_OLSR
from Node import Node

class MockNode(Node):
    def __init__(self, node_id, velocity=(10,0)):
        # Minimal init for testing
        super().__init__(node_id=node_id, 
                         battery_capacity_kwh=100.0, 
                         battery_energy_kwh=50.0, 
                         min_energy_kwh=10.0,
                         velocity=velocity)
        # Init QoS fields default
        self.etx = 1.0
        self.willingness = 3
        self.lane_weight = 0.5
        self.link_stability = 1.0

class TestLayer1(unittest.TestCase):
    def setUp(self):
        self.node = MockNode(b'A')
        self.context = MVCCPContext(self.node)
        self.table = NeighborTable(self.context)

    def test_neighbor_update(self):
        # Verify that passing real attributes updates the node
        attrs_dict = {
            'battery_capacity_kwh': 100.0,
            'battery_energy_kwh': 80.0, 
            'velocity': (10.0, 0.0),
            'etx': 1.0,
            'willingness': 3
        }
        
        self.table.update_neighbor(b'B', attrs_dict, [])
        self.assertIn(b'B', self.table.neighbors)
        neighbor = self.table.neighbors[b'B']
        self.assertEqual(neighbor.battery_energy_kwh, 80.0) 
        self.assertEqual(neighbor.etx, 1.0) 

    def test_olsr_mpr_selection(self):
        # Topology: A <-> B <-> C
        # B needs to cover C.
        
        # B connects to C (update B's entry to say it sees C)
        self.table.update_neighbor(b'B', {'velocity': (10,0)}, [b'C'])
        
        mprs = QoS_OLSR.select_mprs(self.context, self.table)
        self.assertIn(b'B', mprs)

    def test_qos_tie_break(self):
        # A needs to cover D.
        # B and C both cover D.
        # B has high battery (90%), C has low battery (10%).
        
        # B: 90%
        b_attrs = {
            'battery_capacity_kwh': 100.0,
            'battery_energy_kwh': 90.0,
            'etx': 1.0,
            'velocity': (10,0),
            'willingness': 3,
            'lane_weight': 0.5,
            'link_stability': 1.0
        }
        self.table.update_neighbor(b'B', b_attrs, [b'D'])
        
        # C: 10%
        c_attrs = {
            'battery_capacity_kwh': 100.0,
            'battery_energy_kwh': 10.0,
            'etx': 1.0,
            'velocity': (10,0),
            'willingness': 3,
            'lane_weight': 0.5,
            'link_stability': 1.0
        }
        self.table.update_neighbor(b'C', c_attrs, [b'D'])
        
        mprs = QoS_OLSR.select_mprs(self.context, self.table)
        
        # Since B has much better battery, it should be selected. 
        # (Both cover D, so coverage is equal).
        self.assertIn(b'B', mprs)
        self.assertNotIn(b'C', mprs)
