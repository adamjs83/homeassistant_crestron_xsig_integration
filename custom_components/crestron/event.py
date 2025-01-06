"""Event handlers for the Crestron integration."""
from __future__ import annotations

import logging
from typing import Any
import time

from homeassistant.components.event import (
    EventEntity,
    EventDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_NAME,
    CONF_ID,
    CONF_UNIQUE_ID,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DEVICE_TYPE_BUTTON_EVENT,
    JOIN_TYPE_DIGITAL,
)
from .entity import CrestronEntity

_LOGGER = logging.getLogger(__name__)

class CrestronEventEntity(CrestronEntity[bool], EventEntity):
    """Representation of a Crestron event entity."""

    _attr_has_entity_name = True
    _attr_event_types = ["press", "release"]
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(
        self,
        name: str,
        server: Any,
        join: int,
        device_id: str | None = None,
    ) -> None:
        """Initialize the event entity."""
        super().__init__(
            name=name,
            server=server,
            join_type=JOIN_TYPE_DIGITAL,
            join=join,
            device_id=device_id,
        )

        # Set unique ID
        self._attr_unique_id = f"{server.entry_id}_event_{join}"
        
        # Initialize state
        self._previous_value = False

        _LOGGER.debug(
            "Event entity '%s' initialized with join d%s",
            name,
            join
        )

    @callback
    def _handle_update(self, value: str) -> None:
        """Handle updates from server."""
        try:
            value_bool = value == "1"
            
            # Only process if value actually changed
            if value_bool == self._previous_value:
                return
                
            # Update state
            self._previous_value = value_bool
            
            # Determine event type
            event_type = "press" if value_bool else "release"
            
            # Prepare event data for EventEntity
            event_data = {
                "device_id": self._device_id,
                "type": event_type,
                "event_type": event_type,
                "name": self.name,
                "message": f"Button {event_type}",
                "entity_id": self.entity_id
            }

            # Track event in EventEntity
            self._attr_event = {
                "event_type": event_type,
                "data": event_data
            }

            # Fire EventEntity event
            self._trigger_event(event_type, event_data)
            
            # Fire domain event with different structure
            domain_event_data = {
                "device_id": self._device_id,
                "type": event_type,
                "action": f"Button {event_type}",  # This is what logbook uses for domain events
                "entity_id": self.entity_id,
                "event_type": event_type,
                "name": self.name,
            }
            self.hass.bus.async_fire(f"{DOMAIN}_event", domain_event_data)
            
            # Log the event
            _LOGGER.debug(
                "%s: Triggered %s event with data: %s",
                self.name,
                event_type,
                event_data
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "join_type": self._join_type,
            "join_number": self._join,
            "previous_state": "pressed" if self._previous_value else "released"
        }
        
        return attributes

    async def async_will_remove_from_hass(self) -> None:
        """Handle removal from Home Assistant."""
        # Add cleanup code here if needed
        await super().async_will_remove_from_hass()

    async def _platform_will_remove_from_hass(self) -> None:
        """Handle platform-specific cleanup."""
        # Add any event-specific cleanup here
        await super()._platform_will_remove_from_hass()

    async def _restore_state(self, state) -> None:
        """Restore previous state."""
        await super()._restore_state(state)
        try:
            if state.attributes.get("last_event_type"):
                self._attr_event = {
                    "type": state.attributes["last_event_type"],
                    "data": state.attributes.get("last_event_data", {})
                }
        except Exception as err:
            _LOGGER.error(
                "Error restoring state for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    @property
    def name(self) -> str:
        """Return the name of the event entity."""
        return f"Button {self._attr_name}"

    @property
    def device_class(self) -> str:
        """Return the class of this device."""
        return EventDeviceClass.BUTTON

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron event entities."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        entity_configs = entry.options.get("entities", [])
        for entity_config in entity_configs:
            try:
                if entity_config.get("device_type") != DEVICE_TYPE_BUTTON_EVENT:
                    continue

                name = entity_config.get("name", "")
                join = entity_config.get("join")
                device_id = entity_config.get("device_id")

                if not name or join is None:
                    _LOGGER.warning(
                        "Skipping event entity with missing required config: %s",
                        entity_config
                    )
                    continue

                entity = CrestronEventEntity(
                    name=name,
                    server=server,
                    join=join,
                    device_id=device_id,
                )
                entities.append(entity)
                
                _LOGGER.debug(
                    "Added event entity: %s (join=%s)",
                    name,
                    join
                )
                
            except Exception as err:
                _LOGGER.error(
                    "Error setting up event entity %s: %s",
                    entity_config.get("name", "unknown"),
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            
    except Exception as err:
        _LOGGER.error("Error setting up event platform: %s", err, exc_info=True)
        raise HomeAssistantError(f"Event platform setup failed: {err}") from err