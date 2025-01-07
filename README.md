PLEASE NOTE THE IS A BETA RELEASE

# Crestron XSIG Integration for Home Assistant

A full-featured Home Assistant integration for Crestron control systems that provides bidirectional communication and support for various device types through XSIG protocol.

## Features

- **Device Support**
  - Keypads (with dimming)(Tested with CLW-Dimuex)
  - Motorized Shades/Covers
  - Thermostats (including Horizon thermostats)(Still Testing)
  - Switches
  - Binary Sensors
  - Buttons (momentary and LED feedback)
  - Events (for button presses)
  - LED Binding

- **Core Functionality**
  - Bidirectional TCP communication
  - Join state tracking
  - Automatic reconnection
  - State persistence
  - Error recovery
  - Rate limiting

## Installation

1. Copy this repository into your Home Assistant `custom_components` directory:
   ```bash
   cd ~/.homeassistant/custom_components
   git clone [repository_url] crestron_xsig
   ```

2. Restart Home Assistant
3. Add the integration through the Home Assistant UI:
   - Go to Configuration -> Integrations
   - Click the "+ ADD INTEGRATION" button
   - Search for "Crestron XSIG"
   - Follow the configuration steps

## Configuration

The integration supports configuration through the Home Assistant UI. You'll need to provide:

- TCP Port number (default: 32768)

After initial setup, you can add devices through the integration's options:

1. Go to Configuration -> Integrations
2. Click "CONFIGURE" on the Crestron integration
3. Choose "Add Entity" or "Add Device"
4. Follow the configuration steps for your device type

## Supported Device Types

### Lights
- Supports on/off and dimming
- Uses analog joins for dimming (0-65535)
- Supports state feedback

### Shades/Covers
- Position control (0-100%)
- Open/Close/Stop commands
- Raise/Lower functionality
- Position feedback
- Movement state tracking

### Thermostats
- Multiple HVAC modes (Off, Heat, Cool, Auto)
- Temperature setpoints
- Current temperature feedback
- Fan control
- Humidity control (if available)
- Floor warming support (if available)

### Switches
- Simple on/off control
- State feedback
- LED binding capability

### Binary Sensors
- Motion detection
- Door/window status
- Occupancy sensing
- Presence detection

### Buttons
- Momentary press functionality
- Configurable press duration
- LED feedback support
- Event generation

### Events
- Button press detection
- Press types (single, double, triple)
- Hold detection
- Release events

## Services

The integration provides several services for direct join control:

### set_join
Set a join value directly:
```yaml
service: crestron_xsig.set_join
data:
  join_type: "d"  # d=digital, a=analog, s=serial
  join: 1
  value: true
```

### get_join
Request the current value of a join:
```yaml
service: crestron_xsig.get_join
data:
  join_type: "a"
  join: 1
```

### pulse_join
Momentarily activate a digital join:
```yaml
service: crestron_xsig.pulse_join
data:
  join: 1
  duration: 0.1
```

### sync_joins
Request updates for all or specific join types:
```yaml
service: crestron_xsig.sync_joins
data:
  join_types: ["d", "a", "s"]
```

## Join Number Limitations

- Digital Joins: 1-65535
- Analog Joins: 1-65535
- Serial Joins: 1-65535

## Error Handling

The integration includes comprehensive error handling for:
- Connection issues
- Invalid join numbers
- Configuration errors
- State validation
- Rate limiting

## Debugging

Enable debug logging by adding to your `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.crestron_xsig: debug
```

## Contributing

Contributions are welcome! Please read the contributing guidelines before submitting pull requests.

## License

[Add appropriate license information]

## Support

For issues and feature requests, please use the GitHub issue tracker. 
