**1\. Identify Your "Competitive Advantage"**

Since the AI found that most papers are "qualitative" (they say it's better but don't show the exact numbers), your goal is to be **strictly quantitative**.

- **The Target to Beat:** The results mentioned **22.2% energy savings** and **120ms delay**. Your goal is to design a multi-hop system that either:
  - Achieves >25% energy savings.
  - Reduces delay to <100ms.
  - Maintains a **Jain's Fairness Index** above **0.90**.

**2\. Implementation: The "Metric-First" Approach**

Because "Battery Threshold Arrival" is the missing metric in the literature, make it your **Primary Key Performance Indicator (KPI)**.

**How to calculate your metrics for comparison:**

- **For Fairness:** Use the **Jain's Fairness Index** formula. If you have \$n\$ energy providers and \$x_i\$ is the amount of energy each provides, the index \$J\$ is:

\$\$J(x*1, x_2, \\dots, x_n) = \\frac{(\\sum*{i=1}^n x*i)^2}{n \\cdot \\sum*{i=1}^n x_i^2}\$\$

_Aim for a result close to 1.0._

- **For Efficiency:** Measure the ratio of energy received by the AEV to the energy depleted from the RSU/Provider vehicle.

**3\. Your Simulation Stack Setup**

Scopus confirmed that **SUMO + Veins** or **NS-3** are the expected standards.

- **Action:** If you haven't started simulation yet, use **Veins (OMNeT++ + SUMO)**. It is the most robust for coupling "battery drain" (energy models) with "message delay" (network models).
- **Scenario Design:** Create two environments:
  - **Urban (Grid):** High density, many multi-hop opportunities.
  - **Highway (Platoon):** High speed, focus on the "Fairness" of the mobile energy providers in the line.

**4\. Refined Research Question**

You can now pivot your thesis statement to something very specific that reviewers will love:

_"While current literature acknowledges the potential of multi-hop wireless charging, there is a lack of quantitative benchmarking for AEV arrival success rates. This study fills that gap by using AI-optimized protocols to achieve a \[X\]% arrival rate while maintaining a Jain's Fairness Index of \[Y\]."_

**Comparison Checklist (Your "To-Do" List)**

Use this table to track how you are doing against the "Scopus Benchmarks" you just found:

| **Metric**              | **Scopus "SOTA"** | **Your Target**                           |
| ----------------------- | ----------------- | ----------------------------------------- |
| **Arrival Rate**        | "Often Missing"   | **Define a clear % (e.g., 90%)**          |
| **Transfer Efficiency** | 80% - 95%         | **92%+ (Using AI optimization)**          |
| **Comm. Delay**         | ~120 ms           | **< 100 ms (via decentralized protocol)** |
| **Fairness Index**      | 0.78 - 0.92       | **\> 0.90**                               |

PAPERS BELOW

**Dynamic Path-Planning and Charging Optimization for**

**Autonomous Electric Vehicles in Transportation Networks**

**1\. Communication & Information Metrics**

These metrics directly relate to "Low delay" and "Transfer efficiency" (of data) goals.

- **Packet Delivery Ratio (PDR):** This measures how many data packets successfully reach their destination. In simulations of 50-250 vehicles, the proposed relay selection method maintained a PDR between **~90% and 98%**, significantly higher than standard protocols like AODV.
- **End-to-End Delay:** This measures the time it takes for a message to travel through the multi-hop network. For the same vehicle densities, the delay ranged from approximately **0.02s to 0.08s**, which is crucial for real-time charging decisions.
- **Link Stability & Service Satisfaction:** The paper selects relay vehicles based on a "reputation" or "service satisfaction" value (\$S\_{kh}\$), which ensures reliable data transfer across the network.

**2\. Battery & Energy Metrics**

These align with your "Arrival Battery" and "Transfer efficiency" (of power) goals.

- **Arrival/Threshold SoC:** The paper initializes vehicles with a **40% SoC** and uses a charging threshold (\$\\Omega\$) to trigger a search for a station.
- **Target SoC:** Vehicles at Charging Stations (CS) are typically charged to **90% capacity**.
- **Energy Segment (ES) Efficiency:** The paper uses a variable \$\\lambda\$ to represent charging efficiency per unit of time on Energy Segments (wireless charging roads). In their examples, ES charging is often shorter than CS charging because the car only charges for the length of that specific road segment.

**3\. Efficiency & Cost Metrics**

These allow you to compare how much "better" your AI-optimized system is.

- **Queuing & Charging Time Reduction:** The proposed DRT-CS algorithm reduced average queuing time by **4.85 minutes** and charging time by **6.11 minutes** compared to standard algorithms (like CA\*).
- **Travel Cost:** The total "cost" is a mathematical combination of travel time, queuing time, charging time, and energy consumption.

**Comparison Table for Your Metrics**

| **Your Metric**                  | **Equivalent Paper Metric**  | **Reported Quantities**                                                                                                     |
| -------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Arrival Battery > Threshold**  | Arrival SoC & Target SoC     | Start: 40%; Target: 90%                                                                                                     |
| **Transfer Efficiency (Energy)** | Charging Rate & \$\\lambda\$ | Tested with a 70 kWh charging rate                                                                                          |
| **Low Message Delay**            | End-to-End Delay             | **0.02s - 0.08s**                                                                                                           |
| **Fairness (Provider usage)**    | Load Distribution            | The paper focuses on **minimizing individual cost**, but mentions distributing vehicles to avoid queues (indirect fairness) |

Note: No v2v charging here, only info sharing and communication. No platoons

In this paper, information is shared through a **decentralized, cooperative communication network** where each car essentially acts as an individual decision-maker, but they rely on each other to pass information along.

There is **no mention of platoons** (groups of cars traveling closely together) in this research . Instead, the system treats each vehicle as an independent node in a **Vehicular Ad Hoc Network (VANET)**.

Here is exactly how the information sharing works:

### 1\. Are they "on their own"?

- **Decisions are individual:** Each Autonomous Electric Vehicle (AEV) uses its own computer system and the **DRT-A**\* algorithm to plan its own path and charging schedule.
- **Distributed Decision-Making:** The paper emphasizes "distributed decision-making," meaning there is no central "brain" telling every car where to go. Each car makes the best choice for itself based on the data it has.

### 2\. How the "Joint Push-Pull" Sharing Works

Information is shared between vehicles and the infrastructure using two methods simultaneously:

- **The "Push" (Passive Sharing):** Roadside Units (RSUs) constantly broadcast general traffic and charging information to all nearby cars.
- **The "Pull" (Active Requesting):** When a car's battery drops below a certain threshold, it "pulls" (requests) specific, detailed data from the network about the nearest charging stations or wireless charging roads.

### 3\. Cooperative Relaying (Multi-Hop)

While the cars aren't in platoons, they do work together as **relays**.

- **The Problem:** An RSU at an intersection might only have a range of a few hundred meters.
- **The Solution:** If a car is too far from an RSU to get an update, it sends a request to a car in front of it. That car passes the message to the next car, and so on, until it reaches the RSU.
- **Relay Selection:** The system doesn't just pick any car; it chooses "relay vehicles" based on **link stability** (how likely the connection is to stay solid) and **distance**.

Comprehensive review of wireless power transfer systems for electric vehicle charging applications

**1\. Transfer Efficiency (Energy Loss)**

This is the most extensively documented metric in the paper, referred to as **Power Transfer Efficiency (PTE)**.

- **General Performance:** Modern WPT systems (including Inductive, Capacitive, and Hybrid) consistently achieve efficiencies **greater than 90%**.
- **Specific Benchmarks:**
  - **Coil Designs:** An asymmetrical bipolar coil design achieved a peak efficiency of **96.95%** for unipolar receivers and **91%** for bipolar receivers.
  - **Hybrid Systems:** Systems combining inductive and capacitive methods maintain a stable efficiency of **85.82%**.
  - **Distance/Gap:** Efficiency of **\>90%** is maintained at air gaps up to **20 cm (200 mm)**.
  - **Future Targets:** The paper identifies a goal of reaching **\>95% efficiency** for high-power levels (over 150 kW).

**2\. Battery Threshold & Arrival (Range Anxiety)**

The paper does not provide a specific numerical success rate for "arrival with charge > threshold," but it frames this as the primary problem:

- **Range Anxiety:** The paper identifies "anxiety range" (the efficiency of battery power to reach a destination) as one of the most common issues for EV users.
- **Current Factors:** Traditional charging considerations cited include **"current battery level"** and **"battery capacity"**.
- **Impact:** The goal of WPT deployment is to alleviate this anxiety by increasing charging points, with the paper noting a potential **30% reduction** in infrastructure costs to support wider accessibility.

**3\. Message/Packet Delay (Communication)**

Instead of providing latency quantities (like milliseconds), the paper focuses on **Communication-Independent Control** to bypass delay issues entirely.

- **Techniques:** Approaches like **Constant Maximum Power Point Tracking (CMPPT)** are designed to ensure optimal power transfer in systems where **"communication is impossible or unstable"**.
- **System Complexity:** Active rectifier-based control is highlighted for its ability to **lower the cost and complexity of communication subsystems**.
- **Standards:** It mentions standards like **SAE J2954** and **CCS DC** for interface communication but does not list specific delay/latency performance values.

**4\. Fairness for Energy Transfer (Interoperability)**

The paper addresses "fairness" through **interoperability** and **shared charging** rather than a single provider model.

- **Provider Diversity:** It emphasizes **interoperability** across different EV models and receiver types (unipolar, bipolar, and quadrupolar), achieving **\>85% efficiency** across all types to ensure the system is not restricted to specific vehicles.
- **V2V and V2G:** Emerging directions include **Vehicle-to-Vehicle (V2V)** and **Vehicle-to-Grid (V2G)** integration, which allows energy sharing among multiple users and providers rather than a centralized source.
- **Misalignment Tolerance:** Advanced designs improved misalignment tolerance by **30%**, ensuring that energy transfer remains fair and effective even if the vehicle is not perfectly positioned.

**Summary of Quantities for Comparison**

| **Metric**              | **Paper Quantity/Value**                                    |
| ----------------------- | ----------------------------------------------------------- |
| **PTE (Efficiency)**    | **\>90%** (General); **96.95%** (Peak); **85.82%** (Hybrid) |
| **Power Output**        | **3.7 kW to 150 kW**                                        |
| **Distance Tolerance**  | Up to **20 cm**                                             |
| **Infrastructure Cost** | **25-30% reduction** through WPT deployment                 |
| **Environmental**       | **50% reduction** in greenhouse gas emissions by 2040       |

Note: No platoons also

There is V2V charging but we can do the > 150 kW to cover this gap

**Future Research Directions**: The assessment identifies new research topics such as V2G integration, V2V charging, and AI-driven WPT optimization. It suggests specific research objectives to tackle technological issues, including increasing misalignment tolerance in dynamic settings and reaching > 95% efficiency at larger power levels such as > 150 kW.

---

## External Comparison

### Paper Roles

| ID | Paper | Role |
|----|-------|------|
| P3 | Abualola 2021, "V2V Charging Allocation over QoS-OLSR" | **Primary benchmark** — same architecture (QoS-OLSR/MPR, PA phase, provider-consumer allocation) |
| P4 | Tang 2024, "Discharging Driven Energy Sharing" | **Secondary benchmark** — same problem family, reports P3 numbers as "V2V-CA" baseline |
| P1 | Tang 2023, "Dynamic Path-Planning and Charging Optimization" | Parameter alignment only — different problem (V2I infrastructure routing, not V2V) |
| P2 | Abuajwa 2025, "WPT Review" | Citation source for SAE J2954 power classes and ≥90% WPT efficiency numbers |
| P5 | Liu et al., "EV Assignment for Platoon-based Charging" | Conceptual citation for multi-hop platoon charging model |

### Metric Mapping

| Our Metric | P3 Metric | P4 Metric | Notes |
|------------|-----------|-----------|-------|
| `pdr_<type>` + `pdr_unicast_avg` | Packet Delivery Ratio (PDR) | PDR | Per unicast message type (HELLO, JOIN_OFFER, JOIN_ACCEPT, ACK, CHARGE_SYN, CHARGE_ACK, ENERGY_PACKET, CHARGE_FIN). P3 §6.2 reports 90–98 %. See "Known limitations" for why ours sits near 100 %. |
| `avg_rqst_to_packet_gap_s` | End-to-End Delay (loose) | E2E Delay | P3 §6.2 reports 20–80 ms of wireless latency. **Our value is sim-time seconds, not wall-clock ms**: we measure the simulated gap between a consumer's CHARGE_RQST and the first ENERGY_PACKET it receives. No layer-3 transport is modelled, so this is protocol-handshake latency, not DSRC latency. Renamed (and rescaled) from the previous `avg_comm_delay_ms` to make the unit/scope unambiguous. |
| `allocation_rate` | Allocation Rate | Allocation Rate | P3 §6.3: `#completed_pairs / min(#providers_in_network, #consumers_with_demand)`. Consumers = distinct CHARGE_RQST senders. Providers = non-leader vehicles whose initial energy passes the `pick_a_donor` feasibility gate (`energy ≥ min_energy + charge_demand`). PA broadcasts do not exist in this protocol, so the provider pool is proxied from vehicle init state. |
| `avg_payoff_cents` | Payoff (eqn 3) | — | `(selling_price - original_price) × energy - time_value × duration`. P3 defaults: 15 / 8 / 10 ¢. |
| `min_consumer_soc` | — | Min SoC of selected CEV | P4 Table 3. `min(final_energy[c]) / battery_capacity` across consumers with completed sessions. `N/A` when no session completed. |
| `arrival_rate` | — | — | Unique to MVCCP — "Battery Threshold Arrival" not reported in P3/P4. |
| `jains_fairness` | — | — | Jain's Fairness Index over provider contributions (`_energy_sent` per provider). Informative only when per-provider contributions vary — requires multiple consumers per platoon or heterogeneous demand. See "Known limitations". |

> `transfer_efficiency` (energy received / energy sent) was previously exported but is **intentionally omitted from the summary CSV**: without any layer-3 transport or packet-loss modelling the ratio is 1.0 by construction (every sent packet is received). The method is still present on `MetricsCollector` for future use; re-add it to `_append_summary` once an efficiency model exists.

Broadcast message types (`CHARGE_RQST`, `CHARGE_RSP`, `STATUS`) are deliberately **omitted** from the per-type PDR table: one broadcast produces N deliveries, so the ratio is not comparable to the literature definition.

### Non-Reproducible Elements

The following aspects of P3/P4 cannot be reproduced in our simulation:

1. **PHY layer**: P3 uses NS-3 with IEEE 802.11p (5 Mbps, 33 dBm, 250 m range). Our simulation abstracts the PHY — messages are delivered in-memory with no channel model. Unicast PDR is therefore always ≈ 1.0.
2. **Mobility model**: P3 simulates a 10 km, 3-lane highway. We use TAPASCologne urban traffic.
3. **P4's simulation data**: Tang 2024 states "The data that has been used is confidential" — their NS-2 grid scenario cannot be exactly reproduced.
4. **NS-2/NS-3 internals**: Queuing, medium access (CSMA/CA), and propagation delays are not modelled in our SUMO + TraCI stack.

### Known Limitations

- **Unicast PDR ≈ 100 %**: Our abstracted network delivers every unicast message. P3's lower PDR reflects PHY losses from IEEE 802.11p that we deliberately omit. Any unicast value < 1.0 in our runs indicates a bookkeeping bug (a missing `record_send_attempt` call), not a channel loss.
- **Broadcasts are excluded from PDR**: Per the metric mapping table above, `CHARGE_RQST` / `CHARGE_RSP` / `STATUS` have one send and N deliveries by construction, which is not comparable to the literature definition. To recover a broadcast PDR in the future, divide deliveries by (sends × intended_recipients).
- **E2E delay resolution**: With `step_length = 1.0 s` in `SimConfig`, timestamps live on 1-second boundaries in SUMO sim-time. `avg_rqst_to_packet_gap_s` is therefore quantised to whole seconds. Sub-second resolution would require either `step_length < 1.0` or recording wall-clock timestamps inside `MetricsCollector` and dividing by `time_scale`.
- **E2E delay scope**: Our gap is simulated protocol-processing time only (in-memory message passing, ENERGY_PACKET pacing). P3's delay includes MAC-layer contention, propagation, and queuing from NS-3. Our numbers measure a different thing — not comparable, only directionally useful.
- **`transfer_efficiency` omitted**: See the note above the limitations list. Without layer-3 packet-loss modelling the ratio is tautologically 1.0, so the column is not written to `summary.csv`. Re-enable once a loss/efficiency model is added.
- **Allocation-rate provider pool is a proxy**: Since MVCCP does not broadcast PA (Provider Announcement) messages the way P3 does, we cannot enumerate providers by message traffic. Instead we count non-leader vehicles whose initial energy passes the `pick_a_donor` feasibility gate (`energy ≥ min_energy + charge_demand`) from the vehicle init snapshot. This tracks the donor scorer's own eligibility definition.
- **Jain's FI needs variation to be informative**: The index equals 1.0 trivially whenever every provider contributes the same amount — which happens when demand is uniform and each platoon produces exactly one session. The harness mitigates this by firing one CHARGE_RQST per *energy-short* non-leader (threshold: `min_energy + demand`), so a donor picked by multiple consumers in the same platoon accumulates more `_energy_sent` than one picked by few, producing non-trivial variance. For further variance, draw `charge_demand_kwh` from a distribution per consumer.
- **Multi-round vs. single-trigger charging**: `_trigger_charges()` fires once per simulation, but emits one CHARGE_RQST per energy-short member per platoon (not one total). Each request is resolved independently by the leader running `pick_a_donor`. P3 simulates continuous rounds; our harness approximates one "round" with a realistic fan-out of consumers.
- **N/A values**: `min_consumer_soc`, `allocation_rate`, and `avg_payoff_cents` write `N/A` to the CSV when there is no data (zero charge sessions or zero demand pool). A literal `0.0` in those columns is a real zero, not "missing".

### Disclaimer

This is a **same-operating-point comparison**, not a superiority claim. MVCCP is evaluated under P3-aligned parameters (vehicle count, provider/consumer mix, energy demand) on a different topology (urban Cologne vs. highway). Results are reported alongside P3/P4 figures for directional comparison only. Any performance differences attributable to the topology change are noted explicitly.