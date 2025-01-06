"""Config flow for Crestron integration."""
from __future__ import annotations

import logging
from typing import Any, Final
import asyncio
from collections import defaultdict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PORT
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
                # Check entity count
                if self._entity_count >= MAX_ENTITIES:
                    raise ValueError(f"Maximum of {MAX_ENTITIES} entities reached")

                # Validate joins before adding
                name = user_input.get(CONF_NAME, "")
                
                # Track joins based on device type
                if device_type == DEVICE_TYPE_LIGHT:
                    join = user_input.get("brightness_join")
                    if join:
                        self.join_tracker.validate_join(join, "a", name)
                elif device_type == DEVICE_TYPE_SHADE:
                    pos_join = user_input.get("position_join")
                    if pos_join:
                        self.join_tracker.validate_join(pos_join, "a", f"{name} Position")
                    closed_join = user_input.get("closed_join")
                    if closed_join:
                        self.join_tracker.validate_join(closed_join, "d", f"{name} Closed")
                    stop_join = user_input.get("stop_join")
                    if stop_join:
                        self.join_tracker.validate_join(stop_join, "d", f"{name} Stop")
                elif device_type in [DEVICE_TYPE_BUTTON_LED, DEVICE_TYPE_BUTTON_EVENT]:
                    join = user_input.get("join")
                    if join:
                        self.join_tracker.validate_join(join, "d", name, "in")  # Input
                elif device_type == DEVICE_TYPE_SWITCH:
                    join = user_input.get("switch_join")
                    if join:
                        self.join_tracker.validate_join(join, "d", name)
                elif device_type == DEVICE_TYPE_MOMENTARY:
                    join = user_input.get("join")
                    if join:
                        self.join_tracker.validate_join(join, "d", name, "out")  # Output

                # Validate using schema
                validated_config = validate_join_numbers(
                    {"device_type": device_type, **user_input}
                )

                # Initialize options structure if needed
                if "entities" not in self.options:
                    self.options["entities"] = []

                if device_type == MODEL_CLW_DIMUEX_P:
                    await self._process_clw_dimuex(validated_config)
                else:
                    # Add validated entity configuration
                    self.options["entities"].append(validated_config)
                    self._entity_count += 1

                    # Save options and reload immediately
                    await self._update_entry()

                    if device_type == DEVICE_TYPE_BUTTON_LED:
                        _LOGGER.debug(
                            "Saved LED entity config: %s",
                            validated_config
                        )

                # Force reload of affected platform
                platform = DEVICE_TYPE_TO_PLATFORM.get(device_type)
                if platform:
                    try:
                        # First unload the platform
                        await self.hass.config_entries.async_unload_platforms(
                            self._config_entry, [platform]
                        )
                        # Then reload it
                        await self.hass.config_entries.async_forward_entry_setups(
                            self._config_entry, [platform]
                        )
                        _LOGGER.debug("Reloaded platform %s", platform)
                    except Exception as err:
                        _LOGGER.error("Error reloading platform %s: %s", platform, err)

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

    def _create_button_entities(self, device_name: str, button_config: dict, device_id: str) -> None:
        """Create button and LED entities for a device."""
        try:
            button_number = button_config["number"]
            button_join = button_config["join"]
            
            # Validate join number
            self.join_tracker.validate_join(button_join, "d", f"{device_name} Button {button_number}")
            
            # Create button event entity (Digital IN from Crestron)
            button_entity = {
                "name": f"{device_name} Button {button_number}",
                "device_type": DEVICE_TYPE_BUTTON_EVENT,
                "join": button_join,  # Same join for event
                "device_id": device_id,
            }
            self.options["entities"].append(button_entity)
            self._entity_count += 1
            _LOGGER.debug("Added button event entity: Button %d (join=%d)", button_number, button_join)

            # Create LED entity (Digital OUT to Crestron)
            led_entity = {
                "name": f"{device_name} Button {button_number}",
                "device_type": DEVICE_TYPE_BUTTON_LED,
                "join": button_join,  # Same join for LED
                "device_id": device_id,
            }
            self.options["entities"].append(led_entity)
            self._entity_count += 1
            _LOGGER.debug("Added LED entity: Button %d (join=%d)", button_number, button_join)
            
        except Exception as err:
            _LOGGER.error(
                "Error creating button entities for %s: %s",
                device_name,
                err
            )
            raise

    async def _process_clw_dimuex(self, config: dict) -> None:
        """Process CLW-DIMUEX-P configuration."""
        try:
            _LOGGER.debug("Processing CLW-DIMUEX-P configuration: %s", config)
            
            # Validate entity count
            total_entities = 1  # Light entity
            if "auto_populate" in config:
                total_entities += config["auto_populate"] * 2  # Button + LED for each
            if self._entity_count + total_entities > MAX_ENTITIES:
                raise ValueError(f"Adding this device would exceed maximum of {MAX_ENTITIES} entities")
            
            name = config[CONF_NAME]
            unique_id = f"{DOMAIN}_{name}_clw_dimuex"
            
            _LOGGER.debug("Creating device config with unique_id: %s", unique_id)
            
            device_config = {
                "model": MODEL_CLW_DIMUEX_P,
                "name": name,
                "unique_id": unique_id,
            }

            # Add light if configured (Analog I/O)
            if "light_join" in config:
                light_join = config["light_join"]
                self.join_tracker.validate_join(light_join, "a", f"{name} Dimmer")
                
                device_config["light_join"] = light_join
                _LOGGER.debug("Added light join: %s", light_join)
                
                light_entity = {
                    "name": f"{name} Dimmer",
                    "device_type": DEVICE_TYPE_LIGHT,
                    "brightness_join": light_join,
                    "device_id": unique_id,
                }
                self.options["entities"].append(light_entity)
                self._entity_count += 1
                _LOGGER.debug("Added dimmer entity")

            # Process buttons (Digital I/O)
            buttons = {}
            base_join = config["button_1_join"]
            auto_populate = config.get("auto_populate", 0)

            # Validate base join
            self.join_tracker.validate_join(base_join, "d", f"{name} Button 1")

            # Add first button (required)
            buttons["1"] = {"number": 1, "join": base_join}
            _LOGGER.debug("Added button 1: %s", base_join)

            # Auto-populate additional buttons if requested
            if auto_populate > 0:
                for i in range(2, auto_populate + 1):
                    join = base_join + (i-1)  # Sequential joins
                    self.join_tracker.validate_join(join, "d", f"{name} Button {i}")
                    buttons[str(i)] = {
                        "number": i,
                        "join": join
                    }

            device_config["buttons"] = buttons
            _LOGGER.debug("Auto-populated buttons: %s", buttons)

            # Add device config
            if "devices" not in self.options:
                self.options["devices"] = []
            self.options["devices"].append(device_config)
            self._device_count += 1
            _LOGGER.debug("Added device to options: %s", device_config)

            # Create entities for each button
            for button_config in buttons.values():
                self._create_button_entities(name, button_config, unique_id)

            _LOGGER.debug("Final options state: %s", self.options)
            
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

    async def async_step_remove(
        self,
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle removing entities or devices."""
        if user_input is not None:
            try:
                entities = self.options.get("entities", [])
                devices = self.options.get("devices", [])
                removed_device_ids = set()
                
                # Process selected items for removal
                selected = user_input["items"]
                
                # Remove selected entities
                new_entities = []
                entity_registry = er.async_get(self.hass)
                
                for entity in entities:
                    entity_id = f"entity_{entity[CONF_NAME]}"
                    if entity_id not in selected:
                        new_entities.append(entity)
                    else:
                        # Find and remove the actual entity
                        device_type = entity.get("device_type", "")
                        if device_type == DEVICE_TYPE_BUTTON_LED:
                            # Also remove binding if it exists
                            binding_id = None
                            for ent_id, ent in entity_registry.entities.items():
                                if "led_binding" in ent_id and entity[CONF_NAME] in ent_id:
                                    binding_id = ent_id
                                    break
                            if binding_id:
                                entity_registry.async_remove(binding_id)
                            
                        # Remove the entity itself
                        for ent_id, ent in entity_registry.entities.items():
                            if (
                                ent.platform == DOMAIN and
                                entity[CONF_NAME] in ent_id
                            ):
                                entity_registry.async_remove(ent_id)
                                break
                            
                        self._entity_count -= 1
                
                self.options["entities"] = new_entities
                
                # Remove selected devices and their associated entities
                if devices:
                    new_devices = []
                    device_registry = dr.async_get(self.hass)
                    
                    for device in devices:
                        if f"device_{device['unique_id']}" not in selected:
                            new_devices.append(device)
                        else:
                            removed_device_ids.add(device['unique_id'])
                            # Remove device and all its entities
                            if device_entry := device_registry.async_get_device(
                                identifiers={(DOMAIN, device['unique_id'])}
                            ):
                                # First remove all entities belonging to this device
                                for entity_entry in er.async_entries_for_device(
                                    entity_registry,
                                    device_entry.id
                                ):
                                    entity_registry.async_remove(entity_entry.entity_id)
                                # Then remove the device
                                device_registry.async_remove_device(device_entry.id)
                            self._device_count -= 1
                    
                    self.options["devices"] = new_devices
                
                # Save options and reload immediately
                await self._update_entry()
                
                return self.async_create_entry(title="", data=self.options)
                
            except Exception as err:
                _LOGGER.error("Error removing items: %s", err)
                return self.async_abort(reason="remove_failed")

        # Get list of entities and devices that can be removed
        entities = self.options.get("entities", [])
        devices = self.options.get("devices", [])
        
        options = {}
        
        # Add entities to options
        for entity in entities:
            name = entity[CONF_NAME]
            device_type = entity.get("device_type", "")
            if device_type == DEVICE_TYPE_BUTTON_LED:
                options[f"entity_{name}"] = f"LED Entity: {name}"
            else:
                options[f"entity_{name}"] = f"Entity: {name}"
            
        # Add devices to options
        for device in devices:
            name = device.get("name", device["unique_id"])
            options[f"device_{device['unique_id']}"] = f"Device: {name}"

        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema({
                vol.Optional("items"): cv.multi_select(options)
            }),
            description_placeholders={
                "entity_count": str(self._entity_count),
                "device_count": str(self._device_count),
            }
        )