from messages import MessageType, HelloMessage, TLVType
from .neighbor_table import NeighborTable
from .olsr import QoS_OLSR
import struct
from .neighbor_table import NeighborTable
from .olsr import QoS_OLSR

class NeighborDiscoveryHandler:
    def __init__(self, context):
        self.context = context
        self.neighbor_table = NeighborTable(context)
        self.context.neighbor_table = self.neighbor_table # Link back to context

    def handle_hello(self, message: HelloMessage):
        sender_id = message.header.sender_id
        
        # Parse TLVs
        neighbor_list_bytes = message.get_tlv_value(TLVType.NEIGHBOR_LIST)
        node_attrs_bytes = message.get_tlv_value(TLVType.NODE_ATTRIBUTES)
        metrics_bytes = message.get_tlv_value(TLVType.METRICS)
        
        # Decode Neighbor List
        two_hop_neighbors = []
        if neighbor_list_bytes:
            chunk_size = 6
            for i in range(0, len(neighbor_list_bytes), chunk_size):
                two_hop_neighbors.append(neighbor_list_bytes[i:i+chunk_size])
                
        # Prepare combined attributes for Node update
        combined_attrs = {}
        
        # 1. Decode Node Attributes (Physical)
        if node_attrs_bytes:
            # Format: ! f f f f f f f f f f
            # 1. Cap(f), 2. Cur(f), 3. Min(f), 4. MaxIn(f), 5. MaxOut(f)
            # 6. Lat(f), 7. Lon(f), 8. Vx(f), 9. Vy(f), 10. Health(f)
            try:
                unpacked = struct.unpack("!ffffffffff", node_attrs_bytes)
                combined_attrs['battery_capacity_kwh'] = unpacked[0]
                combined_attrs['battery_energy_kwh'] = unpacked[1]
                combined_attrs['min_energy_kwh'] = unpacked[2]
                combined_attrs['max_transfer_rate_in'] = unpacked[3]
                combined_attrs['max_transfer_rate_out'] = unpacked[4]
                combined_attrs['latitude'] = unpacked[5]
                combined_attrs['longitude'] = unpacked[6]
                combined_attrs['velocity'] = (unpacked[7], unpacked[8])
                combined_attrs['battery_health'] = unpacked[9]
            except struct.error as e:
                print(f"Error unpacking node attributes from {sender_id}: {e}")
                
        # 2. Decode Metrics (QoS)
        if metrics_bytes:
            # Format: ! f B f f
            # 1. ETX(f), 2. Willingness(B), 3. Lane(f), 4. Link(f)
            try:
                unpacked = struct.unpack("!fBff", metrics_bytes)
                combined_attrs['etx'] = unpacked[0]
                combined_attrs['willingness'] = unpacked[1]
                combined_attrs['lane_weight'] = unpacked[2]
                combined_attrs['link_stability'] = unpacked[3]
            except struct.error as e:
                print(f"Error unpacking metrics from {sender_id}: {e}")
        
        # Update Table
        self.neighbor_table.update_neighbor(sender_id, combined_attrs, two_hop_neighbors)
        
        # Recalculate MPRs
        self.recalculate_mpr()

    def recalculate_mpr(self):
        new_mprs = QoS_OLSR.select_mprs(self.context, self.neighbor_table)
        self.context.mpr_set = new_mprs

    def create_hello_message(self) -> HelloMessage:
        # Construct Neighbor List (N1)
        n1_neighbors = self.neighbor_table.get_one_hop_set()
        neighbor_list_bytes = b"".join(n1_neighbors) 
        
        node = self.context.node
        
        vx, vy = 0.0, 0.0
        if isinstance(node.velocity, (tuple, list)):
             vx, vy = node.velocity
        else:
             vx, vy = float(node.velocity), 0.0
             
        # 1. Node Attributes (!ffffffffff)
        node_attrs = [
            getattr(node, 'battery_capacity_kwh', 100.0),
            getattr(node, 'battery_energy_kwh', 50.0),
            getattr(node, 'min_energy_kwh', 10.0),
            getattr(node, 'max_transfer_rate_in', 50.0),
            getattr(node, 'max_transfer_rate_out', 50.0),
            getattr(node, 'latitude', 0.0),
            getattr(node, 'longitude', 0.0),
            vx, vy,
            getattr(node, 'battery_health', 1.0)
        ]
        
        attr_bytes = struct.pack("!ffffffffff", *node_attrs)

        # 2. Metrics (!fBff)
        metrics = [
            getattr(node, 'etx', 1.0),
            getattr(node, 'willingness', 3),
            getattr(node, 'lane_weight', 0.5),
            getattr(node, 'link_stability', 1.0)
        ]
        
        metrics_bytes = struct.pack("!fBff", *metrics)
        
        msg = HelloMessage(
            ttl=self.context.msg_ttl, 
            seq_num=int(self.context.current_time),
            sender_id=self.context.node_id,
            neighbor_list=neighbor_list_bytes
        )
        
        from messages import TLV
        msg.add_tlv(TLV(TLVType.NODE_ATTRIBUTES, attr_bytes))
        msg.add_tlv(TLV(TLVType.METRICS, metrics_bytes))
        
        return msg
