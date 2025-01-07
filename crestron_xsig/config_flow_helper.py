"""Helper methods for Crestron config flow."""
from __future__ import annotations

import logging
from typing import Any, Final

from homeassistant.const import CONF_NAME
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import (
    DOMAIN,
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_SHADE,
    DEVICE_TYPE_BUTTON_EVENT,
    DEVICE_TYPE_BUTTON_LED,
    DEVICE_TYPE_SWITCH,
    DEVICE_TYPE_MOMENTARY,
    DEVICE_TYPE_TO_PLATFORM,
)
from .schemas import validate_join_numbers

_LOGGER = logging.getLogger(__name__)

# Constants for validation
MAX_ENTITIES_PER_DEVICE: Final = 50
MAX_DEVICES: Final = 100
MAX_ENTITIES: Final = 500

class EntityHelper:
    """Helper class for entity operations."""

    def __init__(self, join_tracker, options: dict, entity_count: int) -> None:
        """Initialize entity helper."""
        self.join_tracker = join_tracker
        self.options = options
        self._entity_count = entity_count

    def create_button_entities(self, device_name: str, button_config: dict, device_id: str) -> None:
        """Create button event and LED entities for a keypad button."""
        try:
            button_number = button_config["number"]
            join = button_config["join"]
            
            # Validate join number
            self.join_tracker.validate_join(join, "d", f"Button {button_number}")
            
            # Create button event entity (Digital IN from Crestron)
            button_entity = {
                "name": f"Button {button_number}",
                "device_type": DEVICE_TYPE_BUTTON_EVENT,
                "join": join,
                "device_id": device_id,
                "entity_id": f"{device_name}_button_{button_number}",
            }
            self.options["entities"].append(button_entity)
            self._entity_count += 1
            _LOGGER.debug("Added button event entity: Button %d (join=%d)", button_number, join)

            # Create LED entity (Digital OUT to Crestron)
            led_entity = {
                "name": f"LED {button_number}",
                "device_type": DEVICE_TYPE_BUTTON_LED,
                "join": join,
                "device_id": device_id,
                "entity_id": f"{device_name}_led_{button_number}",
            }
            self.options["entities"].append(led_entity)
            self._entity_count += 1
            _LOGGER.debug("Added LED entity: LED %d (join=%d)", button_number, join)
            
        except Exception as err:
            _LOGGER.error(
                "Error creating button entities for %s button %d: %s",
                device_name,
                button_number,
                err
            )
            raise

    async def remove_entity(self, entity: dict, entity_registry: er.EntityRegistry) -> None:
        """Remove a single entity and release its joins."""
        try:
            name = entity[CONF_NAME]
            device_type = entity.get("device_type", "")
            
            # Release joins based on device type
            if device_type == DEVICE_TYPE_LIGHT:
                join = entity.get("brightness_join")
                if join:
                    self.join_tracker.release_join(join, "a")
            elif device_type == DEVICE_TYPE_SHADE:
                pos_join = entity.get("position_join")
                if pos_join:
                    self.join_tracker.release_join(pos_join, "a")
                closed_join = entity.get("closed_join")
                if closed_join:
                    self.join_tracker.release_join(closed_join, "d")
                stop_join = entity.get("stop_join")
                if stop_join:
                    self.join_tracker.release_join(stop_join, "d")
            elif device_type == DEVICE_TYPE_BUTTON_EVENT:
                join = entity.get("join")
                if join:
                    self.join_tracker.release_join(join, "d", "in")
            elif device_type == DEVICE_TYPE_BUTTON_LED:
                join = entity.get("join")
                if join:
                    self.join_tracker.release_join(join, "d", "out")
                # Also remove binding if it exists
                binding_id = None
                for ent_id, ent in entity_registry.entities.items():
                    if "led_binding" in ent_id and name in ent_id:
                        binding_id = ent_id
                        break
                if binding_id:
                    entity_registry.async_remove(binding_id)
            elif device_type == DEVICE_TYPE_SWITCH:
                join = entity.get("switch_join")
                if join:
                    self.join_tracker.release_join(join, "d")
            elif device_type == DEVICE_TYPE_MOMENTARY:
                join = entity.get("momentary_join")
                if join:
                    self.join_tracker.release_join(join, "d", "out")
            
            # Remove the entity from registry
            for ent_id, ent in entity_registry.entities.items():
                if (
                    ent.platform == DOMAIN and
                    name in ent_id
                ):
                    entity_registry.async_remove(ent_id)
                    break
            
            self._entity_count -= 1
            _LOGGER.debug(
                "Removed entity %s (type=%s)",
                name,
                device_type
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error removing entity %s: %s",
                name,
                err
            )
            raise

    async def create_entity(self, entity_config: dict) -> None:
        """Create a single entity with validation.
        
        Args:
            entity_config: Entity configuration including device_type and required joins
            
        Returns:
            None
            
        Raises:
            ValueError: If validation fails
        """
        try:
            # Validate the configuration
            validated_config = validate_join_numbers(entity_config)
            
            # Track joins based on device type
            device_type = validated_config["device_type"]
            name = validated_config.get(CONF_NAME, "")
            
            if device_type == DEVICE_TYPE_LIGHT:
                join = validated_config.get("brightness_join")
                if join:
                    self.join_tracker.validate_join(join, "a", name)
            elif device_type == DEVICE_TYPE_SHADE:
                pos_join = validated_config.get("position_join")
                if pos_join:
                    self.join_tracker.validate_join(pos_join, "a", f"{name} Position")
                closed_join = validated_config.get("closed_join")
                if closed_join:
                    self.join_tracker.validate_join(closed_join, "d", f"{name} Closed")
                stop_join = validated_config.get("stop_join")
                if stop_join:
                    self.join_tracker.validate_join(stop_join, "d", f"{name} Stop")
            elif device_type == DEVICE_TYPE_BUTTON_EVENT:
                join = validated_config.get("join")
                if join:
                    self.join_tracker.validate_join(join, "d", name, "in")
            elif device_type == DEVICE_TYPE_BUTTON_LED:
                join = validated_config.get("join")
                if join:
                    self.join_tracker.validate_join(join, "d", name, "out")
            elif device_type == DEVICE_TYPE_SWITCH:
                join = validated_config.get("switch_join")
                if join:
                    self.join_tracker.validate_join(join, "d", name)
            elif device_type == DEVICE_TYPE_MOMENTARY:
                join = validated_config.get("momentary_join")
                if join:
                    self.join_tracker.validate_join(join, "d", name, "out")
            
            # Add the validated entity
            if "entities" not in self.options:
                self.options["entities"] = []
            
            self.options["entities"].append(validated_config)
            self._entity_count += 1
            
            _LOGGER.debug(
                "Created entity: %s (type=%s)",
                name,
                device_type
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error creating entity: %s",
                err
            )
            raise

class DeviceHelper:
    """Helper class for device operations."""

    def __init__(self, config_entry, options: dict, device_count: int) -> None:
        """Initialize device helper."""
        self._config_entry = config_entry
        self.options = options
        self._device_count = device_count

    async def create_device(self, device_config: dict) -> tuple[str, str]:
        """Create a device entry and return its ID and name."""
        try:
            name = device_config[CONF_NAME]
            model = device_config["model"]
            
            # Create device unique ID
            device_unique_id = f"{DOMAIN}_{name}_{model.lower()}"
            
            # Create device config
            device_entry = {
                "model": model,
                "name": name,  # Original configured name
                "unique_id": device_unique_id,
                "entry_id": self._config_entry.entry_id,
                "manufacturer": "Crestron",
                "sw_version": "1.0.0",
                "identifiers": [(DOMAIN, device_unique_id)],
                **device_config,  # Include any additional device-specific config
            }
            
            # Initialize devices list if needed
            if "devices" not in self.options:
                self.options["devices"] = []
            
            # Add device
            self.options["devices"].append(device_entry)
            self._device_count += 1
            
            _LOGGER.debug(
                "Created device: %s (model=%s)",
                name,
                model
            )
            
            return device_unique_id, name
            
        except Exception as err:
            _LOGGER.error(
                "Error creating device: %s",
                err
            )
            raise

    async def remove_device(self, device: dict, entity_registry: er.EntityRegistry, device_registry: dr.DeviceRegistry, entity_helper: EntityHelper) -> None:
        """Remove a device and all its child entities."""
        try:
            device_id = device["unique_id"]
            name = device.get("name", device_id)
            
            # First remove all child entities from our options
            new_entities = [
                entity for entity in self.options["entities"]
                if entity.get("device_id") != device_id
            ]
            
            # Count removed entities
            removed_count = len(self.options["entities"]) - len(new_entities)
            self.options["entities"] = new_entities
            
            # Remove from registry
            if device_entry := device_registry.async_get_device(
                identifiers={(DOMAIN, device_id)}
            ):
                # Remove all entities belonging to this device
                device_entities = list(er.async_entries_for_device(
                    entity_registry,
                    device_entry.id
                ))
                for entity_entry in device_entities:
                    entity_registry.async_remove(entity_entry.entity_id)
                
                # Then remove the device
                device_registry.async_remove_device(device_entry.id)
            
            # Release joins for all removed entities
            for entity in self.options.get("entities", []):
                if entity.get("device_id") == device_id:
                    await entity_helper.remove_entity(entity, entity_registry)
            
            self._device_count -= 1
            _LOGGER.debug(
                "Removed device %s and %d child entities",
                name,
                removed_count
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error removing device %s: %s",
                name,
                err
            )
            raise

class ValidationHelper:
    """Helper class for validation operations."""

    def __init__(self, entity_count: int, device_count: int) -> None:
        """Initialize validation helper."""
        self._entity_count = entity_count
        self._device_count = device_count

    def validate_entity_count(self, additional_entities: int) -> None:
        """Validate that adding entities won't exceed the maximum."""
        if self._entity_count + additional_entities > MAX_ENTITIES:
            raise ValueError(
                f"Adding {additional_entities} entities would exceed maximum of {MAX_ENTITIES}"
            )
            
    def validate_device_count(self) -> None:
        """Validate that adding a device won't exceed the maximum."""
        if self._device_count + 1 > MAX_DEVICES:
            raise ValueError(
                f"Maximum of {MAX_DEVICES} devices reached"
            ) 