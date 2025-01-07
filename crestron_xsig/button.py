"""Support for Crestron momentary buttons."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Final
from collections import deque

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    DEVICE_TYPE_MOMENTARY,
    MAX_DIGITAL_JOIN,
    ERROR_INVALID_JOIN,
    JOIN_TYPE_DIGITAL,
)
from .entity import CrestronEntity

_LOGGER = logging.getLogger(__name__)

# Constants for state validation
PRESS_DURATION: Final = 0.25  # Default press duration in seconds
MAX_PRESS_DURATION: Final = 1.0  # Maximum press duration
MIN_PRESS_DURATION: Final = 0.01  # Minimum press duration
MAX_RETRY_ATTEMPTS: Final = 3  # Maximum retry attempts
COMMAND_TIMEOUT: Final = 5.0  # Command timeout in seconds
MAX_QUEUE_SIZE: Final = 5  # Maximum press queue size
QUEUE_TIMEOUT: Final = 0.5  # Queue timeout in seconds

class CrestronMomentaryButton(CrestronEntity[bool], ButtonEntity):
    """Representation of a Crestron momentary button."""

    _attr_has_entity_name = True

    def __init__(
        self,
        name: str,
        server,
        join: int,
        device_id: str | None = None,
        press_duration: float = PRESS_DURATION,
    ) -> None:
        """Initialize the button."""
        # Initialize without join_type to prevent callback registration
        super().__init__(
            name=name,
            server=server,
            join_type=None,  # Output only - no callbacks
            join=None,  # Don't set join in parent
            device_id=device_id,
        )

        # Set unique ID
        self._attr_unique_id = f"keypad_button_{join}"

        # Store join for sending commands
        self._join = join

        # Validate press duration
        self._press_duration = min(max(press_duration, MIN_PRESS_DURATION), MAX_PRESS_DURATION)
        
        # Since this is output only, we don't need to wait for first value
        self._got_first_value = True

        _LOGGER.debug(
            "Momentary button '%s' initialized with join d%s (output only, duration=%.3fs)",
            name,
            join,
            self._press_duration
        )

    async def async_press(self) -> None:
        """Press the button."""
        try:
            if not self.available:
                raise HomeAssistantError(f"Cannot press {self.name} - not available")

            # Send press (True)
            await self._server.set_digital(self._join, True)
            
            # Wait for duration
            await asyncio.sleep(self._press_duration)
            
            # Send release (False)
            await self._server.set_digital(self._join, False)
            
            _LOGGER.debug(
                "%s: Press completed (duration=%.3fs)",
                self.name,
                self._press_duration
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error pressing %s: %s",
                self.name,
                err
            )
            raise HomeAssistantError(f"Failed to press {self.name}: {err}") from err

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron buttons."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        # Get configured entities from options
        entity_configs = entry.options.get("entities", [])
        
        for entity_config in entity_configs:
            try:
                device_type = entity_config.get("device_type")
                
                # Skip if not a button
                if device_type != DEVICE_TYPE_MOMENTARY:
                    continue

                # Create button entity
                entity = CrestronMomentaryButton(
                    name=entity_config.get("name", ""),
                    server=server,
                    join=entity_config.get("momentary_join"),
                    device_id=entity_config.get("device_id"),
                )
                entities.append(entity)
                
            except Exception as err:
                _LOGGER.error(
                    "Error setting up button entity %s: %s",
                    entity_config.get("name", "unknown"),
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            
    except Exception as err:
        _LOGGER.error("Error setting up button platform: %s", err)
        raise HomeAssistantError(f"Button platform setup failed: {err}") from err