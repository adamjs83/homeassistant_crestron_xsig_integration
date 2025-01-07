"""Constants for the Crestron XSIG integration."""
from typing import Final
from homeassistant.const import Platform
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_ON, STATE_OFF

DOMAIN: Final = "crestron_xsig"
MANUFACTURER: Final = "Crestron"

# Protocol Commands
CMD_CLEAR_OUTPUTS: Final = b"\xFC"  # Force all outputs to 0
CMD_GET_JOINS: Final = b"\xFD"      # Request all join states
CMD_UPDATE_REQUEST: Final = b"\xFD"  # Update all joins request

# Join Types
JOIN_TYPE_DIGITAL: Final = "d"  # Digital (boolean)
JOIN_TYPE_ANALOG: Final = "a"   # Analog (0-65535)
JOIN_TYPE_SERIAL: Final = "s"   # Serial (string)

JOIN_TYPE_OPTIONS = [
    JOIN_TYPE_DIGITAL,
    JOIN_TYPE_ANALOG,
    JOIN_TYPE_SERIAL,
]

# Join Limits
MIN_DIGITAL_JOIN: Final = 1
MIN_ANALOG_JOIN: Final = 1
MIN_SERIAL_JOIN: Final = 1
MAX_DIGITAL_JOIN: Final = 65535
MAX_ANALOG_JOIN: Final = 65535
MAX_SERIAL_JOIN: Final = 65535

# Configuration
CONF_PORT: Final = "port"
DEFAULT_PORT: Final = 32768

# Device Types
DEVICE_TYPE_LIGHT: Final = "light"
DEVICE_TYPE_SHADE: Final = "shade"
DEVICE_TYPE_THERMOSTAT: Final = "thermostat"
DEVICE_TYPE_BUTTON_EVENT: Final = "button_event"
DEVICE_TYPE_SENSOR: Final = "sensor"
DEVICE_TYPE_BUTTON_LED: Final = "button_led"
DEVICE_TYPE_SWITCH: Final = "switch"
DEVICE_TYPE_MOMENTARY: Final = "momentary"
DEVICE_TYPE_KEYPAD: Final = "keypad"
DEVICE_TYPE_CLW_DIMUEX: Final = "clw_dimuex"

DEVICE_TYPE_OPTIONS: Final = [
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_SHADE,
    DEVICE_TYPE_THERMOSTAT,
    DEVICE_TYPE_BUTTON_EVENT,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_BUTTON_LED,
    DEVICE_TYPE_SWITCH,
    DEVICE_TYPE_MOMENTARY,
    DEVICE_TYPE_CLW_DIMUEX,
]

# Platform Lists
PLATFORMS: Final = {
    DEVICE_TYPE_LIGHT: Platform.LIGHT,
    DEVICE_TYPE_SHADE: Platform.COVER,
    DEVICE_TYPE_THERMOSTAT: Platform.CLIMATE,
    DEVICE_TYPE_BUTTON_EVENT: Platform.EVENT,
    DEVICE_TYPE_SENSOR: Platform.BINARY_SENSOR,
    DEVICE_TYPE_BUTTON_LED: Platform.SWITCH,
    DEVICE_TYPE_SWITCH: Platform.SWITCH,
    DEVICE_TYPE_MOMENTARY: Platform.BUTTON,
    "select": Platform.SELECT,
}

# Configuration Keys
CONF_DEVICE_TYPE: Final = "device_type"
CONF_JOIN_TYPE: Final = "join_type"
CONF_JOIN: Final = "join"
CONF_DEVICE_ID: Final = "device_id"
CONF_ENTITIES: Final = "entities"
CONF_DEVICES: Final = "devices"
CONF_REMOVED_ENTITIES: Final = "removed_entities"
CONF_NAME: Final = "name"

# Shade Configuration
CONF_POSITION_JOIN: Final = "position_join"  # a2 - For position set/feedback
CONF_RAISE_JOIN: Final = "raise_join"        # d2 - For raise pulse out/is_raising state in
CONF_LOWER_JOIN: Final = "lower_join"        # d3 - For lower pulse out/is_lowering state in
CONF_OPEN_JOIN: Final = "open_join"          # d4 - For open pulse out/is_opened state in
CONF_CLOSE_JOIN: Final = "close_join"        # d5 - For close pulse out/is_closed state in
CONF_STOP_JOIN: Final = "stop_join"          # d6 - For stop pulse out/is_stopped state in

# Button Configuration
CONF_PRESS_JOIN: Final = "press_join"
CONF_LED_JOIN: Final = "led_join"

# Switch Configuration
CONF_SWITCH_JOIN: Final = "switch_join"
CONF_MOMENTARY_JOIN: Final = "momentary_join"

# Thermostat Configuration
CONF_SYSTEM_MODE_JOIN: Final = "system_mode_join"
CONF_SYSTEM_MODE_FB_JOIN: Final = "system_mode_fb_join"
CONF_FAN_MODE_JOIN: Final = "fan_mode_join"
CONF_FAN_MODE_FB_JOIN: Final = "fan_mode_fb_join"
CONF_HEAT_SP_JOIN: Final = "heat_sp_join"
CONF_HEAT_SP_FB_JOIN: Final = "heat_sp_fb_join"
CONF_COOL_SP_JOIN: Final = "cool_sp_join"
CONF_COOL_SP_FB_JOIN: Final = "cool_sp_fb_join"
CONF_CURRENT_TEMP_JOIN: Final = "current_temp_join"

# Server States
SERVER_STATE_CONNECTED: Final = "connected"
SERVER_STATE_DISCONNECTED: Final = "disconnected"

# Default Values
DEFAULT_BRIGHTNESS: Final = 255  # Full brightness
DEFAULT_TEMPERATURE: Final = 21  # 21°C
DEFAULT_UPDATE_INTERVAL: Final = 5  # 5 seconds

# Error Messages
ERROR_INVALID_JOIN: Final = "Invalid join number"
ERROR_JOIN_IN_USE: Final = "Join number already in use"
ERROR_JOIN_OUT_OF_RANGE: Final = "Join must be between {0} and {1}"
ERROR_INVALID_PORT: Final = "Invalid port number"
ERROR_PORT_IN_USE: Final = "Port already in use"
ERROR_NO_CONNECTION: Final = "No connection to Crestron system"
ERROR_INVALID_VALUE: Final = "Invalid value for join type"

# Sensor Types
SENSOR_TYPE_MOTION: Final = "motion"
SENSOR_TYPE_DOOR: Final = "door"
SENSOR_TYPE_WINDOW: Final = "window"
SENSOR_TYPE_OCCUPANCY: Final = "occupancy"
SENSOR_TYPE_PRESENCE: Final = "presence"  # Changed from CONTACT

SENSOR_TYPES = {
    SENSOR_TYPE_MOTION: BinarySensorDeviceClass.MOTION,
    SENSOR_TYPE_DOOR: BinarySensorDeviceClass.DOOR,
    SENSOR_TYPE_WINDOW: BinarySensorDeviceClass.WINDOW,
    SENSOR_TYPE_OCCUPANCY: BinarySensorDeviceClass.OCCUPANCY,
    SENSOR_TYPE_PRESENCE: BinarySensorDeviceClass.PRESENCE,  # Changed from CONTACT
}

# Select Entity Constants
SELECT_DOMAIN: Final = "select"
SELECT_OPTION_NONE: Final = "none"
SELECT_NAME_SUFFIX: Final = "LED Binding"

# LED Binding Constants
LED_BIND_UPDATE_DELAY: Final = 0.1  # Delay in seconds for LED state updates

# Device Models
MODEL_CLW_DIMUEX_P: Final = "CLW-DIMUEX-P"

# Device Metadata
DEVICE_METADATA = {
    MODEL_CLW_DIMUEX_P: {
        "name": "CLW-DIMUEX-P",
        "description": "Cameo Keypad with Dimmer",
        "max_buttons": 4,
        "has_dimmer": True,
    }
}

# Event Constants
EVENT_BUTTON_PRESS: Final = "crestron_button_event"
EVENT_BUTTON_RELEASE: Final = "button_release"  # Keep this for compatibility
EVENT_TYPES: Final = {
    "press": "pressed",
    "double_press": "double pressed",
    "triple_press": "triple pressed",
    "hold": "held",
    "release": "released"
}

# Event Timing Constants
EVENT_HOLD_DELAY: Final = 0.5  # Time in seconds to trigger hold
EVENT_DOUBLE_PRESS_DELAY: Final = 0.3  # Max time between presses for double press
EVENT_TRIPLE_PRESS_DELAY: Final = 0.3  # Max time between presses for triple press

# Domains that can be bound to LEDs
BINDABLE_DOMAINS = {
    "light": ["on", "off"],
    "switch": ["on", "off"],
    "binary_sensor": ["on", "off"],
    "cover": ["open", "closed", "opening", "closing"],
    "media_player": ["playing", "paused", "idle"],
    "climate": ["heat", "cool", "off"],
    "fan": ["on", "off"],
    "lock": ["locked", "unlocked"],
    "vacuum": ["cleaning", "docked"],
    "person": ["home", "not_home"],
    "device_tracker": ["home", "not_home"],
    "input_boolean": ["on", "off"],
}

# Device classes that can be bound to LEDs
BINDABLE_DEVICE_CLASSES = {
    "motion": ["on", "off"],
    "door": ["on", "off"],
    "window": ["on", "off"],
    "presence": ["on", "off"],
    "occupancy": ["on", "off"],
    "power": ["on", "off"],
    "plug": ["on", "off"],
    "light": ["on", "off"],
    "switch": ["on", "off"],
}

# State mappings for LED binding
STATE_TO_LED = {
    # Generic states
    "on": True,
    "off": False,
    
    # Cover states
    "open": True,
    "opening": True,
    "closed": False,
    "closing": False,
    
    # Lock states
    "locked": True,
    "unlocked": False,
    
    # Media player states
    "playing": True,
    "paused": False,
    "idle": False,
    
    # Presence states
    "home": True,
    "not_home": False,
    
    # Climate states
    "heat": True,
    "cool": True,
    "off": False,
    
    # Vacuum states
    "cleaning": True,
    "docked": False,
    
    # Binary sensor states
    "detected": True,
    "clear": False,
    "motion": True,
    "no_motion": False,
}

# State Management Constants
STATE_TIMEOUT: Final = 300  # 5 minutes
UPDATE_INTERVAL: Final = 60  # 1 minute
COMMAND_TIMEOUT: Final = 5.0  # 5 seconds
RETRY_DELAY: Final = 5.0  # 5 seconds
MAX_RETRY_ATTEMPTS: Final = 3  # Maximum number of retry attempts
MAX_QUEUE_SIZE: Final = 100  # Maximum command queue size

# Platform mapping
DEVICE_TYPE_TO_PLATFORM = {
    DEVICE_TYPE_LIGHT: Platform.LIGHT,
    DEVICE_TYPE_SHADE: Platform.COVER,
    DEVICE_TYPE_BUTTON_LED: Platform.SWITCH,
    DEVICE_TYPE_SWITCH: Platform.SWITCH,
    DEVICE_TYPE_MOMENTARY: Platform.BUTTON,
    DEVICE_TYPE_BUTTON_EVENT: Platform.EVENT,
    MODEL_CLW_DIMUEX_P: Platform.LIGHT,  # Primary platform for the device
}

