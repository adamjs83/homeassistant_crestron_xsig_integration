"""Schemas for the Crestron integration."""
import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.const import CONF_NAME

import logging

from .const import (
    MAX_ANALOG_JOIN,
    MAX_DIGITAL_JOIN,
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_SHADE,
    DEVICE_TYPE_THERMOSTAT,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_BUTTON_LED,
    DEVICE_TYPE_SWITCH,
    DEVICE_TYPE_MOMENTARY,
    SENSOR_TYPE_MOTION,
    SENSOR_TYPE_DOOR,
    SENSOR_TYPE_WINDOW,
    SENSOR_TYPE_OCCUPANCY,
    SENSOR_TYPE_PRESENCE,
    DEVICE_TYPE_BUTTON_EVENT,
    MODEL_CLW_DIMUEX_P,
    MIN_DIGITAL_JOIN,
    MIN_ANALOG_JOIN,
    ERROR_JOIN_OUT_OF_RANGE,
)

_LOGGER = logging.getLogger(__name__)

def get_schema_for_device_type(device_type: str) -> vol.Schema:
    """Get the schema for a device type."""
    if device_type == DEVICE_TYPE_LIGHT:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("brightness_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_ANALOG_JOIN, max=MAX_ANALOG_JOIN)
            ),
            vol.Required("device_type"): vol.In([DEVICE_TYPE_LIGHT]),
        })
    elif device_type == DEVICE_TYPE_SHADE:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("position_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_ANALOG_JOIN, max=MAX_ANALOG_JOIN)
            ),
            vol.Required("closed_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_DIGITAL_JOIN, max=MAX_DIGITAL_JOIN)
            ),
            vol.Required("device_type"): vol.In([DEVICE_TYPE_SHADE]),
        })
    elif device_type == DEVICE_TYPE_THERMOSTAT:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("current_temp_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_ANALOG_JOIN, max=MAX_ANALOG_JOIN)
            ),
            vol.Required("setpoint_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_ANALOG_JOIN, max=MAX_ANALOG_JOIN)
            ),
            vol.Required("mode_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_ANALOG_JOIN, max=MAX_ANALOG_JOIN)
            ),
            vol.Required("device_type"): vol.In([DEVICE_TYPE_THERMOSTAT]),
        })
    elif device_type == DEVICE_TYPE_SENSOR:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_DIGITAL_JOIN, max=MAX_DIGITAL_JOIN)
            ),
            vol.Required("sensor_type"): vol.In([
                SENSOR_TYPE_MOTION,
                SENSOR_TYPE_DOOR,
                SENSOR_TYPE_WINDOW,
                SENSOR_TYPE_OCCUPANCY,
                SENSOR_TYPE_PRESENCE,
            ]),
            vol.Required("device_type"): vol.In([DEVICE_TYPE_SENSOR]),
        })
    elif device_type == DEVICE_TYPE_BUTTON_EVENT:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_DIGITAL_JOIN, max=MAX_DIGITAL_JOIN)
            ),
            vol.Required("device_type"): vol.In([DEVICE_TYPE_BUTTON_EVENT]),
        })
    elif device_type == DEVICE_TYPE_BUTTON_LED:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_DIGITAL_JOIN, max=MAX_DIGITAL_JOIN)
            ),
            vol.Required("device_type"): vol.In([DEVICE_TYPE_BUTTON_LED]),
        })
    elif device_type == DEVICE_TYPE_SWITCH:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("switch_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_DIGITAL_JOIN, max=MAX_DIGITAL_JOIN)
            ),
            vol.Required("device_type"): vol.In([DEVICE_TYPE_SWITCH]),
        })
    elif device_type == DEVICE_TYPE_MOMENTARY:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("momentary_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_DIGITAL_JOIN, max=MAX_DIGITAL_JOIN)
            ),
            vol.Optional("press_duration", default=0.25): cv.positive_float,
            vol.Required("device_type"): vol.In([DEVICE_TYPE_MOMENTARY]),
        })
    elif device_type == MODEL_CLW_DIMUEX_P:
        return vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Required("button_1_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_DIGITAL_JOIN, max=MAX_DIGITAL_JOIN)
            ),
            vol.Optional("light_join"): vol.All(
                cv.positive_int,
                vol.Range(min=MIN_ANALOG_JOIN, max=MAX_ANALOG_JOIN)
            ),
            vol.Optional("auto_populate", default=0): vol.All(
                cv.positive_int,
                vol.Range(min=0, max=8)  # Maximum 8 buttons
            ),
            vol.Required("device_type"): vol.In([MODEL_CLW_DIMUEX_P]),
        })
    return None

# Schema map for device types
SCHEMA_MAP = {
    DEVICE_TYPE_LIGHT: get_schema_for_device_type(DEVICE_TYPE_LIGHT),
    DEVICE_TYPE_SHADE: get_schema_for_device_type(DEVICE_TYPE_SHADE),
    DEVICE_TYPE_THERMOSTAT: get_schema_for_device_type(DEVICE_TYPE_THERMOSTAT),
    DEVICE_TYPE_SENSOR: get_schema_for_device_type(DEVICE_TYPE_SENSOR),
    DEVICE_TYPE_BUTTON_EVENT: get_schema_for_device_type(DEVICE_TYPE_BUTTON_EVENT),
    DEVICE_TYPE_BUTTON_LED: get_schema_for_device_type(DEVICE_TYPE_BUTTON_LED),
    DEVICE_TYPE_SWITCH: get_schema_for_device_type(DEVICE_TYPE_SWITCH),
    DEVICE_TYPE_MOMENTARY: get_schema_for_device_type(DEVICE_TYPE_MOMENTARY),
    MODEL_CLW_DIMUEX_P: get_schema_for_device_type(MODEL_CLW_DIMUEX_P),
}

def validate_join_numbers(config):
    """Validate that join numbers are within valid ranges."""
    device_type = config.get("device_type")
    schema = SCHEMA_MAP.get(device_type)
    
    if not schema:
        raise vol.Invalid(f"Invalid device type: {device_type}")
        
    # Additional validation for shade joins
    if device_type == DEVICE_TYPE_SHADE:
        # Log the validation
        _LOGGER.debug("Validating shade configuration: %s", config)
        
        # Ensure required joins are present
        required_joins = ["position_join", "closed_join"]
        missing_joins = [j for j in required_joins if j not in config]
        if missing_joins:
            raise vol.Invalid(f"Shade must have {', '.join(missing_joins)} configured")
            
        # Validate join numbers
        position_join = config["position_join"]
        closed_join = config["closed_join"]
        
        if not (0 < position_join <= MAX_ANALOG_JOIN):
            raise vol.Invalid(f"Position join must be between 1 and {MAX_ANALOG_JOIN}")
            
        if not (0 < closed_join <= MAX_DIGITAL_JOIN):
            raise vol.Invalid(f"Closed join must be between 1 and {MAX_DIGITAL_JOIN}")
        
        # Log the final configuration
        _LOGGER.debug("Validated shade configuration: %s", config)
    
    # Additional validation for thermostat joins
    elif device_type == DEVICE_TYPE_THERMOSTAT:
        # Ensure required joins are present
        required_joins = ["current_temp_join", "setpoint_join", "mode_join"]
        missing_joins = [j for j in required_joins if j not in config]
        if missing_joins:
            raise vol.Invalid(f"Thermostat must have {', '.join(missing_joins)} configured")
            
        # Validate join numbers
        current_temp_join = config["current_temp_join"]
        setpoint_join = config["setpoint_join"]
        mode_join = config["mode_join"]
        
        if not (0 < current_temp_join <= MAX_ANALOG_JOIN):
            raise vol.Invalid(f"Current temp join must be between 1 and {MAX_ANALOG_JOIN}")
            
        if not (0 < setpoint_join <= MAX_ANALOG_JOIN):
            raise vol.Invalid(f"Setpoint join must be between 1 and {MAX_ANALOG_JOIN}")
            
        if not (0 < mode_join <= MAX_ANALOG_JOIN):
            raise vol.Invalid(f"Mode join must be between 1 and {MAX_ANALOG_JOIN}")
            
    # Additional validation for sensor joins
    elif device_type == DEVICE_TYPE_SENSOR:
        join = config.get("join")
        if not (0 < join <= MAX_DIGITAL_JOIN):
            raise vol.Invalid(f"Sensor join must be between 1 and {MAX_DIGITAL_JOIN}")
            
    # Additional validation for button event joins
    elif device_type == DEVICE_TYPE_BUTTON_EVENT:
        join = config.get("join")
        if not (0 < join <= MAX_DIGITAL_JOIN):
            raise vol.Invalid(f"Button event join must be between 1 and {MAX_DIGITAL_JOIN}")
            
    # Additional validation for CLW-DIMUEX-P joins
    elif device_type == MODEL_CLW_DIMUEX_P:
        button_1_join = config.get("button_1_join")
        if not (0 < button_1_join <= MAX_DIGITAL_JOIN):
            raise vol.Invalid(f"Button 1 join must be between 1 and {MAX_DIGITAL_JOIN}")
            
        if "light_join" in config:
            light_join = config["light_join"]
            if not (0 < light_join <= MAX_ANALOG_JOIN):
                raise vol.Invalid(f"Light join must be between 1 and {MAX_ANALOG_JOIN}")
                
        auto_populate = config.get("auto_populate", 0)
        if auto_populate > 0:
            # Check that all sequential joins are valid
            for i in range(2, auto_populate + 1):
                join = button_1_join + (i-1)
                if not (0 < join <= MAX_DIGITAL_JOIN):
                    raise vol.Invalid(
                        f"Auto-populated button {i} join {join} exceeds maximum of {MAX_DIGITAL_JOIN}"
                    )
    
    return schema(config)

# Configuration schema with join validation
CONFIG_SCHEMA = vol.Schema({
    vol.Required("device_type"): vol.In([
        DEVICE_TYPE_LIGHT,
        DEVICE_TYPE_SHADE,
        DEVICE_TYPE_THERMOSTAT,
        DEVICE_TYPE_SENSOR,
        DEVICE_TYPE_BUTTON_EVENT,
        DEVICE_TYPE_BUTTON_LED,
        DEVICE_TYPE_SWITCH,
        DEVICE_TYPE_MOMENTARY,
        MODEL_CLW_DIMUEX_P,
    ]),
    vol.Required(CONF_NAME): cv.string,
}, extra=vol.ALLOW_EXTRA)
