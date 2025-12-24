import time

class MVCCPContext:
    def __init__(self, node):
        self.node = node  # The physical Node object
        
        # Identity
        self.node_id = node.node_id
        
        # Configuration
        self.hello_interval = 1.0  # seconds
        self.pa_interval = 5.0     # seconds
        self.msg_ttl = 4           # hops
        
        # Network Interface Callback
        # This function should be set by the Network Interface (e.g. ns3 adapter)
        # Signature: callback(data: bytes)
        self.send_callback = None
        
        # State
        self.last_hello_time = 0.0
        self.last_pa_time = 0.0
        
        # Layer 1 Data
        self.neighbor_table = None # Initialized in Layer 1 handler
        self.mpr_set = set()       # Set of neighbor IDs selected as MPRs
        self.mpr_selector_set = set() # Set of neighbors that selected ME as MPR
        
        # Layer 2 Data
        self.provider_table = None # Initialized in Layer 2 handler
        
        # Layer 3 Data
        self.consumer_state = None
        self.provider_state = None
        
        # Time Management
        self.current_time = time.time()

    def update_time(self, timestamp):
        self.current_time = timestamp
