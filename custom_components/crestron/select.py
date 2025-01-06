"""Support for Crestron LED binding selects."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import (
    STATE_ON,
    STATE_OFF,
)

from .const import (
    DOMAIN,
    BINDABLE_DOMAINS,
    BINDABLE_DEVICE_CLASSES,
    SELECT_OPTION_NONE,
    SELECT_NAME_SUFFIX,
    STATE_TO_LED,
    DEVICE_TYPE_BUTTON_LED,
)
from .entity import CrestronEntity

_LOGGER = logging.getLogger(__name__)

class CrestronLEDBindingSelect(CrestronEntity[str], SelectEntity):
    """Select entity for LED binding."""

    def __init__(
        self, 
        server, 
        led_entity_id: str, 
        led_unique_id: str,
        parent_device_id: str | None = None
    ) -> None:
        """Initialize the select entity."""
        # Extract base name from LED entity ID
        base_name = led_entity_id.split(".")[-1].replace("_led", "")
        name = f"{base_name} {SELECT_NAME_SUFFIX}"
        
        # Initialize parent with None for join since this entity doesn't use joins
        super().__init__(
            name=name,
            server=server,
            join_type=None,  # No join needed for binding select
            join=None,       # No join needed for binding select
            device_id=None   # Don't inherit device_id from LED entity
        )

        # Set unique ID based on LED entity
        self._attr_unique_id = f"{led_unique_id}_binding"
        
        # Store LED entity info
        self._led_entity_id = led_entity_id
        self._bound_entity_id: str | None = None
        self._cleanup_listener = None
        
        # Initialize options
        self._attr_options = [SELECT_OPTION_NONE]
        self._attr_current_option = SELECT_OPTION_NONE
        
        # Since this is a virtual entity, we don't need to wait for first value
        self._got_first_value = True

        _LOGGER.debug(
            "Created LED binding select '%s' for LED entity %s",
            self.name,
            led_entity_id
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        
        try:
            # Update available options
            self._update_options()
            
            # Restore previous binding if available
            if last_state := await self.async_get_last_state():
                if last_state.state != SELECT_OPTION_NONE:
                    self._attr_current_option = last_state.state
                    # Set up binding without triggering a state save
                    await self._setup_binding(last_state.state)
                    
            _LOGGER.debug(
                "LED binding '%s' restored state: %s",
                self.name,
                last_state.state if last_state else SELECT_OPTION_NONE
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error setting up LED binding %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def async_will_remove_from_hass(self) -> None:
        """Handle cleanup when entity is removed."""
        try:
            # Clean up all listeners
            if self._cleanup_listener is not None:
                self._cleanup_listener()
            self._cleanup_listener = None
            
            # Clear binding
            self._bound_entity_id = None
            
            await super().async_will_remove_from_hass()
            
        except Exception as err:
            _LOGGER.error(
                "Error cleaning up LED binding %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def _setup_binding(self, entity_id: str) -> None:
        """Set up binding to an entity."""
        try:
            # Clean up any existing binding
            await self._cleanup_binding()
            
            if entity_id != SELECT_OPTION_NONE:
                # Set up new binding
                self._bound_entity_id = entity_id
                self._cleanup_listener = async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._handle_bound_state_change
                )
                
                # Get initial state
                if state := self.hass.states.get(entity_id):
                    await self._update_led_state(state.state)
                    
        except Exception as err:
            _LOGGER.error(
                "Error setting up binding for %s to %s: %s",
                self.name,
                entity_id,
                err,
                exc_info=True
            )

    async def _cleanup_binding(self) -> None:
        """Clean up current binding."""
        try:
            # Clean up all listeners
            if self._cleanup_listener is not None:
                self._cleanup_listener()
            self._cleanup_listener = None
            
            self._bound_entity_id = None
            
        except Exception as err:
            _LOGGER.error(
                "Error cleaning up binding for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    @callback
    def _update_options(self) -> None:
        """Update the list of available options."""
        try:
            options = [SELECT_OPTION_NONE]
            
            # Get entity registry
            entity_registry = er.async_get(self.hass)
            
            # Add entities that can be bound
            for entity_id, entry in entity_registry.entities.items():
                # Skip if this is the LED entity itself or its binding
                if entity_id == self._led_entity_id or "led_binding" in entity_id:
                    continue
                    
                # Check if domain is bindable
                domain = entry.domain
                if domain not in BINDABLE_DOMAINS:
                    continue
                    
                # Skip disabled entities
                if entry.disabled:
                    continue

                # Add entity if it's in a bindable domain
                options.append(entity_id)
                _LOGGER.debug("Added bindable entity: %s (domain=%s)", entity_id, domain)
                    
            self._attr_options = sorted(options)
            self.async_write_ha_state()
            
            _LOGGER.debug(
                "Updated binding options for %s: %s",
                self.name,
                self._attr_options
            )
            
            # Log bindable entities by domain
            for domain in BINDABLE_DOMAINS:
                entities = [
                    entity_id for entity_id, entry in entity_registry.entities.items()
                    if entry.domain == domain and not entry.disabled
                ]
                if entities:
                    _LOGGER.debug("Found %s entities in domain %s: %s", len(entities), domain, entities)
            
        except Exception as err:
            _LOGGER.error(
                "Error updating options for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        try:
            await self._setup_binding(option)
            self._attr_current_option = option
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error(
                "Error selecting option for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    @callback
    async def _handle_bound_state_change(self, event) -> None:
        """Handle bound entity state changes."""
        try:
            if not self._bound_entity_id:
                return
            
            new_state = event.data.get("new_state")
            if not new_state:
                return
            
            # Get state mapping
            state = new_state.state
            should_be_on = STATE_TO_LED.get(state, False)
            
            # Update LED state
            await self.hass.services.async_call(
                "switch",
                "turn_on" if should_be_on else "turn_off",
                {"entity_id": self._led_entity_id},
                blocking=True
            )
            
            _LOGGER.debug(
                "LED binding '%s' updated LED to %s based on state '%s'",
                self.name,
                "on" if should_be_on else "off",
                state
            )
            
        except Exception as err:
            _LOGGER.error(
                "Error handling bound state change for %s: %s",
                self.name,
                err,
                exc_info=True
            )

    async def _update_led_state(self, state: str) -> None:
        """Update LED state based on bound entity state."""
        if not self._bound_entity_id:
            return
            
        # Get entity registry to check domain and device class
        entity_registry = er.async_get(self.hass)
        entry = entity_registry.async_get(self._bound_entity_id)
        if not entry:
            return
            
        # Get valid states based on domain and device class
        valid_states = []
        if entry.device_class and entry.device_class in BINDABLE_DEVICE_CLASSES:
            valid_states = BINDABLE_DEVICE_CLASSES[entry.device_class]
        elif entry.domain in BINDABLE_DOMAINS:
            valid_states = BINDABLE_DOMAINS[entry.domain]
            
        # Set LED state based on entity state
        if state in valid_states:
            # Turn LED on for active states
            if state in [STATE_ON, "open", "cleaning", "playing", "active", "home"]:
                await self.hass.services.async_call(
                    "switch",
                    "turn_on",
                    {"entity_id": self._led_entity_id},
                    blocking=True
                )
            else:
                await self.hass.services.async_call(
                    "switch",
                    "turn_off",
                    {"entity_id": self._led_entity_id},
                    blocking=True
                )

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron LED binding selects."""
    try:
        server = hass.data[DOMAIN]["server"]
        entities = []

        # Get entity registry
        entity_registry = er.async_get(hass)
        
        _LOGGER.debug("Searching for LED entities to create bindings for...")
        
        # First check if LED entities are configured
        led_configs = [
            config for config in entry.options.get("entities", [])
            if config.get("device_type") == DEVICE_TYPE_BUTTON_LED
        ]

        if not led_configs:
            _LOGGER.debug("No LED entities configured in options")
            return

        # Then check if they exist in registry
        for led_config in led_configs:
            try:
                name = led_config.get("name")
                join = led_config.get("join")
                
                if not name or join is None:
                    continue
                    
                # Generate expected unique_id for LED entity
                led_unique_id = f"{entry.entry_id}_led_{join}"
                binding_unique_id = f"{led_unique_id}_binding"
                
                # Check if binding already exists
                existing_binding = None
                for entity_id, entity in entity_registry.entities.items():
                    if entity.unique_id == binding_unique_id and entity.config_entry_id == entry.entry_id:
                        existing_binding = entity_id
                        break
                
                if existing_binding:
                    _LOGGER.debug(
                        "Found existing binding for LED %s: %s",
                        name,
                        existing_binding
                    )

                # Look for LED entity in registry
                led_entity_id = None
                for entity_id, entity in entity_registry.entities.items():
                    if (
                        entity.platform == DOMAIN and
                        entity.domain == "switch" and
                        entity.unique_id == led_unique_id
                    ):
                        led_entity_id = entity_id
                        break
                        
                if led_entity_id:
                    _LOGGER.debug(
                        "Found LED entity to bind: %s (name=%s)",
                        led_entity_id,
                        name
                    )
                    
                    select = CrestronLEDBindingSelect(
                        server,
                        led_entity_id,
                        led_unique_id
                    )
                    entities.append(select)
                    
                    _LOGGER.debug(
                        "Created binding select for LED: %s (unique_id=%s)",
                        led_entity_id,
                        binding_unique_id
                    )
                    
            except Exception as err:
                _LOGGER.error(
                    "Error creating binding select for LED %s: %s",
                    name,
                    err,
                    exc_info=True
                )

        if entities:
            async_add_entities(entities)
            _LOGGER.debug("Added %d LED binding selects", len(entities))
        else:
            _LOGGER.debug("No LED entities found to create bindings for")
            
        # Store cleanup function in hass.data
        if "cleanup_functions" not in hass.data[DOMAIN]:
            hass.data[DOMAIN]["cleanup_functions"] = []
            
        async def cleanup():
            """Clean up LED bindings."""
            entity_registry = er.async_get(hass)
            for entity_id, entity in entity_registry.entities.items():
                if (
                    entity.platform == DOMAIN and
                    entity.domain == "select" and
                    "led_binding" in entity_id
                ):
                    # Remove binding entity
                    entity_registry.async_remove(entity_id)
                    
        hass.data[DOMAIN]["cleanup_functions"].append(cleanup)

    except Exception as err:
        _LOGGER.error("Error setting up select platform: %s", err)
        raise HomeAssistantError(f"Select platform setup failed: {err}") from err