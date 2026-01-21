# CLAUDE.md — Authoritative Project Context for AI Assistants

## Purpose

This file provides **mandatory, authoritative context** for any AI assistant interacting with this repository. It exists to prevent incorrect architectural assumptions, unsafe protocol behavior, and simulation-time bugs.

The system currently executes **single-threaded inside ns-3**, but is intentionally written to be **thread-safe by construction** so it can later migrate to real embedded or multi-core environments without redesign.

If anything is unclear: **stop and ask questions before writing code**.

---

## Project Overview

This project implements **MVCCP (Multi-hop VANET Charging Coordination Protocol)** — a decentralized protocol for **autonomous electric vehicles (AEVs)** operating in a **vehicular ad-hoc network (VANET)**.

Capabilities:

* Neighbor discovery and local topology maintenance
* Provider advertisement (mobile EVs and fixed RREHs)
* Charging session negotiation (consumer ↔ provider)
* Platoon-based wireless energy transfer while driving

System properties:

* Decentralized (no global controller)
* Event-driven (ns-3 discrete-event scheduler)
* Message-driven (explicit message types only)

---

## Execution Model (Authoritative)

* Language: **Python 3.x**
* Runtime: **Single-threaded, event-driven**
* Scheduler: **ns-3 simulation scheduler**

Important implications:

* No Python threads are spawned by the Node
* No async / await
* No thread pools
* No background timers

All protocol logic runs inside **ns-3’s single simulation thread** via deterministic callbacks.

---

## SUMO ↔ ns-3 Co-Simulation Model (Target, Authoritative)

This repository is intended to support **SUMO mobility + ns-3 PHY/MAC** co-simulation, with the MVCCP protocol running in Python.

### Orchestrator and stepping

- **Orchestrator location**: runs in the **ns-3 Python main process** (same process that creates ns-3 objects and the MVCCP application adapter).
- **SUMO step size**: **Δt = 0.5 seconds** per SUMO step.
- **ns-3 sub-step events**: ns-3 runs **sub-step packet events** inside each SUMO interval \([t, t+Δt)\).
  - Packets can arrive at arbitrary `eventTime` values inside the window.
  - These packet events must be processed using their true ns-3 event time (not “rounded” to the SUMO boundary).

### Receive metadata constraint (important)

In the target integration, the Python protocol receive path should assume it receives:
- **raw bytes only** (no PHY/MAC metadata such as previous-hop MAC, RSSI/SNR).

This constraint directly requires an explicit forwarding identity contract (see below).

---

## Time Model (Simulation-Time Only)

**Wall-clock time must never be used for protocol logic.**

Time source:

* ns-3 provides `timestamp: float` (simulation seconds)

Rules:

* `context.update_time(timestamp)` is the **only** way to advance time
* `context.current_time` is the single source of truth

Forbidden:

* `time.sleep()`
* `threading.Timer`
* `time.time()` / `datetime.now()` for protocol decisions

Periodic behavior is implemented as:

```python
if timestamp - self.last_event_time >= INTERVAL:
    ...
```

---

## Tick vs. Receive Ordering (Policy B — Explicit)

This project uses **Policy B**:

* **Both `tick(timestamp)` and `ReceivePacket()` are authoritative events**
* **Both must update simulation time before executing logic**

Required invariant:

* `context.update_time(timestamp)` **must be called**:

  * at the start of `tick(timestamp)`
  * at the start of `ReceivePacket()` (using the ns-3 event time)

Consequences:

* Handlers must be correct regardless of whether a packet or a tick is processed first at the same simulation timestamp
* No handler may assume that `tick()` has already run for the current time

This prevents stale-time bugs and role/timer inconsistencies.

---

## Known Time Violations To Remove (Critical Checklist)

This section is intentionally **explicit and elaborate** because time-model violations are easy to miss and will create silent simulation bugs (stale timers, inconsistent state transitions, non-determinism).

### The rule (repeat)

- **Protocol logic must use simulation time only.**
- **`MVCCPContext.update_time(timestamp)` is the only authoritative way to advance time.**
- Any usage of `time.time()` / wall-clock time inside protocol decisions is a **bug** (even if “it usually gets overwritten later”).

### Why this matters in SUMO(Δt=0.5s) + ns-3(sub-step) co-sim

- ns-3 delivers packets at sub-step times `eventTime` within \([t, t+Δt)\).
- If any component reads wall-clock time instead of `eventTime`, you will see:
  - timeouts firing “randomly”
  - dedup caches expiring incorrectly
  - inconsistent behavior across runs
  - incorrect ordering when multiple events happen at the same simulation timestamp

### Concrete violations currently present in the repo

These must be removed as part of **Tier 0 / O2 (Simulation-Time Compliance Sweep)** from `Required_Changes.md`.

#### 1) `src/protocol/context.py` — initializes simulation time from wall clock

- **File**: `src/protocol/context.py`
- **Current behavior**: `MVCCPContext.__init__` sets `self.current_time = time.time()`
- **Why it’s dangerous**:
  - Unit tests and integration harnesses can execute handler logic before the ns-3 adapter calls `update_time()`
  - Any early timers/seq numbers derived from this will be non-deterministic
  - It violates the simulation-time-only rule even if later overwritten
- **Required fix**:
  - Initialize `current_time` to a deterministic value (commonly `0.0`), or use `None` but then enforce strict checks
  - Ensure every entry point calls `update_time(timestamp)` before logic (Policy B already requires this)

#### 2) `src/protocol/layer_a/neighbor_table.py` — falls back to wall clock when time is missing

- **File**: `src/protocol/layer_a/neighbor_table.py`
- **Current behavior**: when `context.current_time` is `None`, it falls back to `time.time()` in update/prune paths
- **Why it’s dangerous**:
  - This injects wall-clock time into neighbor liveness and pruning
  - It can change MPR selection and PA dissemination behavior across runs
  - It breaks determinism and makes debugging almost impossible
- **Required fix**:
  - Remove the wall-clock fallback entirely
  - Replace with one of:
    - strict failure (raise) if `context.current_time` is not set (preferred while developing)
    - deterministic safe default (`0.0`) + warning, but never wall-clock

#### 3) `src/core/node.py` — exposes wall-clock `current_time` property

- **File**: `src/core/node.py`
- **Current behavior**: `Node.current_time` property returns `time.time()`
- **Why it’s dangerous**:
  - It’s a trapdoor: future code can accidentally read wall-clock time without noticing
  - It undermines “single source of truth” for simulation time
  - It makes it unclear whether “time” is coming from Context, ns-3, or the OS
- **Required fix**:
  - Remove the property entirely, or make it return a simulation time provided by Context/orchestrator
  - Any code needing time must use `context.current_time`, not `node.current_time`

### Time compliance sanity checks (must pass)

- Search for `time.time(` in `src/` should return **no usages in protocol logic** after O2 is complete.
- For ns-3 integration, confirm `Simulation/ns3_adapter.py` continues to call:
  - `context.update_time(timestamp)` at the start of `tick(timestamp)`
  - `context.update_time(eventTime)` at the start of packet receive handling

---

## Protocol Architecture (Strict Layering)

```
Event-driven Architecture: includes 4 layers:
Layer D — Platoon Coordination
Layer C — Charging Coordination
Layer B — Provider Announcements (PA)
Layer A — Neighbor Discovery
```

Cross-layer access is **forbidden** except through the shared Context interface.

---

## Layer Responsibilities

### Layer A — Neighbor Discovery

* HELLO messaging
* Neighbor liveness tracking
* 1-hop / 2-hop topology
* QoS metrics

Owns:

* NeighborTable

### Layer B — Provider Announcements

* PA dissemination
* TTL-controlled multi-hop forwarding
* ProviderTable maintenance
* Duplicate suppression by `(originator_id, seq_num)` (see forwarding identity contract below)

### Layer C — Charging Coordination

* Consumer ↔ Provider negotiation
* Charging session lifecycle
* Admission and scheduling logic

### Layer D — Platoon Coordination

* Platoon formation and maintenance
* In-motion charging coordination
* Platoon role management
* **Edge-based formation optimization** (see below)

---

## Edge-Based Platoon Optimization (Authoritative)

This system uses an **edge graph model** for intra-platoon energy transfer optimization and **virtual edges** for inter-platoon discovery.

### Intra-Platoon Edges (Energy Transfer)

Each platoon maintains an **edge graph** where:
- **Nodes** = platoon members (including head)
- **Edges** = potential wireless charging links between any two members
- **Edge weight** = transfer cost based on distance, efficiency, and time

**Files:**
- `src/core/edge.py` — Edge class with inverse-square efficiency model
- `src/core/platoon.py` — Edge graph, Dijkstra, and formation optimization

#### Efficiency Model (Inverse-Square)

```python
efficiency = 1 / (1 + EDGE_EFFICIENCY_SCALE * distance²)
```

- At distance=0: 100% efficiency
- At distance=3m (scale=0.1): ~53% efficiency
- At distance=10m (scale=0.1): ~9% efficiency

Configurable in `ProtocolConfig`:
- `EDGE_EFFICIENCY_SCALE = 0.1`
- `EDGE_MAX_RANGE_M = 10.0`
- `EDGE_MIN_EFFICIENCY = 0.1` (below this, edge unusable)

#### Dijkstra Energy Path Finding

`Platoon.dijkstra_energy_paths()` finds optimal paths from energy-surplus to energy-deficit nodes.

Edge cost = `w1*distance + w2*(1-efficiency) + w3*transfer_time`

Used to determine:
- Which member charges which
- Multi-hop relay paths (A→B→C) when direct transfer is inefficient

#### Formation Optimization

`Platoon.compute_optimal_formation(timestamp)` calculates target 2D positions for each member to maximize energy transfer efficiency.

Constraints:
- Minimum distance between vehicles (safety)
- Maximum lateral offset (lane width)
- Maximum longitudinal distance from head

Formation data is serialized via `TLVType.FORMATION_POSITIONS` in `PLATOON_BEACON`.

### Inter-Platoon Discovery (Virtual Edges)

Enables consumers to discover and compare multiple platoons.

**Files:**
- `src/protocol/layer_c/platoon_table.py` — PlatoonTable with scoring
- `src/protocol/layer_c/platoon_head_handler.py` — PLATOON_ANNOUNCE broadcast

#### PLATOON_ANNOUNCE Message

Broadcast by Platoon Heads at `PLATOON_ANNOUNCE_INTERVAL` (5s):
- platoon_id, head_id, position
- available_slots, surplus_energy
- direction_vector, formation_efficiency

#### PlatoonTable

Consumers maintain a `PlatoonTable` of discovered platoons. Virtual edge scoring:

```python
score = w1*direction_match + w2*(1/distance) + w3*energy_match + efficiency_bonus
```

Configurable weights in `ProtocolConfig`:
- `PLATOON_SCORE_DIRECTION = 0.4`
- `PLATOON_SCORE_DISTANCE = 0.3`
- `PLATOON_SCORE_ENERGY = 0.3`

### Invariants

1. **Edge graph is built on platoon creation** via `initialize_2d_positions()`
2. **Edges are updated when positions change** via `update_edge_distances()`
3. **PlatoonTable prunes stale entries** after `PLATOON_ENTRY_TIMEOUT` (15s)
4. **Formation is recomputed periodically** at `FORMATION_UPDATE_INTERVAL` (2s)

### Forbidden Patterns

- Do NOT create edges outside of `Platoon.build_edge_graph()`
- Do NOT use Euclidean distance for intra-platoon; use edge graph
- Do NOT modify `PlatoonTable` without RWLock
- Do NOT assume formation positions are immediately applied (they are targets)

---

## Message Definitions (Hard Rule)

**All message types must be defined in exactly one file:**

```
src/messages/messages.py
```

Rules:

* No ad-hoc message dicts or tuples
* No inline message classes in handlers
* Every message must define:

  * explicit message type ID
  * `serialize()`
  * `deserialize()`

---

## Forwarding Identity Contract (Authoritative — Option A)

Because the Python receive path is expected to have **raw bytes only** (no PHY/MAC metadata), **multi-hop forwarding must carry previous-hop identity inside the message**.

### Contract

- **Header `sender_id` MUST be the ORIGINATOR ID**
  - Identifies the node that originally created the message
  - Must remain unchanged across multi-hop forwarding
- **A required TLV MUST carry previous-hop identity**
  - TLV name/type: **`PREVIOUS_HOP`**
  - Meaning: the immediate transmitter for *this hop*
  - Forwarders MUST overwrite `PREVIOUS_HOP` with their own node ID before re-broadcasting

### Deduplication key

- Duplicate suppression MUST be performed on **`(originator_id, seq_num)`**
- Do NOT use `(previous_hop, seq_num)` because `previous_hop` changes at each hop and will break dedup

### Layer B forwarding implication

When deciding whether to forward a PA:
- “previous hop” identity comes from **`PREVIOUS_HOP`**
- Do NOT assume header `sender_id` is the previous hop under this contract

---

## Message Transport (ns-3 Integrated)

* Transport uses **ns-3 PacketSocket** (802.11p simulation)
* Messages pass through PHY/MAC and radio propagation
* No in-process queues
* No direct UDP sockets

Ordering guarantees:

* FIFO per sender → receiver
* No global ordering across different senders

---

## State Machines (Explicit)

State machines are implemented as **explicit handler classes**.

| Role         | Handler            | State Enum       |
| ------------ | ------------------ | ---------------- |
| Consumer     | ConsumerHandler    | ConsumerState    |
| Platoon Head | PlatoonHeadHandler | PlatoonHeadState |
| RREH         | RREHHandler        | RREHState        |

Rules:

* `tick(timestamp)` for periodic logic
* `handle_<message>()` per message type
* State transitions via enum assignment only
* State is stored in Context, not globals

Role invariants:

* Exactly one role is active at a time
* Role transitions must be atomic

---

## Thread-Safety Policy (By Design)

Although execution is currently single-threaded, **thread-safety is mandatory**.

### Locking Model

* Use **RWLock** from `src/protocol/locks.py`
* Read-only operations → `ReadLock`
* Mutations → `WriteLock`

### Shared Tables

| Table         | Locking           |
| ------------- | ----------------- |
| NeighborTable | RWLock            |
| ProviderTable | RWLock (required) |

RWLock is **not re-entrant**. Do not acquire the same lock twice in a call chain.

---

## Shared State Rules

* No direct access to internal table fields
* External code must use public methods
* Do not return mutable internal structures

Violations are **logic bugs**, not style issues.

---

## TTL and Flood Control

Provider Announcement TTL:

* Computed centrally (Config / Context)
* Must respect MIN / MAX bounds
* Must not be hardcoded in handlers

TTL modes:

* FIXED
* DENSITY-BASED

---

## Configuration Ownership

All protocol constants belong in:

```
src/protocol/config.py
```

No magic numbers elsewhere.

---

## Do Not Do (Failure Modes)

The following are explicitly forbidden:

* Create new logic and files without checking for a functionally similar entity first.
* Using wall-clock time for protocol logic
* Creating ad-hoc message formats
* Defining messages outside `messages.py`
* Bypassing ns-3 transport
* Assuming global message ordering
* Hardcoding TTL or flooding parameters
* Cross-layer table mutation
* Accessing shared state without locks

---

## Final Rule for AI Assistants

If unsure about:

* Time ordering (tick vs receive)
* Lock ownership or boundaries
* State transitions or invariants
* Layer responsibilities

**STOP and ask before writing code.**

Guessing is unacceptable.
