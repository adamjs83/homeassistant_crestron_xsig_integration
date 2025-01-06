"""Support for Crestron thermostats."""
from __future__ import annotations

import logging
from typing import Any, Final
import asyncio
from enum import IntEnum
from datetime import datetime, timedelta

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_TENTHS,
    UnitOfTemperature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .entity import CrestronEntity
from .const import (
    DOMAIN,
    DEVICE_TYPE_THERMOSTAT,
    MAX_ANALOG_JOIN,
    ERROR_INVALID_JOIN,
    JOIN_TYPE_ANALOG,
)

_LOGGER = logging.getLogger(__name__)

# Constants for state validation
MIN_TEMP: Final = 10.0
MAX_TEMP: Final = 32.0
TEMP_STEP: Final = 0.5
MAX_RETRY_ATTEMPTS: Final = 3
COMMAND_TIMEOUT: Final = 5.0
MODE_UPDATE_DELAY: Final = 0.5
STATE_TIMEOUT: Final = 300  # 5 minutes
UPDATE_INTERVAL: Final = 60  # 1 minute

# HVAC mode mapping
class HVACModeValue(IntEnum):
    """HVAC mode values for Crestron."""
    OFF = 0
    HEAT = 1
    COOL = 2
    AUTO = 3

MODE_TO_CRESTRON = {
    HVACMode.OFF: HVACModeValue.OFF,
    HVACMode.HEAT: HVACModeValue.HEAT,
    HVACMode.COOL: HVACModeValue.COOL,
    HVACMode.AUTO: HVACModeValue.AUTO,
}

CRESTRON_TO_MODE = {
    HVACModeValue.OFF: HVACMode.OFF,
    HVACModeValue.HEAT: HVACMode.HEAT,
    HVACModeValue.COOL: HVACMode.COOL,
    HVACModeValue.AUTO: HVACMode.AUTO,
}

class CrestronThermostat(CrestronEntity[float], ClimateEntity):
    """Representation of a Crestron thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    )
    _attr_precision = PRECISION_TENTHS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _attr_has_entity_name = True

    def __init__(
        self,
        name: str,
        server,
        current_temp_join: int,
        mode_join: int,
        heat_sp_join: int,
        cool_sp_join: int,
        device_id: str | None = None,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(
            name=name,
            server=server,
            join_type=JOIN_TYPE_ANALOG,
            join=current_temp_join,
            device_id=device_id,
        )

        # Set unique ID
        self._attr_unique_id = f"{server.entry_id}_thermostat_{current_temp_join}"

        # Store join numbers
        self._current_temp_join = current_temp_join
        self._mode_join = mode_join
        self._heat_sp_join = heat_sp_join
        self._cool_sp_join = cool_sp_join

        # Store formatted join IDs for callbacks
        self._current_temp_join_id = f"a{self._current_temp_join}"
        self._mode_join_id = f"a{self._mode_join}"
        self._heat_sp_join_id = f"a{self._heat_sp_join}"
        self._cool_sp_join_id = f"a{self._cool_sp_join}"

        # Initialize state attributes
        self._attr_current_temperature = None
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = None
        self._attr_target_temperature_high = None
        self._attr_target_temperature_low = None
        self._attr_hvac_action = None

        # State tracking
        self._mode_lock = asyncio.Lock()
        self._update_task = None
        self._command_queue = asyncio.Queue()
        self._command_task = None

        _LOGGER.debug(
            "Thermostat '%s' initialized with joins: current_temp=a%s, mode=a%s, heat_sp=a%s, cool_sp=a%s",
            name,
            current_temp_join,
            mode_join,
            heat_sp_join,
            cool_sp_join,
        )

    async def _platform_added_to_hass(self) -> None:
        """Platform-specific initialization."""
        try:
            # Register additional callbacks
            for join_id, handler in [
                (self._mode_join_id, self._handle_mode_update),
                (self._heat_sp_join_id, self._handle_heat_sp_update),
                (self._cool_sp_join_id, self._handle_cool_sp_update),
            ]:
                self.register_callback(join_id, handler)
            
            # Start tasks
            self._command_task = asyncio.create_task(self._process_command_queue())
            self._update_task = asyncio.create_task(self._update_loop())
            
        except Exception as err:
            _LOGGER.error(
                "Error setting up thermostat %s: %s",
                self.name,
                err
            )

    async def _platform_will_remove_from_hass(self) -> None:
        """Platform-specific cleanup."""
        try:
            # Cancel tasks
            if self._command_task and not self._command_task.done():
                self._command_task.cancel()
                try:
                    await self._command_task
                except asyncio.CancelledError:
                    pass
                    
            if self._update_task and not self._update_task.done():
                self._update_task.cancel()
                try:
                    await self._update_task
                except asyncio.CancelledError:
                    pass
                    
        except Exception as err:
            _LOGGER.error(
                "Error cleaning up %s: %s",
                self.name,
                err
            )

    async def _request_initial_state(self) -> None:
        """Request initial state from server."""
        try:
            # Request all states
            await self._server.get_analog(self._current_temp_join)
            await self._server.get_analog(self._mode_join)
            await self._server.get_analog(self._heat_sp_join)
            await self._server.get_analog(self._cool_sp_join)
            
        except Exception as err:
            _LOGGER.error(
                "Error requesting initial state for %s: %s",
                self.name,
                err
            )
            raise

    def _update_state(self, value: float) -> None:
        """Handle current temperature updates."""
        try:
            # Update current temperature
            self._attr_current_temperature = round(value, 1)
            
            # Update HVAC action based on current temperature and setpoints
            self._update_hvac_action()
            
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error handling temperature update for %s: %s",
                self.name,
                err
            )

    @callback
    def _handle_mode_update(self, value: float) -> None:
        """Handle HVAC mode updates."""
        try:
            # Convert mode value
            mode_value = HVACModeValue(int(value))
            new_mode = CRESTRON_TO_MODE.get(mode_value, HVACMode.OFF)
            
            # Update mode
            self._attr_hvac_mode = new_mode
            
            # Update HVAC action
            self._update_hvac_action()
            
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error handling mode update for %s: %s",
                self.name,
                err
            )

    @callback
    def _handle_heat_sp_update(self, value: float) -> None:
        """Handle heating setpoint updates."""
        try:
            # Update heating setpoint
            self._attr_target_temperature_low = round(value, 1)
            
            # Update target temperature if in heat mode
            if self._attr_hvac_mode == HVACMode.HEAT:
                self._attr_target_temperature = self._attr_target_temperature_low
                
            # Update HVAC action
            self._update_hvac_action()
            
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error handling heat setpoint update for %s: %s",
                self.name,
                err
            )

    @callback
    def _handle_cool_sp_update(self, value: float) -> None:
        """Handle cooling setpoint updates."""
        try:
            # Update cooling setpoint
            self._attr_target_temperature_high = round(value, 1)
            
            # Update target temperature if in cool mode
            if self._attr_hvac_mode == HVACMode.COOL:
                self._attr_target_temperature = self._attr_target_temperature_high
                
            # Update HVAC action
            self._update_hvac_action()
            
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error handling cool setpoint update for %s: %s",
                self.name,
                err
            )

    def _update_hvac_action(self) -> None:
        """Update HVAC action based on current state."""
        try:
            if self._attr_hvac_mode == HVACMode.OFF:
                self._attr_hvac_action = HVACAction.OFF
                return
                
            if self._attr_current_temperature is None:
                self._attr_hvac_action = None
                return
                
            if self._attr_hvac_mode == HVACMode.HEAT:
                if self._attr_target_temperature_low is None:
                    self._attr_hvac_action = None
                elif self._attr_current_temperature < self._attr_target_temperature_low:
                    self._attr_hvac_action = HVACAction.HEATING
                else:
                    self._attr_hvac_action = HVACAction.IDLE
                    
            elif self._attr_hvac_mode == HVACMode.COOL:
                if self._attr_target_temperature_high is None:
                    self._attr_hvac_action = None
                elif self._attr_current_temperature > self._attr_target_temperature_high:
                    self._attr_hvac_action = HVACAction.COOLING
                else:
                    self._attr_hvac_action = HVACAction.IDLE
                    
            elif self._attr_hvac_mode == HVACMode.AUTO:
                if (
                    self._attr_target_temperature_low is None or
                    self._attr_target_temperature_high is None
                ):
                    self._attr_hvac_action = None
                elif self._attr_current_temperature < self._attr_target_temperature_low:
                    self._attr_hvac_action = HVACAction.HEATING
                elif self._attr_current_temperature > self._attr_target_temperature_high:
                    self._attr_hvac_action = HVACAction.COOLING
                else:
                    self._attr_hvac_action = HVACAction.IDLE
                    
        except Exception as err:
            _LOGGER.error(
                "Error updating HVAC action for %s: %s",
                self.name,
                err
            )

    async def _process_command_queue(self) -> None:
        """Process commands from the queue."""
        try:
            while True:
                command = await self._command_queue.get()
                try:
                    await command()
                except Exception as err:
                    _LOGGER.error(
                        "Error processing command for %s: %s",
                        self.name,
                        err
                    )
                finally:
                    self._command_queue.task_done()
                    
        except asyncio.CancelledError:
            _LOGGER.debug("Command queue processor cancelled for %s", self.name)
            raise

    async def _update_loop(self) -> None:
        """Periodically update state."""
        try:
            while True:
                try:
                    await self._request_initial_state()
                except Exception as err:
                    _LOGGER.error(
                        "Error updating state for %s: %s",
                        self.name,
                        err
                    )
                await asyncio.sleep(UPDATE_INTERVAL)
                
        except asyncio.CancelledError:
            _LOGGER.debug("Update loop cancelled for %s", self.name)
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        if not self.available:
            raise HomeAssistantError(f"Cannot set mode for {self.name} - not available")
            
        try:
            # Convert mode
            mode_value = MODE_TO_CRESTRON[hvac_mode]
            
            # Send command
            await self._server.set_analog(self._mode_join, mode_value)
            
            # Update state
            self._attr_hvac_mode = hvac_mode
            self._update_hvac_action()
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error setting mode for %s: %s",
                self.name,
                err
            )
            raise HomeAssistantError(f"Failed to set mode for {self.name}: {err}") from err

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if not self.available:
            raise HomeAssistantError(f"Cannot set temperature for {self.name} - not available")
            
        try:
            if ATTR_TEMPERATURE in kwargs:
                temperature = kwargs[ATTR_TEMPERATURE]
                if self._attr_hvac_mode == HVACMode.HEAT:
                    await self._server.set_analog(self._heat_sp_join, temperature)
                    self._attr_target_temperature = temperature
                    self._attr_target_temperature_low = temperature
                elif self._attr_hvac_mode == HVACMode.COOL:
                    await self._server.set_analog(self._cool_sp_join, temperature)
                    self._attr_target_temperature = temperature
                    self._attr_target_temperature_high = temperature
            else:
                if "target_temp_low" in kwargs:
                    temperature = kwargs["target_temp_low"]
                    await self._server.set_analog(self._heat_sp_join, temperature)
                    self._attr_target_temperature_low = temperature
                if "target_temp_high" in kwargs:
                    temperature = kwargs["target_temp_high"]
                    await self._server.set_analog(self._cool_sp_join, temperature)
                    self._attr_target_temperature_high = temperature
                    
            self._update_hvac_action()
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error setting temperature for %s: %s",
                self.name,
                err
            )
            raise HomeAssistantError(f"Failed to set temperature for {self.name}: {err}") from err

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron thermostats."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        # Get configured entities from options
        entity_configs = entry.options.get("entities", [])
        for entity_config in entity_configs:
            try:
                if entity_config.get("device_type") != DEVICE_TYPE_THERMOSTAT:
                    continue

                name = entity_config.get("name", "")
                current_temp_join = entity_config.get("current_temp_join")
                mode_join = entity_config.get("mode_join")
                heat_sp_join = entity_config.get("heat_sp_join")
                cool_sp_join = entity_config.get("cool_sp_join")
                device_id = entity_config.get("device_id")

                if not name or not all([current_temp_join, mode_join, heat_sp_join, cool_sp_join]):
                    _LOGGER.warning(
                        "Skipping thermostat entity with missing required config: %s",
                        entity_config
                    )
                    continue

                # Validate join numbers
                for join in (current_temp_join, mode_join, heat_sp_join, cool_sp_join):
                    if not 0 < join <= MAX_ANALOG_JOIN:
                        raise ValueError(f"{ERROR_INVALID_JOIN}: {join}")

                entity = CrestronThermostat(
                    name=name,
                    server=server,
                    current_temp_join=current_temp_join,
                    mode_join=mode_join,
                    heat_sp_join=heat_sp_join,
                    cool_sp_join=cool_sp_join,
                    device_id=device_id,
                )
                entities.append(entity)
                
                _LOGGER.debug(
                    "Added thermostat entity: %s (current_temp=%s, mode=%s, heat_sp=%s, cool_sp=%s)",
                    name,
                    current_temp_join,
                    mode_join,
                    heat_sp_join,
                    cool_sp_join,
                )
                
            except Exception as err:
                _LOGGER.error(
                    "Error setting up thermostat entity %s: %s",
                    entity_config.get("name", "unknown"),
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            
    except Exception as err:
        _LOGGER.error("Error setting up climate platform: %s", err, exc_info=True)
        raise HomeAssistantError(f"Climate platform setup failed: {err}") from err