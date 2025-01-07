"""Support for Crestron switches."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Final
from collections import deque

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    DEVICE_TYPE_SWITCH,
    DEVICE_TYPE_BUTTON_LED,
    MAX_DIGITAL_JOIN,
    ERROR_INVALID_JOIN,
    JOIN_TYPE_DIGITAL,
)
from .entity import CrestronEntity

_LOGGER = logging.getLogger(__name__)

class CrestronSwitch(CrestronEntity[bool], SwitchEntity):
    """Representation of a Crestron switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        name: str,
        server: CrestronServer,
        join: int,
        device_id: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        """Initialize the switch."""
        super().__init__(
            name=name,
            server=server,
            join_type=JOIN_TYPE_DIGITAL,  # Digital join
            join=join,
            device_id=device_id,
            entity_id=entity_id,
        )
        
        # Initialize state
        self._attr_is_on = False
        
        _LOGGER.debug(
            "Switch '%s' initialized with join d%s",
            name,
            join
        )

class CrestronButtonLED(CrestronEntity[bool], SwitchEntity):
    """Representation of a Crestron button LED."""

    _attr_has_entity_name = True

    def __init__(
        self,
        name: str,
        server: CrestronServer,
        join: int,
        device_id: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        """Initialize the LED."""
        super().__init__(
            name=name,
            server=server,
            join_type="d",  # Digital join
            join=join,
            device_id=device_id,
            entity_id=entity_id,
        )
        
        # Initialize state
        self._attr_is_on = False
        
        _LOGGER.debug(
            "LED '%s' initialized with join d%s",
            name,
            join
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        await super().async_added_to_hass()
        
        try:
            # For output-only entities, we don't need to request initial state
            # Just mark as available when server is connected
            self._attr_available = self._server.is_available()
            
            # Restore previous state if available
            if last_state := await self.async_get_last_state():
                self._attr_is_on = last_state.state == "on"
                
                # Only try to re-apply state if server is available
                if self._server.is_available():
                    await self._server.set_digital(self._join, self._attr_is_on)
            
            _LOGGER.debug(
                "LED '%s' restored state: %s, available: %s",
                self.name,
                "on" if self._attr_is_on else "off",
                self._attr_available
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error setting up button LED %s: %s",
                self.name,
                err,
                exc_info=True
            )
            self._attr_available = False

    @callback
    def _handle_update(self, value: str) -> None:
        """Handle updates from server."""
        try:
            value_bool = value == "1"
            
            # Only process if value actually changed
            if value_bool == self._attr_is_on:
                return
            
            # Update state
            self._attr_is_on = value_bool
            
            # Log state change
            _LOGGER.debug(
                "%s: State changed to %s",
                self.name,
                "on" if value_bool else "off"
            )
            
            # Update HA state
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error handling update for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the LED on."""
        try:
            await self._server.set_digital(self._join, True)
            self._attr_is_on = True
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error("Error turning on %s: %s", self.name, err)
            raise HomeAssistantError(f"Failed to turn on {self.name}: {err}") from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the LED off."""
        try:
            await self._server.set_digital(self._join, False)
            self._attr_is_on = False
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error("Error turning off %s: %s", self.name, err)
            raise HomeAssistantError(f"Failed to turn off {self.name}: {err}") from err

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron switches."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        # Get configured entities from options
        entity_configs = entry.options.get("entities", [])
        
        # Get entity registry to check existing entities
        entity_registry = er.async_get(hass)
        
        for entity_config in entity_configs:
            try:
                device_type = entity_config.get("device_type")
                
                # Skip if not a switch or LED
                if device_type not in [DEVICE_TYPE_SWITCH, DEVICE_TYPE_BUTTON_LED]:
                    continue

                name = entity_config.get("name", "")
                keypad_name = entity_config.get("keypad_name")  # Get keypad name
                
                # Get join based on device type
                if device_type == DEVICE_TYPE_SWITCH:
                    join = entity_config.get("switch_join")
                else:  # DEVICE_TYPE_BUTTON_LED
                    join = entity_config.get("join")
                    
                device_id = entity_config.get("device_id")

                if not name or join is None:
                    _LOGGER.warning(
                        "Skipping switch entity with missing required config: %s",
                        entity_config
                    )
                    continue

                # Validate join number
                if not 0 < join <= MAX_DIGITAL_JOIN:
                    raise ValueError(f"{ERROR_INVALID_JOIN}: {join}")

                # Create appropriate entity based on device type
                entity_class = CrestronSwitch if device_type == DEVICE_TYPE_SWITCH else CrestronButtonLED
                entity = entity_class(
                    name=name,
                    server=server,
                    join=join,
                    device_id=device_id,
                    entity_id=entity_config.get("entity_id"),
                )
                entities.append(entity)
                
                _LOGGER.debug(
                    "Added %s entity: %s (join=%s)",
                    device_type,
                    name,
                    join
                )
                
            except Exception as err:
                _LOGGER.error(
                    "Error setting up switch entity %s: %s",
                    entity_config.get("name", "unknown"),
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            _LOGGER.debug("Added %d switch entities", len(entities))
            
    except Exception as err:
        _LOGGER.error("Error setting up switch platform: %s", err)
        raise HomeAssistantError(f"Switch platform setup failed: {err}") from err