"""Support for Crestron binary sensors."""
from __future__ import annotations

import logging
from typing import Any, Final
import asyncio

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .entity import CrestronEntity
from .const import (
    DOMAIN,
    DEVICE_TYPE_SENSOR,
    SENSOR_TYPES,
    MAX_DIGITAL_JOIN,
    ERROR_INVALID_JOIN,
    JOIN_TYPE_DIGITAL,
)

_LOGGER = logging.getLogger(__name__)

# Constants for state validation
STATE_DEBOUNCE_DELAY: Final = 0.1  # Delay in seconds for state debounce
MAX_RETRY_ATTEMPTS: Final = 3      # Maximum number of retry attempts

class CrestronBinarySensor(CrestronEntity[bool], BinarySensorEntity):
    """Representation of a Crestron binary sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        name: str,
        server,
        join: int,
        device_class: BinarySensorDeviceClass | None,
        device_id: str | None = None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            name=name,
            server=server,
            join_type=JOIN_TYPE_DIGITAL,
            join=join,
            device_id=device_id,
        )
        
        # Set unique ID
        self._attr_unique_id = f"{server.entry_id}_sensor_{join}"
        
        # Set device class
        self._attr_device_class = device_class
        
        # Initialize state
        self._attr_is_on = False

        _LOGGER.debug(
            "Binary sensor '%s' initialized with join d%s",
            name,
            join
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        await super().async_added_to_hass()
        
        try:
            # Request initial state
            await self._request_initial_state()
            
        except Exception as err:
            _LOGGER.error(
                "Failed to request initial state for %s: %s",
                self.name,
                err
            )
            self._attr_available = False

    async def _request_initial_state(self) -> None:
        """Request initial state from server."""
        try:
            await self._server.get_digital(self._join)
        except Exception as err:
            _LOGGER.error(
                "Error requesting initial state for %s: %s",
                self.name,
                err
            )
            raise

    def _update_state(self, value: bool) -> None:
        """Update sensor state."""
        try:
            self._attr_is_on = value
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error handling state update for %s: %s",
                self.name,
                err
            )

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron binary sensors."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        # Get configured entities from options
        entity_configs = entry.options.get("entities", [])
        for entity_config in entity_configs:
            try:
                if entity_config.get("device_type") != DEVICE_TYPE_SENSOR:
                    continue

                name = entity_config.get("name", "")
                join = entity_config.get("join")
                device_id = entity_config.get("device_id")
                sensor_type = entity_config.get("sensor_type")

                if not name or join is None or not sensor_type:
                    _LOGGER.warning(
                        "Skipping sensor entity with missing required config: %s",
                        entity_config
                    )
                    continue

                # Validate join number
                if not 0 < join <= MAX_DIGITAL_JOIN:
                    raise ValueError(f"{ERROR_INVALID_JOIN}: {join}")

                entity = CrestronBinarySensor(
                    name=name,
                    server=server,
                    join=join,
                    device_class=SENSOR_TYPES.get(sensor_type),
                    device_id=device_id,
                )
                entities.append(entity)
                
                _LOGGER.debug(
                    "Added sensor entity: %s (join=%s, type=%s)",
                    name,
                    join,
                    sensor_type,
                )
                
            except Exception as err:
                _LOGGER.error(
                    "Error setting up sensor entity %s: %s",
                    entity_config.get("name", "unknown"),
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            
    except Exception as err:
        _LOGGER.error("Error setting up binary_sensor platform: %s", err, exc_info=True)
        raise HomeAssistantError(f"Binary sensor platform setup failed: {err}") from err