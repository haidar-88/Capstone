def PA_message(vehicle):
    return {
        "type": "PA",
        "provider_id": vehicle.node_id,
        "energy_available": vehicle.available_energy() - vehicle.min_energy_kwh,
        "position": vehicle.position()
    }

def JOIN_OFFER(consumer, provider_id, needed_kwh):
    return {
        "type": "JOIN_OFFER",
        "consumer_id": consumer.node_id,
        "provider_id": provider_id,
        "needed_kwh": needed_kwh
    }

def JOIN_ACCEPT(provider, consumer_id, approved_kwh):
    return {
        "type": "JOIN_ACCEPT",
        "provider_id": provider.node_id,
        "consumer_id": consumer_id,
        "approved_kwh": approved_kwh
    }
