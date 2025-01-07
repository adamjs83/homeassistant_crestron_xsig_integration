"""Support for Crestron devices."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
    ATTR_NAME,
    ATTR_ENTITY_ID,
    ATTR_DOMAIN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import (
    async_get,
    async_entries_for_config_entry,
)
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DEVICE_TYPE_BUTTON_EVENT,
    EVENT_BUTTON_PRESS,
    EVENT_TYPES,
    CONF_DEVICE_ID,
    CONF_JOIN,
    CONF_DEVICE_TYPE,
    CONF_ENTITIES,
    CONF_DEVICES,
    CONF_REMOVED_ENTITIES,
)
from .server import CrestronServer

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.config"

PLATFORMS = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.COVER,
    Platform.EVENT,
    Platform.BUTTON,
    Platform.SELECT,
]

async def async_setup(hass: HomeAssistant, config) -> bool:
    """Set up the Crestron integration."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
        
    # Initialize storage
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    hass.data[DOMAIN]["store"] = store

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crestron from a config entry."""
    try:
        # Initialize domain data if not already done
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        
        # Load stored config
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        hass.data[DOMAIN]["store"] = store
        stored_config = await store.async_load() or {}
        
        # Restore stored options if available
        if entry.entry_id in stored_config:
            options = dict(stored_config[entry.entry_id])
            hass.config_entries.async_update_entry(entry, options=options)
        
        # Set up server
        await _async_setup_server(hass, entry)
        
        # Store device map
        hass.data[DOMAIN]["devices_map"] = {}
        
        # Register device cleanup
        async def cleanup_devices(event=None):
            """Clean up devices."""
            device_registry = dr.async_get(hass)
            entity_registry = er.async_get(hass)
            
            # Remove empty devices
            for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
                device_entities = er.async_entries_for_device(
                    entity_registry,
                    device.id
                )
                if not device_entities:
                    device_registry.async_remove_device(device.id)
        
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cleanup_devices)
        )
        
        # Forward entry setup to platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        # Register options update listener
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
        
        return True
        
    except Exception as err:
        _LOGGER.error("Error setting up Crestron integration: %s", err)
        raise ConfigEntryNotReady from err

async def _async_setup_server(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up the Crestron server."""
    if CONF_PORT not in entry.data:
        raise HomeAssistantError("Port configuration missing")

    port = entry.data[CONF_PORT]
    server = CrestronServer(hass, "0.0.0.0", port)
    server.set_entry_id(entry.entry_id)

    if not await server.start():
        raise HomeAssistantError("Failed to start Crestron server")

    hass.data[DOMAIN]["server"] = server

    async def cleanup(event=None) -> None:
        """Clean up resources."""
        try:
            _LOGGER.debug("Cleaning up server resources")
            await asyncio.wait_for(server.stop(), timeout=10.0)
        except (asyncio.TimeoutError, Exception) as err:
            _LOGGER.error("Error during cleanup: %s", err)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cleanup)
    )

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        # Get registries
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        
        # Track removed entities
        removed_entities = set()
        
        # Get configured devices
        configured_devices = set()
        for entity_config in entry.options.get("entities", []):
            if "device_id" in entity_config:
                configured_devices.add(entity_config["device_id"])
        
        # Unload platforms one by one
        unload_ok = True
        for platform in PLATFORMS:
            try:
                platform_unload = await hass.config_entries.async_unload_platforms(entry, [platform])
                if not platform_unload:
                    _LOGGER.error("Failed to unload platform %s", platform)
                    unload_ok = False
            except ValueError:
                # Platform was not loaded, skip it
                _LOGGER.debug("Platform %s was not loaded, skipping unload", platform)
                continue
            except Exception as err:
                _LOGGER.error("Error unloading platform %s: %s", platform, err)
                unload_ok = False
        
        # Clean up orphaned devices
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
            try:
                device_entities = er.async_entries_for_device(
                    entity_registry,
                    device.id
                )
                
                # Remove device if it has no entities or is not in configured devices
                if (
                    not device_entities or
                    not any(
                        ident[1] in configured_devices
                        for ident in device.identifiers
                        if ident[0] == DOMAIN
                    )
                ):
                    _LOGGER.debug(
                        "Removing device %s (no entities or not configured)",
                        device.id
                    )
                    device_registry.async_remove_device(device.id)
                    
            except Exception as device_err:
                _LOGGER.error("Error processing device %s: %s", device.id, device_err)
        
        # Store removed entities in config
        if removed_entities:
            try:
                store = hass.data[DOMAIN]["store"]
                stored_config = await store.async_load() or {}
                entry_config = stored_config.setdefault(entry.entry_id, {})
                entry_config[CONF_REMOVED_ENTITIES] = list(removed_entities)
                await store.async_save(stored_config)
            except Exception as store_err:
                _LOGGER.error("Error storing removed entities: %s", store_err)
        
        if unload_ok:
            # Clean up server
            server = hass.data[DOMAIN].get("server")
            if server:
                await server.stop()
            
            # Clean up domain data
            if entry.entry_id in hass.data[DOMAIN]:
                del hass.data[DOMAIN][entry.entry_id]
            
        return unload_ok
        
    except Exception as err:
        _LOGGER.error("Error unloading entry: %s", err)
        return False

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    try:
        # Get entity registry
        ent_reg = async_get(hass)
        entity_entries = async_entries_for_config_entry(ent_reg, entry.entry_id)
        
        # Track configured unique IDs
        configured_unique_ids = set()
        
        # Process entities
        for entity_config in entry.options.get("entities", []):
            try:
                name = entity_config.get("name", "")
                device_type = entity_config.get("device_type", "")
                device_id = entity_config.get("device_id")
                
                # Skip entities with missing required config
                if not name or not device_type:
                    continue
                
                # Handle different entity types
                if device_type == "shade":
                    # For shades, use position join for unique ID
                    join = entity_config.get("position_join")
                    if join is not None:
                        unique_id = f"{entry.entry_id}_shade_{join}"
                        configured_unique_ids.add(unique_id)
                
                elif device_type == "thermostat":
                    # For thermostats, use current temp join for unique ID
                    join = entity_config.get("current_temp_join")
                    if join is not None:
                        unique_id = f"{entry.entry_id}_thermostat_{join}"
                        configured_unique_ids.add(unique_id)
                
                elif device_type == "button_event":
                    # For button events, use event format
                    join = entity_config.get("join")
                    if join is not None:
                        unique_id = f"{entry.entry_id}_event_{join}"
                        configured_unique_ids.add(unique_id)
                
                else:
                    # For other entities, use standard join format
                    join = None
                    for join_key in ["join", "brightness_join", "switch_join", "momentary_join"]:
                        if join_key in entity_config:
                            join = entity_config[join_key]
                            break
                    
                    if join is None:
                        _LOGGER.warning(
                            "Skipping entity %s - missing join number",
                            name
                        )
                        continue
                    
                    # Generate unique_id based on join type
                    join_type = "a" if device_type in ["light"] else "d"
                    unique_id = f"{entry.entry_id}_{join_type}{join}"
                    configured_unique_ids.add(unique_id)
                
                # Also track device-based unique IDs
                if device_id:
                    device_unique_id = f"{device_id}_{name}"
                    configured_unique_ids.add(device_unique_id)
                
                _LOGGER.debug(
                    "Tracking entity: name=%s, device_type=%s, join=%s, unique_id=%s",
                    name,
                    device_type,
                    join,
                    unique_id
                )
                
            except Exception as err:
                _LOGGER.error(
                    "Error processing entity config: %s",
                    err,
                    exc_info=True
                )
        
        # Remove unconfigured entities
        for entity_entry in entity_entries:
            if entity_entry.unique_id not in configured_unique_ids:
                _LOGGER.debug(
                    "Removing entity %s (unique_id=%s) - no longer configured",
                    entity_entry.entity_id,
                    entity_entry.unique_id
                )
                ent_reg.async_remove(entity_entry.entity_id)
        
        # Store current config before reloading
        store = hass.data[DOMAIN]["store"]
        stored_config = await store.async_load() or {}
        stored_config[entry.entry_id] = dict(entry.options)
        await store.async_save(stored_config)
        
        # Reload platforms
        await hass.config_entries.async_reload(entry.entry_id)
        
    except Exception as err:
        _LOGGER.error("Error reloading entry: %s", err, exc_info=True)
        raise

async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    try:
        # Get registries
        ent_reg = async_get(hass)
        dev_reg = dr.async_get(hass)
        
        # Remove entities
        entity_entries = async_entries_for_config_entry(ent_reg, entry.entry_id)
        for entity_entry in entity_entries:
            ent_reg.async_remove(entity_entry.entity_id)
            _LOGGER.debug("Removed entity: %s", entity_entry.entity_id)
            
        # Remove devices
        device_entries = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        for device_entry in device_entries:
            dev_reg.async_remove_device(device_entry.id)
            _LOGGER.debug("Removed device: %s", device_entry.id)
            
        # Remove stored config
        store = hass.data[DOMAIN]["store"]
        stored_config = await store.async_load() or {}
        stored_config.pop(entry.entry_id, None)
        await store.async_save(stored_config)
            
    except Exception as err:
        _LOGGER.error("Error removing entry: %s", err)