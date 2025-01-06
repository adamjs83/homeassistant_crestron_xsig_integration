"""Support for Crestron shades."""
from __future__ import annotations

import logging
from typing import Any, Final
import asyncio
import time

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    CoverDeviceClass,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.event import async_call_later

from .entity import CrestronEntity
from .const import (
    DOMAIN,
    DEVICE_TYPE_SHADE,
    MAX_ANALOG_JOIN,
    MAX_DIGITAL_JOIN,
    ERROR_INVALID_JOIN,
)

_LOGGER = logging.getLogger(__name__)

# Constants for position conversion
MIN_POSITION: Final = 0
MAX_POSITION: Final = 65535

# Constants for movement detection
MOVEMENT_TIMEOUT: Final = 1.0  # Time without position change to consider stopped
MIN_POSITION_CHANGE: Final = 50  # Minimum position change to consider movement
DECELERATION_THRESHOLD: Final = 100  # Position change threshold to detect deceleration

class CrestronShade(CrestronEntity[int], CoverEntity):
    """Representation of a Crestron shade."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN |
        CoverEntityFeature.CLOSE |
        CoverEntityFeature.STOP |
        CoverEntityFeature.SET_POSITION
    )
    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.SHADE

    def __init__(
        self,
        name: str,
        server,
        position_join: int,    # a2 - position set/feedback
        closed_join: int,      # d2 - closed feedback
        stop_join: int | None = None,  # d6 - stop command (optional)
        device_id: str | None = None,
    ) -> None:
        """Initialize the shade."""
        super().__init__(
            name=name,
            server=server,
            join_type="a",  # Use analog join for primary state
            join=position_join,
            device_id=device_id,
        )

        # Set unique ID based on position join
        self._attr_unique_id = f"{server.entry_id}_shade_{position_join}"

        # Store joins
        self._position_join = position_join  # a2 - position set/feedback
        self._closed_join = closed_join      # d2 - closed feedback
        self._stop_join = stop_join if stop_join is not None else closed_join  # Use closed_join as fallback

        # Store formatted join IDs for callbacks
        self._position_join_id = f"a{self._position_join}"
        self._closed_join_id = f"d{self._closed_join}"

        # Initialize state attributes
        self._attr_current_cover_position = 0  # Current position (0-100)
        self._attr_is_closed = True
        self._attr_is_closing = False
        self._attr_is_opening = False
        self._last_position = None
        self._last_update_time = None
        self._movement_cancel = None
        self._last_movement_speed = 0
        self._stop_requested = False
        self._movement_start_time = None

        _LOGGER.debug(
            "Shade '%s' initialized with joins: position=%s, closed=%s, stop=%s",
            name,
            position_join,
            closed_join,
            self._stop_join
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        await super().async_added_to_hass()
        try:
            # Register callbacks for position and closed state
            self.register_callback(self._position_join_id, self._update_position)
            self.register_callback(self._closed_join_id, self._update_closed)
            
        except Exception as err:
            _LOGGER.warning(
                "Failed to register callbacks for %s: %s",
                self.name,
                err
            )

    def _cancel_movement_timeout(self):
        """Cancel the movement timeout if it exists."""
        if self._movement_cancel is not None:
            self._movement_cancel()
            self._movement_cancel = None

    @callback
    def _schedule_movement_timeout(self):
        """Schedule movement timeout check using HA's async scheduler."""
        self._cancel_movement_timeout()
        self._movement_cancel = async_call_later(
            self.hass,
            MOVEMENT_TIMEOUT,
            self._handle_movement_timeout
        )

    @callback
    async def _handle_movement_timeout(self, _now=None):
        """Handle movement timeout - called when no position updates received."""
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._movement_cancel = None
        self._stop_requested = False
        self._movement_start_time = None
        self._last_movement_speed = 0
        self.async_write_ha_state()
        _LOGGER.debug("%s: Movement timeout - position stable", self.name)

    @callback
    def _update_position(self, value: str) -> None:
        """Handle position updates."""
        try:
            now = time.time()
            position = int(value)
            
            # Calculate position change and speed
            if self._last_position is not None and self._last_update_time is not None:
                position_change = position - self._last_position
                time_diff = now - self._last_update_time
                if time_diff > 0:
                    current_speed = abs(position_change / time_diff)
                    
                    # Detect start of movement
                    if not self._attr_is_opening and not self._attr_is_closing and abs(position_change) > MIN_POSITION_CHANGE:
                        self._movement_start_time = now
                        if position_change > 0:
                            self._attr_is_opening = True
                            self._attr_is_closing = False
                        else:
                            self._attr_is_opening = False
                            self._attr_is_closing = True
                    
                    # Detect deceleration after stop request
                    if self._stop_requested and self._last_movement_speed > 0:
                        speed_change = current_speed - self._last_movement_speed
                        if speed_change < -DECELERATION_THRESHOLD:
                            _LOGGER.debug(
                                "%s: Detected deceleration after stop (speed: %.2f -> %.2f)",
                                self.name,
                                self._last_movement_speed,
                                current_speed
                            )
                    
                    self._last_movement_speed = current_speed
                    
                    # Schedule movement timeout
                    if abs(position_change) > MIN_POSITION_CHANGE:
                        self._schedule_movement_timeout()
            
            # Store position and time
            self._last_position = position
            self._last_update_time = now
            
            # Convert to 0-100 scale for HA
            new_position = round((position / MAX_POSITION) * 100)
            if new_position != self._attr_current_cover_position:
                self._attr_current_cover_position = new_position
                self.async_write_ha_state()
            
            _LOGGER.debug(
                "%s: Position update - %d%% (%d) %s speed=%.2f", 
                self.name,
                self._attr_current_cover_position,
                position,
                "opening" if self._attr_is_opening else "closing" if self._attr_is_closing else "stopped",
                self._last_movement_speed
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error handling position update for %s: %s",
                self.name,
                err
            )

    @callback
    def _update_closed(self, value: str) -> None:
        """Handle closed state updates."""
        try:
            is_closed = bool(int(value))
            
            # Update closed state
            self._attr_is_closed = is_closed
            
            if is_closed:
                self._attr_is_opening = False
                self._attr_is_closing = False
                self._attr_current_cover_position = 0
                self._last_position = 0
                self._cancel_movement_timeout()
                self._stop_requested = False
                self._movement_start_time = None
                self._last_movement_speed = 0
            
            # Update HA state
            self.async_write_ha_state()
            
            _LOGGER.debug("%s: Closed state: %s", self.name, is_closed)
            
        except Exception as err:
            _LOGGER.error(
                "Error handling closed update for %s: %s",
                self.name,
                err
            )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        try:
            position = kwargs.get("position", 50)
            
            # Convert HA position (0-100) to Crestron position (0-65535)
            value = round((position / 100) * MAX_POSITION)
            
            # Reset stop flag when new position commanded
            self._stop_requested = False
            
            # Send command
            await self._server.set_analog(self._position_join, value)
            
        except Exception as err:
            _LOGGER.error("Error setting position: %s", err)
            raise HomeAssistantError(f"Failed to set position: {err}") from err

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        try:
            # Reset stop flag when opening
            self._stop_requested = False
            
            # Send max position command
            await self._server.set_analog(self._position_join, MAX_POSITION)
            
        except Exception as err:
            _LOGGER.error("Error opening %s: %s", self.name, err)
            raise HomeAssistantError(f"Failed to open cover: {err}") from err

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        try:
            # Reset stop flag when closing
            self._stop_requested = False
            
            # Send min position command
            await self._server.set_analog(self._position_join, MIN_POSITION)
            
        except Exception as err:
            _LOGGER.error("Error closing %s: %s", self.name, err)
            raise HomeAssistantError(f"Failed to close cover: {err}") from err

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        try:
            # Set stop flag before sending command
            self._stop_requested = True
            
            # Send stop pulse
            await self._server.set_digital(self._stop_join, True)
            await asyncio.sleep(0.1)
            await self._server.set_digital(self._stop_join, False)
            
            # Log stop request
            _LOGGER.debug(
                "%s: Stop requested at position %d%%",
                self.name,
                self._attr_current_cover_position
            )
            
        except Exception as err:
            _LOGGER.error("Error stopping %s: %s", self.name, err)
            raise HomeAssistantError(f"Failed to stop cover: {err}") from err

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron covers."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        # Get configured entities from options
        entity_configs = entry.options.get("entities", [])
        for entity_config in entity_configs:
            try:
                if entity_config.get("device_type") != DEVICE_TYPE_SHADE:
                    continue

                name = entity_config.get("name", "")
                position_join = entity_config.get("position_join")
                closed_join = entity_config.get("closed_join")
                stop_join = entity_config.get("stop_join")  # Now optional
                device_id = entity_config.get("device_id")

                if not name or position_join is None or closed_join is None:
                    _LOGGER.warning(
                        "Skipping shade with missing required config: %s",
                        entity_config
                    )
                    continue

                # Validate join numbers
                if not 0 < position_join <= MAX_ANALOG_JOIN:
                    raise ValueError(f"{ERROR_INVALID_JOIN} (position): {position_join}")
                if not 0 < closed_join <= MAX_DIGITAL_JOIN:
                    raise ValueError(f"{ERROR_INVALID_JOIN} (closed): {closed_join}")
                if stop_join is not None and not 0 < stop_join <= MAX_DIGITAL_JOIN:
                    raise ValueError(f"{ERROR_INVALID_JOIN} (stop): {stop_join}")

                entity = CrestronShade(
                    name=name,
                    server=server,
                    position_join=position_join,
                    closed_join=closed_join,
                    stop_join=stop_join,  # Will use closed_join as fallback if None
                    device_id=device_id,
                )
                entities.append(entity)
                
                _LOGGER.debug(
                    "Added shade entity: %s (position=%s, closed=%s, stop=%s)",
                    name,
                    position_join,
                    closed_join,
                    stop_join if stop_join is not None else closed_join
                )
                
            except Exception as err:
                _LOGGER.error(
                    "Error setting up shade %s: %s",
                    entity_config.get("name", "unknown"),
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            
    except Exception as err:
        _LOGGER.error("Error setting up covers: %s", err, exc_info=True)