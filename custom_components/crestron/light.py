"""Support for Crestron lights."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    LightEntity,
    ColorMode,
    ATTR_BRIGHTNESS,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .const import (
    DOMAIN,
    DEVICE_TYPE_LIGHT,
    ERROR_INVALID_JOIN,
    MAX_ANALOG_JOIN,
)
from .entity import CrestronEntity, CrestronServer

_LOGGER = logging.getLogger(__name__)

# Crestron uses 0-65535 for analog values
BRIGHTNESS_RANGE = (0, 65535)

class CrestronLight(CrestronEntity[int], LightEntity):
    """Representation of a Crestron light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_has_entity_name = True

    def __init__(
        self,
        name: str,
        server: CrestronServer,
        join: int,
        device_id: str | None = None,
    ) -> None:
        """Initialize the light."""
        super().__init__(
            name=name,
            server=server,
            join_type="a",  # Analog join for dimming
            join=join,
            device_id=device_id,
        )
        
        # Set unique ID
        self._attr_unique_id = f"{server.entry_id}_light_{join}"
        
        # Initialize state - assume OFF initially
        self._attr_is_on = False
        self._attr_brightness = 0
        self._last_brightness = 0
        
        _LOGGER.debug(
            "Light '%s' initialized with join a%s",
            name,
            join
        )

    def _update_state(self, value: str | int) -> None:
        """Update state from join value."""
        try:
            # Convert value to integer
            value = int(value)
            brightness = round(ranged_value_to_percentage(BRIGHTNESS_RANGE, value) * 255 / 100)
            self._attr_brightness = brightness
            self._attr_is_on = brightness > 0
            
            # Log state update only if value changed
            if self._last_brightness != brightness:
                _LOGGER.debug(
                    "%s: Updated brightness to %s (from value %s)",
                    self.name,
                    brightness,
                    value
                )
            self._last_brightness = brightness
            
            # Write state if server is available
            if self._server.is_available():
                self.async_write_ha_state()
            
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error converting light value '%s' to integer: %s",
                value,
                err,
                exc_info=True
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            if ATTR_BRIGHTNESS in kwargs:
                # Convert HA brightness (0-255) to Crestron analog value
                brightness_pct = kwargs[ATTR_BRIGHTNESS] / 255 * 100
                value = round(percentage_to_ranged_value(BRIGHTNESS_RANGE, brightness_pct))
            else:
                # Default to full brightness
                value = BRIGHTNESS_RANGE[1]

            # Send command to Crestron
            await self._server.set_analog(self._join, value)
            
            # Update state
            self._attr_is_on = True
            self._attr_brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error turning on %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            # Send command to Crestron
            await self._server.set_analog(self._join, 0)
            
            # Update state
            self._attr_is_on = False
            self._attr_brightness = 0
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error turning off %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def _request_initial_state(self) -> None:
        """Request initial state from server."""
        try:
            if self._server.is_available():
                # Request analog value
                await self._server.get_analog(self._join)
                
                # If we haven't gotten a value yet, assume it's off (0)
                if not self._got_first_value:
                    _LOGGER.debug(
                        "%s: No initial value received, assuming off (0)",
                        self.name
                    )
                    self._update_state(0)
                
        except Exception as err:
            _LOGGER.error(
                "Error requesting initial state for %s: %s",
                self.name,
                err,
                exc_info=True
            )

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron light entities."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        # Get configured entities from options
        entity_configs = entry.options.get("entities", [])
        for entity_config in entity_configs:
            try:
                if entity_config.get("device_type") != DEVICE_TYPE_LIGHT:
                    continue

                name = entity_config.get("name", "")
                join = entity_config.get("brightness_join")  # Changed to match config flow
                device_id = entity_config.get("device_id")

                if not name or join is None:
                    _LOGGER.warning(
                        "Skipping light entity with missing required config: %s",
                        entity_config
                    )
                    continue

                # Validate join number
                if not 0 < join <= MAX_ANALOG_JOIN:
                    raise ValueError(f"{ERROR_INVALID_JOIN}: {join}")

                entity = CrestronLight(
                    name=name,
                    server=server,
                    join=join,
                    device_id=device_id,
                )
                entities.append(entity)
                
                _LOGGER.debug(
                    "Added light entity: %s (join=%s)",
                    name,
                    join
                )
                
            except Exception as err:
                _LOGGER.error(
                    "Error setting up light entity %s: %s",
                    entity_config.get("name", "unknown"),
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            
    except Exception as err:
        _LOGGER.error("Error setting up light platform: %s", err, exc_info=True)
        raise HomeAssistantError(f"Light platform setup failed: {err}") from err