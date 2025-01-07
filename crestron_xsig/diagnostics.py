"""Diagnostics support for Crestron."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_PORT

from .const import DOMAIN

TO_REDACT = {"identifiers", "ip_address", "mac_address", "host"}

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    server = hass.data[DOMAIN]["server"]
    
    data = {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": {
                CONF_PORT: entry.data[CONF_PORT],
            },
            "options": async_redact_data(entry.options, TO_REDACT),
        },
        "server_status": server.get_status(),
        "entities": {
            platform: [
                {
                    "name": entity.name,
                    "unique_id": entity.unique_id,
                    "available": entity.available,
                    "device_id": getattr(entity, "_device_id", None),
                    "join_type": getattr(entity, "_join_type", None),
                    "join": getattr(entity, "_join", None),
                    "state": entity.state,
                    "attributes": async_redact_data(entity.extra_state_attributes, TO_REDACT),
                }
                for entity in hass.data[DOMAIN].get("entities", {}).get(platform, [])
            ]
            for platform in hass.data[DOMAIN].get("platforms", set())
        },
        "join_states": {
            "digital": server._digital_states,
            "analog": server._analog_states,
            "serial": server._serial_states,
        },
    }

    return data 