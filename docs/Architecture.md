# MVCCP Architecture (Target: SUMO Δt=0.5s + ns-3 PHY/MAC sub-step events)

This document describes the **target architecture** for MVCCP running in a SUMO + ns-3 co-simulation:

- **SUMO** advances at **Δt = 0.5s** per step (controlled by an orchestrator).
- **ns-3** runs **sub-step events** (packets/PHY/MAC) inside each \([t, t+Δt)\) window.
- **Protocol time is simulation-time only**: all protocol logic uses `MVCCPContext.current_time`, advanced only via `context.update_time(timestamp)`.
- **Forwarding identity (Option A)**: `MessageHeader.sender_id` is the **originator ID**; forwarding logic uses a **required** TLV `PREVIOUS_HOP` updated by forwarders.

---

## Co-simulation control plane (target)

```mermaid
flowchart TB
  subgraph CoSimTarget["CoSimTarget(Δt=0.5s_SUMO,substep_ns3)"]
    Orchestrator["CoSimOrchestrator(planned_new_module)"]
    SUMO["SUMO"]
    TraCI["TraCI_API"]
    NS3["ns-3(Simulator+PHY/MAC+802.11p)"]
    MVCCPApp["MVCCPApplication(Simulation/ns3_adapter.py)"]
  end

  %% SUMO stepping controlled by orchestrator (planned)
  Orchestrator -->|"simulationStep(tNext)"| SUMO
  SUMO -->|"vehicle_state"| TraCI
  TraCI -->|"state_updates"| Orchestrator

  %% ns-3 runs sub-step events inside window
  Orchestrator -->|"RunUntil(tNext)"| NS3
  NS3 -->|"ReceivePacket(bytes,eventTime)"| MVCCPApp
  MVCCPApp -->|"SendPacket(bytes)"| NS3

  %% Periodic protocol tick at SUMO boundary (existing MVCCPApplication.tick)
  Orchestrator -->|"tick(tNext)"| MVCCPApp

  %% Mobility/energy sync into MVCCPApplication/NodeProxy (planned call site)
  Orchestrator -->|"applyMobilityAndEnergyUpdates(tNext)"| MVCCPApp
```

---

## MVCCP internal architecture (target)

```mermaid
flowchart TB
  subgraph MVCCP["MVCCP_Python_Protocol(target)"]
    Context["MVCCPContext(sim_time_only)"]
    Messages["src/messages/messages.py"]
    Config["src/protocol/config.py(ProtocolConfig)"]
    Locks["src/protocol/locks.py(RWLock)"]

    subgraph LayerA["LayerA_NeighborDiscovery"]
      L1["NeighborDiscoveryHandler"]
      NT["NeighborTable(RWLock)"]
      OLSR["QoS_OLSR"]
    end

    subgraph LayerB["LayerB_ProviderAnnouncements"]
      L2["ProviderAnnouncementHandler"]
      PT["ProviderTable(RWLock_planned)"]
      Dedup["DedupCache((originator_id,seq_num))"]
      Forwarding["MPR_forwarding_uses_TLV_PREVIOUS_HOP(planned)"]
    end

    subgraph LayerC["LayerC_ChargingCoordination"]
      RM["RoleManager"]
      CH["ConsumerHandler"]
      PH["PlatoonHeadHandler"]
      RH["RREHHandler"]
      EC["EfficiencyCalculator"]
    end

    subgraph LayerD["LayerD_PlatoonCoordination"]
      L4["PlatoonCoordinationHandler"]
    end

    subgraph Core["Core"]
      Node["Node_or_NodeProxy"]
      Platoon["Platoon(invariants_planned)"]
    end
  end

  %% Context wiring
  Context --> Config
  Context --> Node
  Context --> Platoon
  Context --> NT
  Context --> PT

  %% Layer internals
  L1 --> NT
  L1 --> OLSR

  L2 --> PT
  L2 --> Dedup
  L2 --> Forwarding

  CH --> EC
  PH --> Platoon
  L4 --> Platoon

  %% Message ownership (messages.py is the only definition point)
  Messages --> L1
  Messages --> L2
  Messages --> CH
  Messages --> PH
  Messages --> RH
  Messages --> L4
```

---

## Event ordering (target)

```mermaid
sequenceDiagram
participant Orchestrator as CoSimOrchestrator(planned)
participant NS3 as ns3.Simulator
participant App as MVCCPApplication(ns3_adapter)
participant Ctx as MVCCPContext
participant Msg as messages.py
participant L1 as LayerA
participant L2 as LayerB
participant L3C as LayerC_Consumer
participant L3P as LayerC_PlatoonHead
participant L3R as LayerC_RREH
participant L4 as LayerD

Note over Orchestrator: SUMO steps at Δt=0.5s\nns-3 sub-step events inside [t,tNext)

Orchestrator->>NS3: RunUntil(tNext)
NS3->>App: ReceivePacket(bytes,eventTime)
App->>Ctx: update_time(eventTime)
App->>Msg: decode(bytes)
Msg-->>App: MVCCPMessage(msg_type,TLVs)

alt HELLO
App->>L1: handle_hello(msg)
else PA_or_GRID_STATUS
App->>L2: handle_pa_or_grid_status(msg)
else JOIN_messages
App->>L3C: handle_join_accept_or_ackack(msg)
App->>L3P: handle_join_offer_or_ack(msg)
App->>L3R: handle_join_offer_or_ack(msg)
else PLATOON_messages
App->>L4: handle_beacon_or_status(msg)
end

Orchestrator->>App: tick(tNext)
App->>Ctx: update_time(tNext)
App->>App: role_manager.tick(tNext)
App->>L3C: tick(tNext)
App->>L3P: tick(tNext)
App->>L3R: tick(tNext)
App->>L4: tick(tNext)

Orchestrator->>Orchestrator: simulationStep(tNext)\nvia TraCI (planned)
Orchestrator->>App: applyMobilityAndEnergyUpdates(tNext)\n(planned)
```

---

## Edge-Based Platoon Optimization

### Formation Optimization Flow

```mermaid
sequenceDiagram
participant Members as PlatoonMembers
participant PH as PlatoonHead
participant Platoon as Platoon.py
participant EdgeGraph as EdgeGraph
participant L4 as LayerD_Handler

Note over PH: Periodic tick

Members->>PH: PLATOON_STATUS (battery, position)
PH->>L4: handle_status()
L4->>Platoon: update member info

PH->>Platoon: compute_optimal_formation(timestamp)
Platoon->>EdgeGraph: build_edge_graph()
Note over EdgeGraph: N*(N-1) directed edges

Platoon->>Platoon: dijkstra_energy_paths()
Note over Platoon: Find optimal surplus->deficit paths

Platoon->>Platoon: optimize positions
Platoon-->>PH: target_formation Dict

PH->>PH: _send_beacon()
Note over PH: Include FORMATION_POSITIONS TLV

PH->>Members: PLATOON_BEACON
Members->>L4: handle_beacon()
L4->>L4: extract target position
Note over Members: Adjust toward target in SUMO
```

### Inter-Platoon Discovery Flow

```mermaid
sequenceDiagram
participant PH_A as PlatoonHead_A
participant PH_B as PlatoonHead_B
participant Consumer as Consumer
participant PT as PlatoonTable

Note over PH_A,PH_B: Periodic PLATOON_ANNOUNCE

PH_A->>Consumer: PLATOON_ANNOUNCE (slots=2, energy=30kWh)
Consumer->>PT: update_from_announce()

PH_B->>Consumer: PLATOON_ANNOUNCE (slots=4, energy=50kWh)
Consumer->>PT: update_from_announce()

Consumer->>PT: find_best_platoon(position, direction, energy_needed)
Note over PT: Virtual edge scoring

PT-->>Consumer: PlatoonEntry (PH_B, score=0.85)
Consumer->>PH_B: JOIN_OFFER
```

### Intra-Platoon Edge Graph

```mermaid
graph TB
    subgraph PlatoonEdgeGraph["Platoon Edge Graph"]
        PH["PH (Head)<br/>80 kWh"]
        M1["M1<br/>60 kWh"]
        M2["M2<br/>40 kWh"]
        M3["M3<br/>15 kWh (deficit)"]
    end
    
    PH -->|"d=2m, η=96%"| M1
    PH -->|"d=5m, η=71%"| M2
    PH -->|"d=8m, η=39%"| M3
    M1 -->|"d=3m, η=92%"| M2
    M1 -->|"d=6m, η=58%"| M3
    M2 -->|"d=3m, η=92%"| M3
    
    style M3 fill:#ffcccc
```

**Dijkstra finds:** PH → M1 → M2 → M3 path (cumulative η = 81%) is better than PH → M3 direct (η = 39%)
