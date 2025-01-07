"""Config flow for Crestron integration."""
from __future__ import annotations

import logging
from typing import Any
import asyncio
from collections import defaultdict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PORT, Platform
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    MODEL_CLW_DIMUEX_P,
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_SHADE,
    DEVICE_TYPE_THERMOSTAT,
    DEVICE_TYPE_BUTTON_EVENT,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_BUTTON_LED,
    DEVICE_TYPE_SWITCH,
    DEVICE_TYPE_MOMENTARY,
    MAX_DIGITAL_JOIN,
    MAX_ANALOG_JOIN,
    MAX_SERIAL_JOIN,
    MIN_DIGITAL_JOIN,
    MIN_ANALOG_JOIN,
    MIN_SERIAL_JOIN,
    ERROR_INVALID_JOIN,
    ERROR_JOIN_IN_USE,
    ERROR_JOIN_OUT_OF_RANGE,
    DEVICE_TYPE_TO_PLATFORM,
)
from .schemas import SCHEMA_MAP, validate_join_numbers
from .config_flow_helper import EntityHelper, DeviceHelper, ValidationHelper

_LOGGER = logging.getLogger(__name__)

# Constants for validation
MAX_ENTITIES_PER_DEVICE: Final = 50
MAX_DEVICES: Final = 100
MAX_ENTITIES: Final = 500

class JoinTracker:
    """Track used joins."""

    def __init__(self) -> None:
        """Initialize the join tracker."""
        self.digital_joins_in = set()  # For input joins (events)
        self.digital_joins_out = set()  # For output joins (LEDs, momentary)
        self.analog_joins = set()
        self.join_owners = defaultdict(str)

    def validate_join(self, join: int, join_type: str, owner: str, direction: str = "out") -> None:
        """Validate join number."""
        # Check join range based on type
        if join_type == "d":
            if not MIN_DIGITAL_JOIN <= join <= MAX_DIGITAL_JOIN:
                raise ValueError(ERROR_JOIN_OUT_OF_RANGE.format(MIN_DIGITAL_JOIN, MAX_DIGITAL_JOIN))
            
            # For digital joins, check direction
            if direction == "in":
                if join in self.digital_joins_in:
                    current_owner = self.join_owners[f"d{join}_in"]
                    raise ValueError(f"Digital input join {join} already in use by {current_owner}")
                self.digital_joins_in.add(join)
                self.join_owners[f"d{join}_in"] = owner
            else:  # direction == "out"
                if join in self.digital_joins_out:
                    current_owner = self.join_owners[f"d{join}_out"]
                    raise ValueError(f"Digital output join {join} already in use by {current_owner}")
                self.digital_joins_out.add(join)
                self.join_owners[f"d{join}_out"] = owner
                
        elif join_type == "a":
            if not MIN_ANALOG_JOIN <= join <= MAX_ANALOG_JOIN:
                raise ValueError(ERROR_JOIN_OUT_OF_RANGE.format(MIN_ANALOG_JOIN, MAX_ANALOG_JOIN))
            if join in self.analog_joins:
                current_owner = self.join_owners[f"a{join}"]
                raise ValueError(f"Analog join {join} already in use by {current_owner}")
            self.analog_joins.add(join)
            self.join_owners[f"a{join}"] = owner
        else:
            raise ValueError(ERROR_INVALID_JOIN)

    def release_join(self, join: int, join_type: str, direction: str = "out") -> None:
        """Release a join number."""
        if join_type == "d":
            if direction == "in":
                self.digital_joins_in.discard(join)
                self.join_owners.pop(f"d{join}_in", None)
            else:
                self.digital_joins_out.discard(join)
                self.join_owners.pop(f"d{join}_out", None)
        elif join_type == "a":
            self.analog_joins.discard(join)
            self.join_owners.pop(f"a{join}", None)

    def clear(self) -> None:
        """Clear all tracked joins."""
        self.digital_joins_in.clear()
        self.digital_joins_out.clear()
        self.analog_joins.clear()
        self.join_owners.clear()


class CrestronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.options = {}
        self._current_config = {}
        self.join_tracker = JoinTracker()
        self._device_count = 0
        self._entity_count = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                # Validate port
                port = user_input[CONF_PORT]
                if port < 1024:
                    errors[CONF_PORT] = "port_reserved"
                elif port > 65535:
                    errors[CONF_PORT] = "port_invalid"
                else:
                    await self.async_set_unique_id(f"{DOMAIN}_{port}")
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Crestron (Port {port})",
                        data=user_input
                    )

            except Exception as err:
                _LOGGER.error("Error in user step: %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }),
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CrestronOptionsFlow:
        """Get the options flow for this handler."""
        return CrestronOptionsFlow(config_entry)


class CrestronOptionsFlow(config_entries.OptionsFlow):
    """Handle Crestron options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.options = dict(config_entry.options)
        self._config_entry = config_entry
        self._entity_count = len(self.options.get("entities", []))
        self._device_count = len(self.options.get("devices", []))
        self.join_tracker = JoinTracker()  # Initialize join tracker
        
        # Initialize helpers
        self.entity_helper = EntityHelper(self.join_tracker, self.options, self._entity_count)
        self.device_helper = DeviceHelper(self._config_entry, self.options, self._device_count)
        self.validation_helper = ValidationHelper(self._entity_count, self._device_count)
        
        # Track existing joins
        for entity in self.options.get("entities", []):
            try:
                name = entity.get("name", "")
                device_type = entity.get("device_type", "")
                
                # Track joins based on device type
                if device_type == DEVICE_TYPE_LIGHT:
                    join = entity.get("brightness_join")
                    if join:
                        self.join_tracker.validate_join(join, "a", name)
                elif device_type == DEVICE_TYPE_SHADE:
                    pos_join = entity.get("position_join")
                    if pos_join:
                        self.join_tracker.validate_join(pos_join, "a", f"{name} Position")
                    closed_join = entity.get("closed_join")
                    if closed_join:
                        self.join_tracker.validate_join(closed_join, "d", f"{name} Closed")
                    stop_join = entity.get("stop_join")
                    if stop_join:
                        self.join_tracker.validate_join(stop_join, "d", f"{name} Stop")
                elif device_type == DEVICE_TYPE_BUTTON_EVENT:
                    join = entity.get("join")
                    if join:
                        self.join_tracker.validate_join(join, "d", name, "in")  # Input
                elif device_type == DEVICE_TYPE_BUTTON_LED:
                    join = entity.get("join")
                    if join:
                        self.join_tracker.validate_join(join, "d", name, "out")  # Output
                elif device_type == DEVICE_TYPE_SWITCH:
                    join = entity.get("switch_join")
                    if join:
                        self.join_tracker.validate_join(join, "d", name)
                elif device_type == DEVICE_TYPE_MOMENTARY:
                    join = entity.get("momentary_join")
                    if join:
                        self.join_tracker.validate_join(join, "d", name, "out")  # Output
                        
            except Exception as err:
                _LOGGER.debug(
                    "Non-critical error tracking existing join for %s: %s",
                    name,
                    err
                )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        return await self.async_step_menu()

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the menu step."""
        if user_input is not None:
            if user_input["next_step"] == "add":
                return await self.async_step_add()
            elif user_input["next_step"] == "remove":
                return await self.async_step_remove()

        return self.async_show_form(
            step_id="menu",
            data_schema=vol.Schema({
                vol.Required("next_step"): vol.In({
                    "add": "Add Entity/Device",
                    "remove": "Remove Entity/Device",
                })
            }),
            description_placeholders={
                "entity_count": str(self._entity_count),
                "device_count": str(self._device_count),
            }
        )

    async def _update_entry(self) -> None:
        """Update config entry with current options."""
        # Update the config entry
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options=self.options
        )
        
        # Reload the integration to apply changes immediately
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)

    async def async_step_add(
        self,
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a new entity."""
        errors = {}

        if user_input is not None:
            try:
                self.context["device_type"] = user_input["device_type"]
                return await self.async_step_configure_entity()
            except Exception as err:
                _LOGGER.error("Error in add_entity step: %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="add",
            data_schema=vol.Schema({
                vol.Required("device_type"): vol.In({
                    DEVICE_TYPE_LIGHT: "Light (Analog I/O)",
                    DEVICE_TYPE_SHADE: "Shade (Mixed I/O)",
                    DEVICE_TYPE_THERMOSTAT: "Thermostat (Mixed I/O)",
                    DEVICE_TYPE_BUTTON_EVENT: "Button Event (Digital IN)",
                    DEVICE_TYPE_SENSOR: "Sensor (Digital IN)",
                    DEVICE_TYPE_BUTTON_LED: "Button LED (Digital OUT)",
                    DEVICE_TYPE_SWITCH: "Switch (Digital I/O)",
                    DEVICE_TYPE_MOMENTARY: "Momentary (Digital OUT)",
                    MODEL_CLW_DIMUEX_P: "CLW-DIMUEX-P (Mixed I/O)",
                }),
            }),
            errors=errors
        )

    async def async_step_configure_entity(
        self,
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure the selected entity type."""
        errors = {}
        device_type = self.context["device_type"]

        if user_input is not None:
            try:
                # Validate entity count
                self.validation_helper.validate_entity_count(1)

                if device_type == MODEL_CLW_DIMUEX_P:
                    await self._process_clw_dimuex(user_input)
                else:
                    # Create single entity
                    entity_config = {"device_type": device_type, **user_input}
                    await self.entity_helper.create_entity(entity_config)
                    
                    # Save options
                    await self._update_entry()
                    
                    # Reload affected platform
                    if platform := DEVICE_TYPE_TO_PLATFORM.get(device_type):
                        await self._reload_platforms({platform})

                return self.async_create_entry(title="", data=self.options)

            except ValueError as err:
                _LOGGER.error("Validation error: %s", err)
                errors["base"] = str(err)
            except Exception as err:
                _LOGGER.error("Error configuring entity: %s", err)
                errors["base"] = "unknown"

        # Get schema for selected device type
        schema = SCHEMA_MAP.get(device_type)
        if not schema:
            _LOGGER.error("No schema found for device type: %s", device_type)
            return self.async_abort(reason="unknown_device_type")

        return self.async_show_form(
            step_id="configure_entity",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device_type": device_type,
                "entity_count": str(self._entity_count),
                "max_entities": str(MAX_ENTITIES),
            }
        )

    async def _process_clw_dimuex(self, config: dict) -> None:
        """Process CLW-DIMUEX-P configuration."""
        try:
            _LOGGER.debug("Processing CLW-DIMUEX-P configuration: %s", config)
            
            # Get button count (required 2-4 buttons)
            button_count = config["button_count"]
            total_entities = button_count * 3  # Button + LED + Select for each button
            
            if "light_join" in config:
                total_entities += 1
                
            # Validate entity and device counts
            self.validation_helper.validate_entity_count(total_entities)
            self.validation_helper.validate_device_count()
            
            name = config[CONF_NAME]
            
            # Create device first
            device_config = {
                "model": MODEL_CLW_DIMUEX_P,
                "name": name,
                "button_count": button_count,
            }
            
            device_id, device_name = await self.device_helper.create_device(device_config)
            platforms_to_reload = set()
            
            # Add light if configured (Analog I/O)
            if "light_join" in config:
                light_join = config["light_join"]
                light_config = {
                    "name": "Dimmer",
                    "device_type": DEVICE_TYPE_LIGHT,
                    "brightness_join": light_join,
                    "device_id": device_id,
                    "entity_id": f"{device_name}_dimmer",
                }
                await self.entity_helper.create_entity(light_config)
                platforms_to_reload.add("light")
            
            # Process buttons (Digital I/O)
            base_join = config["button_1_join"]
            
            # Validate base join and ensure space for all buttons
            if base_join > MAX_DIGITAL_JOIN - (button_count - 1):
                raise ValueError(f"Base join {base_join} too high for {button_count} sequential buttons")
            
            # Create buttons with sequential joins
            for i in range(1, button_count + 1):
                current_join = base_join + (i-1)
                button_config = {
                    "number": i,
                    "join": current_join,
                }
                # Create button event and LED entities
                self.entity_helper.create_button_entities(device_name, button_config, device_id)
            
            # Add all affected platforms
            platforms_to_reload.update({"event", "switch", "select"})
            
            # Save options
            await self._update_entry()
            
            # Reload all affected platforms
            await self._reload_platforms(platforms_to_reload)
            
        except Exception as err:
            _LOGGER.error(
                "Error processing CLW-DIMUEX-P configuration: %s",
                err
            )
            raise

    async def async_step_add_device(
        self,
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a new device (collection of entities)."""
        errors = {}

        if user_input is not None:
            try:
                self.context["device_type"] = user_input["device_type"]
                if user_input["device_type"] == MODEL_CLW_DIMUEX_P:
                    return await self.async_step_clw_dimuex()
                # Add other device type handlers as needed
            except Exception as err:
                _LOGGER.error("Error in add_device step: %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema({
                vol.Required("device_type"): vol.In({
                    MODEL_CLW_DIMUEX_P: "CLW-DIMUEX-P (Keypad with Dimmer)",
                    # Add other device types here as needed
                }),
            }),
            errors=errors,
            description_placeholders={
                "device_count": str(self._device_count),
                "max_devices": str(MAX_DEVICES),
            }
        )

    async def async_step_remove(self, user_input=None):
        """Handle removal of entities and devices."""
        if user_input is None:
            # Build schema with individual checkboxes for each entity and device
            schema = {}
            
            # Add devices first
            for device in self.options.get("devices", []):
                name = device.get("name", device["unique_id"])
                schema[vol.Optional(f"device_{device['unique_id']}", default=False)] = bool
            
            # Then add entities that don't belong to a device
            for entity in self.options.get("entities", []):
                if not entity.get("device_id"):
                    name = entity[CONF_NAME]
                    schema[vol.Optional(f"entity_{name}", default=False)] = bool
            
            if not schema:
                return self.async_abort(reason="no_entities_or_devices")
            
            return self.async_show_form(
                step_id="remove",
                data_schema=vol.Schema(schema),
                description_placeholders={
                    "count": len(schema)
                }
            )
        
        try:
            # Get registries
            entity_registry = er.async_get(self.hass)
            device_registry = dr.async_get(self.hass)
            
            # Track what needs to be reloaded
            platforms_to_reload = set()
            
            # Process selected items
            for key, selected in user_input.items():
                if not selected:
                    continue
                    
                if key.startswith("device_"):
                    # Remove device
                    device_id = key[7:]  # Strip "device_" prefix
                    device = next(
                        (d for d in self.options.get("devices", [])
                         if d["unique_id"] == device_id),
                        None
                    )
                    if device:
                        await self.device_helper.remove_device(
                            device, 
                            entity_registry, 
                            device_registry,
                            self.entity_helper
                        )
                        # Add platforms for all entity types in this device
                        for entity in self.options.get("entities", []):
                            if entity.get("device_id") == device_id:
                                platform = DEVICE_TYPE_TO_PLATFORM.get(
                                    entity.get("device_type", "")
                                )
                                if platform:
                                    platforms_to_reload.add(platform)
                
                elif key.startswith("entity_"):
                    # Remove entity
                    entity_name = key[7:]  # Strip "entity_" prefix
                    entity = next(
                        (e for e in self.options.get("entities", [])
                         if e[CONF_NAME] == entity_name),
                        None
                    )
                    if entity:
                        await self.entity_helper.remove_entity(entity, entity_registry)
                        # Add platform for this entity type
                        platform = DEVICE_TYPE_TO_PLATFORM.get(
                            entity.get("device_type", "")
                        )
                        if platform:
                            platforms_to_reload.add(platform)
            
            # Update entry
            await self._update_entry()
            
            # Reload affected platforms
            await self._reload_platforms(platforms_to_reload)
            
            return self.async_create_entry(title="", data={})
            
        except Exception as err:
            _LOGGER.error("Error in remove step: %s", err)
            return self.async_abort(reason="remove_failed")

    async def _reload_platforms(self, platforms: set) -> None:
        """Reload the specified platforms."""
        try:
            # First, ensure the platforms are loaded
            await self.hass.config_entries.async_forward_entry_setups(
                self._config_entry, list(platforms)
            )
            
            # Then reload them
            for platform in platforms:
                try:
                    # Attempt to unload the platform
                    await self.hass.config_entries.async_unload_platforms(
                        self._config_entry, [platform]
                    )
                    # Reload it
                    await self.hass.config_entries.async_forward_entry_setups(
                        self._config_entry, [platform]
                    )
                    _LOGGER.debug("Reloaded platform %s", platform)
                except ValueError as err:
                    # Handle case where platform was not loaded
                    _LOGGER.debug(
                        "Platform %s was not loaded, skipping unload: %s",
                        platform,
                        err
                    )
                except Exception as err:
                    _LOGGER.error(
                        "Error reloading platform %s: %s",
                        platform,
                        err
                    )
                    raise
        except Exception as err:
            _LOGGER.error(
                "Error reloading platforms: %s",
                err
            )
            raise