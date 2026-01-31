# ==========================================
#     PLATOON PROTOCOL MESSAGE BUILDERS
#     Compatible with YOUR Vehicle class
# ==========================================

# ---------- 5.1 HELLO ----------
def HELLO_message(vehicle):
    return {
        "type": "HELLO",
        "node_id": vehicle.node_id,
        "energy_available": vehicle.available_energy(),
        "position": vehicle.position(),  # (lat, lon)
        "max_transfer_rate_in": vehicle.battery.max_transfer_rate_in,
        "max_transfer_rate_out": vehicle.battery.max_transfer_rate_out
    }


# ---------- 5.2 JOIN_OFFER ----------
def JOIN_OFFER_message(sender_vehicle, target_vehicle_id):
    platoon = sender_vehicle.platoon

    return {
        "type": "JOIN_OFFER",
        "node_id": sender_vehicle.node_id,
        "target_vehicle_id": target_vehicle_id,
        "platoon_id": platoon.platoon_id,
        "platoon_total_energy_available": platoon.total_energy_available(),
        "platoon_total_energy_demand": platoon.total_energy_demand(),
        "platoon_size": len(platoon.nodes),
        "platoon_mobility_pattern": platoon.mobility_pattern()
    }


# ---------- 5.3 JOIN_ACCEPT ----------
def JOIN_ACCEPT_message(vehicle, platoon_id):
    return {
        "type": "JOIN_ACCEPT",
        "node_id": vehicle.node_id,
        "platoon_id": platoon_id,
        "accept": True
    }


# ---------- 5.4 ACK ----------
def ACK_message(platoon_id, vehicle_id):
    return {
        "type": "ACK",
        "platoon_id": platoon_id,
        "vehicle_id": vehicle_id
    }


# ---------- 5.5 CHARGE_RQST ----------
def CHARGE_RQST_message(vehicle, energy_demand_kwh):
    return {
        "type": "CHARGE_RQST",
        "node_id": vehicle.node_id,
        "energy_demand_kwh": energy_demand_kwh
    }


# ---------- 5.6 CHARGE_RSP ----------
def CHARGE_RSP_message(provider_vehicle, energy_amount_kwh, transfer_time_s):
    return {
        "type": "CHARGE_RSP",
        "provider_vehicle_id": provider_vehicle.node_id,
        "energy_amount_kwh": energy_amount_kwh,
        "estimated_transfer_time_s": transfer_time_s
    }


# ---------- 5.7 CHARGE_SYN ----------
def CHARGE_SYN_message(vehicle):
    return {
        "type": "CHARGE_SYN",
        "vehicle_id": vehicle.node_id,
        "flag": "SYN"
    }


# ---------- 5.8 CHARGE_ACK ----------
def CHARGE_ACK_message(vehicle):
    return {
        "type": "CHARGE_ACK",
        "vehicle_id": vehicle.node_id,
        "flag": "ACK"
    }


# ---------- 5.9 CHARGE_FIN ----------
def CHARGE_FIN_message(vehicle):
    return {
        "type": "CHARGE_FIN",
        "vehicle_id": vehicle.node_id,
        "flag": "FIN"
    }


# ---------- 5.10 PLATOON_STATUS ----------
def PLATOON_STATUS_message(vehicle):
    return {
        "type": "PLATOON_STATUS",
        "vehicle_id": vehicle.node_id,
        "battery_level_percent": (vehicle.battery.energy_kwh / vehicle.battery.capacity_kwh) * 100,
        "energy_available_kwh": vehicle.available_energy()
    }


# ---------- 5.11 AIM (Implement the concrete class later) ----------
"""def AIM_message(hub):
    return {
        "type": "AIM",
        "hub_id": hub.node_id,
        "renewable_fraction_current": hub.current_renewable_fraction(),
        "renewable_fraction_forecast": hub.forecasted_renewable_fraction(),
        "available_power_kw": hub.available_power_kw(),
        "max_simultaneous_sessions": hub.max_sessions(),
        "queue_time_estimate_s": hub.queue_time_estimate(),
        "operational_state": hub.operational_state()
    }"""
