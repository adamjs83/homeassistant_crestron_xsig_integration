"""Base class for Crestron entities."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Generic, TypeVar, Protocol, Callable
import time

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    JOIN_TYPE_DIGITAL,
    JOIN_TYPE_ANALOG,
    JOIN_TYPE_SERIAL,
    MANUFACTURER,
)

_LOGGER = logging.getLogger(__name__)

StateType = TypeVar("StateType", bool, int, float, str)

class CrestronServer(Protocol):
    """Protocol for Crestron server implementations."""
    
    @property
    def entry_id(self) -> str:
        """Return the config entry ID."""
        ...
    
    @property
    def version(self) -> str:
        """Return server version."""
        ...
    
    def is_available(self) -> bool:
        """Return if server is available."""
        ...
    
    async def set_digital(self, join: int, value: bool) -> None:
        """Set digital join value."""
        ...

    async def set_analog(self, join: int, value: int) -> None:
        """Set analog join value."""
        ...

    async def set_serial(self, join: int, value: str) -> None:
        """Set serial join value."""
        ...

    async def get_digital(self, join: int) -> None:
        """Request digital join value."""
        ...

    async def get_analog(self, join: int) -> None:
        """Request analog join value."""
        ...

    async def get_serial(self, join: int) -> None:
        """Request serial join value."""
        ...
    
    def register_callback(self, join_id: str, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Register callback for updates."""
        ...

class CrestronEntity(RestoreEntity, Generic[StateType]):
    """Base class for Crestron entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        name: str,
        server: CrestronServer,
        join_type: str,
        join: int | None,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        self._attr_name = name
        self._server = server
        self._join_type = join_type
        self._join = join
        self._device_id = device_id
        self._state_lock = asyncio.Lock()
        self._unregister_join = None
        self._unregister_available = None
        self._additional_unregister_callbacks = {}
        
        # Set device info if we have a device ID
        if device_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, device_id)},
                manufacturer=MANUFACTURER,
                name=name,
                via_device=(DOMAIN, server.entry_id),
                sw_version=server.version,
            )
            
        # Set unique ID
        if join is not None:
            self._attr_unique_id = f"{server.entry_id}_{join_type}{join}"
        elif device_id:
            self._attr_unique_id = f"{device_id}_{name}"
        else:
            self._attr_unique_id = f"{server.entry_id}_{name}"
        
        # Register join ID if we have one
        if self._join:
            self._join_id = f"{self._join_type}{self._join}"
        else:
            self._join_id = None

        # Make available immediately
        self._attr_available = True

        _LOGGER.debug(
            "Entity '%s' initialized with join %s%s",
            name,
            join_type,
            join
        )

    @callback
    def _handle_update(self, value: Any) -> None:
        """Handle updates from server."""
        try:
            # Since this is a callback, we can't use async with
            if self._state_lock.locked():
                return
                
            # Only process updates if server is available
            if not self._server.is_available():
                _LOGGER.debug(
                    "%s: Ignoring update while server unavailable: %s",
                    self.name,
                    value
                )
                return
                
            # Update state
            self._update_state(value)
            
            # Log state update
            _LOGGER.debug(
                "%s: State updated from join %s%s: %s",
                self.name,
                self._join_type,
                self._join,
                value
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error handling update for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    @callback
    def _handle_availability(self, value: str) -> None:
        """Handle availability updates."""
        try:
            _LOGGER.debug(
                "%s: Handling system event: %s",
                self.name,
                value
            )
            
            if value == "connected":
                self._attr_available = True
                self.async_write_ha_state()
            elif value == "disconnected":
                self._attr_available = False
                self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error handling availability for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        await super().async_added_to_hass()
        
        try:
            # Restore previous state if available
            if (last_state := await self.async_get_last_state()) is not None:
                await self._restore_state(last_state)
            
            # Register join callback if we have a join ID
            if self._join_id:
                self._unregister_join = self._server.register_callback(
                    self._join_id,
                    self._handle_update
                )
            
            # Register availability callback
            self._unregister_available = self._server.register_callback(
                "system",
                self._handle_availability
            )
            
            # Allow platform-specific initialization
            await self._platform_added_to_hass()
            
        except Exception as err:
            _LOGGER.error(
                "Error setting up %s: %s",
                self.name,
                err,
                exc_info=True
            )
            self._attr_available = False

    async def async_will_remove_from_hass(self) -> None:
        """Clean up callbacks."""
        await super().async_will_remove_from_hass()
        
        try:
            # Clean up join callback
            if self._unregister_join is not None:
                self._unregister_join()
                self._unregister_join = None
                
            # Clean up availability callback
            if self._unregister_available is not None:
                self._unregister_available()
                self._unregister_available = None
                
            # Clean up additional callbacks
            for unregister in self._additional_unregister_callbacks.values():
                if unregister is not None:
                    unregister()
            self._additional_unregister_callbacks.clear()
            
            # Allow platform-specific cleanup
            await self._platform_will_remove_from_hass()
            
        except Exception as err:
            _LOGGER.error(
                "Error cleaning up %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def _platform_added_to_hass(self) -> None:
        """Hook for platform-specific initialization.
        
        To be implemented by child classes if needed.
        """
        pass

    async def _platform_will_remove_from_hass(self) -> None:
        """Hook for platform-specific cleanup.
        
        To be implemented by child classes if needed.
        """
        pass

    def register_callback(self, join_id: str, callback_func) -> None:
        """Register additional callback with cleanup tracking."""
        unregister = self._server.register_callback(join_id, callback_func)
        if unregister:
            self._additional_unregister_callbacks[join_id] = unregister

    async def _restore_state(self, state) -> None:
        """Restore previous state."""
        try:
            _LOGGER.debug(
                "%s: Restoring state: %s",
                self.name,
                state.state
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error restoring state for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._attr_available

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return self._attr_device_info

    async def _request_initial_state(self) -> None:
        """Request initial state from server."""
        try:
            if self._join and self._server.is_available():
                if self._join_type == JOIN_TYPE_DIGITAL:
                    await self._server.get_digital(self._join)
                elif self._join_type == JOIN_TYPE_ANALOG:
                    await self._server.get_analog(self._join)
                elif self._join_type == JOIN_TYPE_SERIAL:
                    await self._server.get_serial(self._join)
        except Exception as err:
            _LOGGER.error(
                "Error requesting initial state for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._attr_name