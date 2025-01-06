"""Services for the Crestron integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    JOIN_TYPE_OPTIONS,
    MAX_DIGITAL_JOIN,
    MAX_ANALOG_JOIN,
    MAX_SERIAL_JOIN,
)

_LOGGER = logging.getLogger(__name__)

# Service schemas
SET_JOIN_SCHEMA = vol.Schema({
    vol.Required("join_type"): vol.In(JOIN_TYPE_OPTIONS),
    vol.Required("join"): vol.All(
        vol.Coerce(int),
        vol.Range(min=1)
    ),
    vol.Required("value"): vol.Any(
        cv.boolean,       # For digital
        vol.Coerce(int),  # For analog
        cv.string,        # For serial
    ),
})

GET_JOIN_SCHEMA = vol.Schema({
    vol.Required("join_type"): vol.In(JOIN_TYPE_OPTIONS),
    vol.Required("join"): vol.All(
        vol.Coerce(int),
        vol.Range(min=1)
    ),
})

PULSE_JOIN_SCHEMA = vol.Schema({
    vol.Required("join"): vol.All(
        vol.Coerce(int),
        vol.Range(min=1)
    ),
    vol.Optional("duration", default=0.1): vol.All(
        vol.Coerce(float),
        vol.Range(min=0.1, max=5.0)
    ),
})

SYNC_JOINS_SCHEMA = vol.Schema({
    vol.Optional("join_types"): vol.All(
        cv.ensure_list,
        [vol.In(JOIN_TYPE_OPTIONS)]
    ),
})

async def async_get_server(hass: HomeAssistant) -> Any:
    """Get and validate server."""
    if DOMAIN not in hass.data:
        raise HomeAssistantError("Crestron integration not configured")

    server = hass.data[DOMAIN].get("server")
    if not server:
        raise HomeAssistantError("Crestron server not available")

    if not server.is_available():
        raise HomeAssistantError("Crestron system not connected")

    return server

async def async_set_join(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set a join value."""
    try:
        server = await async_get_server(hass)
        join_type = call.data["join_type"]
        join = call.data["join"]
        value = call.data["value"]

        # Validate join number based on type
        if join_type == "d" and join > MAX_DIGITAL_JOIN:
            raise HomeAssistantError(f"Digital join must be <= {MAX_DIGITAL_JOIN}")
        elif join_type == "a" and join > MAX_ANALOG_JOIN:
            raise HomeAssistantError(f"Analog join must be <= {MAX_ANALOG_JOIN}")
        elif join_type == "s" and join > MAX_SERIAL_JOIN:
            raise HomeAssistantError(f"Serial join must be <= {MAX_SERIAL_JOIN}")
        
        if join_type == "d":
            await server.set_digital(join, bool(value))
        elif join_type == "a":
            if not 0 <= int(value) <= 65535:
                raise HomeAssistantError("Analog value must be between 0 and 65535")
            await server.set_analog(join, int(value))
        elif join_type == "s":
            await server.set_serial(join, str(value))

    except Exception as err:
        _LOGGER.error("Error in set_join service: %s", err, exc_info=True)
        raise HomeAssistantError(f"Failed to set join: {err}") from err

async def async_get_join(hass: HomeAssistant, call: ServiceCall) -> Any:
    """Get a join value."""
    try:
        server = await async_get_server(hass)
        join_type = call.data["join_type"]
        join = call.data["join"]

        # Validate join number based on type
        if join_type == "d" and join > MAX_DIGITAL_JOIN:
            raise HomeAssistantError(f"Digital join must be <= {MAX_DIGITAL_JOIN}")
        elif join_type == "a" and join > MAX_ANALOG_JOIN:
            raise HomeAssistantError(f"Analog join must be <= {MAX_ANALOG_JOIN}")
        elif join_type == "s" and join > MAX_SERIAL_JOIN:
            raise HomeAssistantError(f"Serial join must be <= {MAX_SERIAL_JOIN}")
        
        if join_type == "d":
            return server.get_digital(join)
        elif join_type == "a":
            return server.get_analog(join)
        elif join_type == "s":
            return server.get_serial(join)

    except Exception as err:
        _LOGGER.error("Error in get_join service: %s", err, exc_info=True)
        raise HomeAssistantError(f"Failed to get join: {err}") from err

async def async_pulse_join(hass: HomeAssistant, call: ServiceCall) -> None:
    """Pulse a digital join."""
    try:
        server = await async_get_server(hass)
        join = call.data["join"]
        duration = call.data["duration"]

        if join > MAX_DIGITAL_JOIN:
            raise HomeAssistantError(f"Digital join must be <= {MAX_DIGITAL_JOIN}")

        await server.set_digital(join, True)
        await asyncio.sleep(duration)
        await server.set_digital(join, False)

    except Exception as err:
        _LOGGER.error("Error in pulse_join service: %s", err, exc_info=True)
        raise HomeAssistantError(f"Failed to pulse join: {err}") from err

async def async_sync_joins(hass: HomeAssistant, call: ServiceCall) -> None:
    """Request join updates."""
    try:
        server = await async_get_server(hass)
        await server.request_updates()

    except Exception as err:
        _LOGGER.error("Error in sync_joins service: %s", err, exc_info=True)
        raise HomeAssistantError(f"Failed to sync joins: {err}") from err

async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    services = {
        "set_join": (async_set_join, SET_JOIN_SCHEMA),
        "get_join": (async_get_join, GET_JOIN_SCHEMA),
        "pulse_join": (async_pulse_join, PULSE_JOIN_SCHEMA),
        "sync_joins": (async_sync_joins, SYNC_JOINS_SCHEMA),
    }

    for service_name, (handler, schema) in services.items():
        hass.services.async_register(DOMAIN, service_name, handler, schema=schema)

async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister integration services."""
    services = ["set_join", "get_join", "pulse_join", "sync_joins"]
    for service in services:
        hass.services.async_remove(DOMAIN, service)