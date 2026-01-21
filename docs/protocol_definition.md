
# RFC: Multi-hop VANET Charging Coordination Protocol (MVCCP)
(Informational)

## 1. Introduction
The Multi-hop VANET Charging Coordination Protocol (MVCCP) specifies a decentralized communication framework enabling autonomous electric vehicles (AEVs) to discover energy providers, negotiate charging sessions, and coordinate platoon-based wireless energy transfer (WET). MVCCP supports both mobile provider EVs and Roadside Renewable Energy Hubs (RREHs), allowing energy to be sourced sustainably. The protocol ensures robust communication in high-mobility environments using multi-hop Vehicular Ad-hoc Networks (VANETs).

## 2. Scope
MVCCP defines:
- Message formats (HELLO, PA, JOIN_OFFER, JOIN_ACCEPT, ACK, ACKACK, PLATOON_BEACON, PLATOON_STATUS, optional GRID_STATUS)
- Charging coordination behavior and state machines
- Multi-hop propagation using QoS-OLSR MPR forwarding
- Green-aware provider selection via renewable energy metrics
- Security considerations
- Implementation guidance

MVCCP does not define:
- Wireless energy transfer physics
- Pricing or payoff optimization models
- Vehicle battery management algorithms

## 3. Protocol Architecture
MVCCP is structured into four architectural layers:
1. Neighbor Discovery Layer – based on QoS-OLSR extensions.
2. Provider Announcement Layer – multi-hop PA dissemination.
3. Charging Coordination Layer – negotiation and handshake for charging sessions.
4. Platoon Coordination Layer – management of charging platoons.

## 4. Entities
- Consumer (C): EV requiring charge.
- Mobile Provider (MP): EV able to supply energy to others.
- Roadside Renewable Energy Hub (RREH): stationary charging node powered by a renewable microgrid.
- Platoon Head (PH): lead vehicle of a charging platoon.
- MPR Node: Multipoint Relay used for multi-hop forwarding.

Mobile providers may also act as consumers when their battery is low, enabling renewable-powered V2V charging after recharging at RREHs.

## 5. Message Overview

### 5.1 HELLO
Used for neighbor discovery. Contains:
- node identifier
- one-hop neighbor list and link status
- QoS-OSLR metrics (refer to 7.4)
- provider flag and basic energy availability + direction of travel if the node is a provider or RREH

### 5.2 Provider Announcement (PA)
Multi-hop advertisement constructed and forwarded only by MPRs. Each PA entry includes:
- provider_id
- provider_type (0 = MP, 1 = PH, 2 = RREH)
- Current geographic position
- Final geographic destination
- Y Direction
- X Direction
- Number of Cars in plattoon
- Total energy available (Energy of all cars in plattoon - energy needed for all of them to reach the final destination)

PAs are forwarded with a Time-To-Live (TTL) limited to 4 hops.

### 5.3 JOIN_OFFER
Sent by a Consumer to a chosen Provider (MP, PH, or RREH). Fields include:
- consumer_id
- required_energy_kwh
- current position and planned trajectory
- preferred_meeting_point_id (for mobile providers and platoon heads)

### 5.4 JOIN_ACCEPT
Response from a Provider to a Consumer. Includes:
- provider_id
- selected_meeting_point_id (for mobile providers and PHs)
- expected_charging_bandwidth
- expected_duration
- list of EVs in the plattoon: EV_id, EV_energy_needed, EV_energy_available, EV_destination
- platoon topology vector (ordered list of member IDs and their positions relative to the plattoon head)

### 5.5 ACK and ACKACK
ACK is sent by the Consumer upon receiving JOIN_ACCEPT.
ACKACK is sent by the Provider to confirm final commitment.
After ACKACK both sides consider the session booked.

### 5.6 PLATOON_BEACON
Broadcast by a Platoon Head. Contains:
- platoon_id and head_id
- timestamp
- head position and velocity
- available_slots
- platoon topology vector (ordered list of member IDs and their positions relative to the plattoon head)
- approximate route or segment sequence

### 5.7 PLATOON_STATUS
Sent by platoon members to the head. Contains:
- platoon_id
- vehicle_id
- battery_level_percent
- relative_platoon_index
- local estimate of receive_rate

### 5.8 GRID_STATUS (Optional)
Sent by an RREH to nearby vehicles with lower frequency than PA. Contains:
- hub_id
- current and forecasted renewable_fraction
- available_power_kw
- max_simultaneous_sessions
- queue_time_estimate_s
- operational_state (normal, congested, limited, offline)

### 5.9 PLATOON_ANNOUNCE
Broadcast by a Platoon Head for inter-platoon discovery. Enables consumers to discover and compare multiple platoons. Contains:
- platoon_id and head_id
- current position (lat, lon)
- destination (lat, lon)
- available_slots (number of open member positions)
- surplus_energy (total shareable energy in kWh)
- direction_vector (normalized dx, dy heading)
- formation_efficiency (current edge-based formation efficiency, 0.0-1.0)

PLATOON_ANNOUNCE is sent at a configurable interval (default 5 seconds) and allows consumers to evaluate platoons based on route alignment, distance, and available energy before sending JOIN_OFFER.

## 6. Multi-hop Dissemination Process
PA messages are constructed at MPR nodes using provider information collected through HELLO messages. Only MPR nodes are allowed to rebroadcast PA messages. A PA is forwarded while its TTL is greater than zero. Each forwarding MPR decrements the TTL by one. When the TTL reaches zero the PA is no longer forwarded.

All vehicles use received PA messages to populate a local ProviderTable. Each ProviderTable entry contains the most recent information about a provider or RREH, including its type, price, renewable_fraction and estimated distance or detour. Stale entries are removed after their availability_time_s expires.

### 6.1 Forwarding Identity Contract (Option A — REQUIRED for bytes-only receive)

In the target SUMO + ns-3 integration, the protocol receive path should assume it receives **raw bytes only** (no PHY/MAC metadata such as previous-hop MAC address, RSSI/SNR). Therefore, multi-hop forwarding must carry previous-hop identity explicitly inside the message.

**Contract:**

- **`sender_id` in the common header is the ORIGINATOR ID**
  - The node that originally created the message.
  - It does **not** change when a message is forwarded.
- **A required TLV carries the immediate previous-hop identity**
  - **TLV: `PREVIOUS_HOP`** (6 bytes)
  - Meaning: the immediate transmitter of the packet for *this hop*.
  - Each forwarder must overwrite `PREVIOUS_HOP` with its own node ID before re-broadcasting.

**Duplicate suppression (deduplication):**

- Dedup key MUST be **`(originator_id, seq_num)`**, i.e. **`(sender_id, sequence_number)`** under this contract.
- Dedup MUST NOT use `(previous_hop, seq_num)` because `previous_hop` changes at each hop and would break suppression.

**MPR forwarding implication:**

- Forwarding/MPR decisions that depend on the “previous hop” must use **`PREVIOUS_HOP`**, not the header `sender_id`.

## 7. MPR Selection and QoS-OLSR Integration

### 7.1 Overview
Multipoint Relays (MPRs) are a subset of vehicles selected dynamically to forward broadcast control messages. MVCCP uses QoS-OLSR to select MPRs. MPRs provide scalable and reliable multi-hop dissemination of PAs without requiring every vehicle to rebroadcast them.

### 7.2 Neighbor Discovery and Topology Awareness
Each vehicle periodically broadcasts HELLO messages. From these messages every node learns:
- its one-hop neighbors (set N1)
- which two-hop neighbors are reachable through which N1 neighbors (set N2)

This local two-hop view is the basis for MPR selection.

### 7.3 Classical OLSR MPR Algorithm
The classical algorithm proceeds as follows:

1. Any one-hop neighbor that is the only path to a particular two-hop neighbor is selected as an MPR.
2. Among the remaining one-hop neighbors, the node that covers the largest number of currently uncovered two-hop neighbors is selected as an MPR.
3. Step 2 is repeated until all two-hop neighbors are covered.

This yields a small forwarding set that still guarantees reachability of all two-hop neighbors.

### 7.4 QoS-Based Extension in MVCCP
MVCCP adopts QoS-OLSR. During MPR selection, candidate neighbors are ranked using multiple QoS metrics, including:
- link reliability or Expected Transmission Count (ETX)
- Transmissiond elay or jitter
- similarity of speed and heading (prefer lower velocity vehicles to act as MPRs)
- lane weight (traffic congestion)
- historical link stability
- N_willingness (willingness to act as MPR)
- Battery level (prefer nodes with higher battery levels to act as MPRs)


When two candidates cover the same number of two-hop neighbors, the candidate with higher QoS ranking is chosen. This improves delivery ratio and stability for PA propagation in high-mobility scenarios.

### 7.5 MPR Responsibilities
MPR nodes in MVCCP:
- collect provider information from HELLO messages
- construct Provider Announcement (PA) messages
- rebroadcast PAs when TTL > 0
- do not modify the logical meaning of PA entries
- do not forward PAs when TTL == 0

Additionally (Option A):
- forwarders MUST update the `PREVIOUS_HOP` TLV to their own node ID when re-broadcasting

### 7.6 Configurable TTL Dissemination

MVCCP supports configurable TTL for PA messages with three modes:

**FIXED Mode (Default):**
Static TTL value (default: 4 hops). Each PA is created with TTL = PA_TTL_DEFAULT. This mode is suitable for uniform network densities.

**DENSITY_BASED Mode:**
TTL adjusts based on local network density using the formula:
```
TTL = max(PA_TTL_MIN, min(PA_TTL_MAX, 8 - log2(neighbor_count)))
```
- High density (many neighbors): Lower TTL to reduce flooding
- Low density (few neighbors): Higher TTL to extend discovery range

**Default Configuration:**
- PA_TTL_DEFAULT = 4 hops
- PA_TTL_MIN = 2 hops (lower bound)
- PA_TTL_MAX = 6 hops (upper bound)
- PA_TTL_ADAPTIVE_PROVIDER_THRESHOLD = 3 providers
- PA_TTL_ADAPTIVE_FLOOD_THRESHOLD = 20 PA/second

Each forwarding MPR decrements TTL by one. When TTL reaches zero the PA is not forwarded further. This offers a bounded discovery radius and prevents unnecessary city-wide flooding while adapting to local network conditions.

### 7.7 Multi-hop Continuity Guarantees
Although OLSR and QoS-OLSR only use one-hop and two-hop knowledge during MPR selection, MVCCP still achieves communication beyond two hops by chaining multiple local forwarding regions. At each hop, new MPRs are selected using their own local N1 and N2 sets. As long as the physical network is connected, there will be at least one MPR at each forwarding layer until the TTL expires or the network boundary is reached. If a node has no further neighbors, propagation stops naturally at that edge.

## 8. State Machines

### 8.1 Consumer State Machine
1. DISCOVER: listen for PAs and optional GRID_STATUS.
2. EVALUATE: build ProviderTable and compute preferences (cost, renewable_fraction, detour, deadline).
3. SEND_OFFER: send JOIN_OFFER to the selected provider.
4. WAIT_ACCEPT: start timer and wait for JOIN_ACCEPT.
5. ACK: upon ACCEPT, send ACK.
6. WAIT_ACKACK: wait for final ACKACK.
7. ALLOCATED: reservation is confirmed.
8. TRAVEL: move toward meeting point or RREH location.
9. CHARGE: perform the charging session.
10. LEAVE: session ends; update internal energy state.

### 8.2 Mobile Provider State Machine
Mobile Providers operate using dynamic role switching between CONSUMER and PLATOON_HEAD roles based on shareable energy and willingness thresholds. When a vehicle has sufficient energy to share:
1. RoleManager evaluates shareable_energy and willingness.
2. If thresholds are met and not in active session, transition to PLATOON_HEAD role.
3. If energy drops below threshold or session completes, transition back to CONSUMER role.

This dynamic approach allows vehicles to seamlessly switch between consuming and providing energy.

### 8.3 RREH State Machine
RREHs are stationary charging stations with predetermined roles:
1. GRID_ANNOUNCE: broadcast GRID_STATUS periodically with capacity info.
2. WAIT_OFFERS: listen for JOIN_OFFER messages during an offer window.
3. EVALUATE_QUEUE: select next consumer from queue (FIFO policy).
4. SEND_ACCEPT: send JOIN_ACCEPT to chosen consumer.
5. WAIT_ACK: wait for ACK from consumer (with timeout).
6. SEND_ACKACK: confirm final commitment.
7. CHARGE_SESSION: manage active charging sessions.
8. IDLE: no active sessions, waiting for offers.

### 8.4 Platoon Head State Machine
1. BEACON: periodically send PLATOON_BEACON and PLATOON_ANNOUNCE.
2. WAIT_OFFERS: listen for JOIN_OFFER messages during offer window.
3. EVALUATE_OFFERS: evaluate incoming join requests based on route alignment and capacity.
4. SEND_ACCEPT: send JOIN_ACCEPT to accepted members with position assignment.
5. WAIT_ACK: wait for ACK from each consumer.
6. SEND_ACKACK: confirm final commitment.
7. COORDINATE: maintain platoon formation using PLATOON_STATUS updates and compute optimal positions.
8. HANDOFF: transfer PH role to best candidate when energy drops below threshold.

## 9. Sequence Flows

### 9.1 Direct V2V Charging Sequence
HELLO -> PA -> Consumer EVALUATE -> JOIN_OFFER -> JOIN_ACCEPT -> ACK -> ACKACK -> travel to meeting point -> CHARGE.

### 9.2 Platoon-Based Charging Sequence
PLATOON_BEACON -> JOIN_OFFER(join_mode = platoon) -> JOIN_ACCEPT(platoon_position) -> ACK -> ACKACK -> join platoon -> CHARGE while platoon moves.

### 9.3 RREH Charging Sequence
HELLO -> PA(provider_type = RREH) plus optional GRID_STATUS ->
Consumer selects RREH -> JOIN_OFFER -> JOIN_ACCEPT -> ACK -> ACKACK ->
travel to RREH -> CHARGE at fixed location.

## 10. Message Formats (Abstract)

### 10.1 Common Header
- msg_type: 16-bit unsigned integer
- ttl: 8-bit unsigned integer
- sequence_number: 32-bit unsigned integer
- sender_id: unique identifier (48 bits) (**originator ID under Option A; does not change across hops**)
- payload_length: 16-bit unsigned integer

### 10.2 TLV Payload Encoding
All message bodies are encoded as ordered sequences of TLV fields:
- Type: 1 byte
- Length: 1 byte
- Value: Length bytes

Concrete TLV type assignments are defined in Appendix A.

## 11. Error Handling
- If JOIN_ACCEPT is not received before timeout, the consumer removes the provider from its local ProviderTable and re-enters EVALUATE.
- If ACK is not received, the provider discards the pending allocation and may re-announce capacity in future PA rounds.
- If PLATOON_BEACON is not heard for several intervals, platoon members fall back to safe-mode spacing and may leave the platoon.
- If an RREH transitions to congested or offline, new PA or GRID_STATUS messages are broadcast to update queue_time_estimate_s and operational_state.

## 12. Security Considerations
MVCCP assumes an underlying V2X security framework such as IEEE 1609.2. Messages should be:
- signed to provide integrity and authenticity
- time-stamped to prevent replay attacks
- associated with short-lived pseudonyms to preserve privacy

Nodes must validate signatures before acting on PA, JOIN_ACCEPT, PLATOON_BEACON, and GRID_STATUS messages.

## 13. Implementation Recommendations
- Use ns-3 together with SUMO or Veins for realistic simulation of VANET mobility and 802.11p links.
- Use compact encodings such as TLV or CBOR for on-road deployment.
- Use JSON encodings only for logging and debugging.
- Implement node logic using a modular architecture so that optimization policies (e.g., green-first or cheapest-first) can be swapped without changing packet formats.

