# Octo Bed – Home Assistant integration

Control your **Octo Bed** (or compatible BLE bed remote) from Home Assistant using an **existing ESP32 Bluetooth Proxy** (or any HA Bluetooth adapter). No need to run a dedicated ESPHome device for the bed; this integration uses the same BLE protocol and works with your current Bluetooth Proxy.

## Requirements

- Home Assistant with **Bluetooth** support (native or via [ESP32 Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html))
- The bed’s BLE remote powered on and in range of the proxy (advertises as **RC2** by default)

## Installation

### Via HACS (recommended)

1. In HACS go to **Integrations** → **⋮** → **Custom repositories**
2. Add: `https://github.com/bramboe/octo-esp32`
3. Choose category **Integration**
4. Install **Octo Bed**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/octo_bed` folder into your HA `custom_components` directory
2. Restart Home Assistant
3. **Settings** → **Devices & Services** → **Add Integration** → search for **Octo Bed**

**If HACS reports "Failed to download zipball" (404):** HACS may be trying to download a specific commit as a branch. Use **Manual** install above, or in HACS open the integration → **⋮** → **Redownload** and ensure the default branch (e.g. `main`) is selected.

## Configuration

1. **Settings** → **Devices & Services** → **Add Integration** → **Octo Bed**
2. Enter:
   - **Device name**: BLE name of the remote (default: `RC2`)
   - **Device address (optional)**: MAC address if you want to lock to a specific remote (e.g. `AA:BB:CC:DD:EE:FF`)
   - **PIN**: 4-digit PIN used for keep-alive (default: `0000`)
   - **Head calibration (seconds)**: Time in seconds for head to move 0%→100% (default: 30)
   - **Feet calibration (seconds)**: Time in seconds for feet to move 0%→100% (default: 30)
3. If you leave **Device address** empty, the integration will discover the remote by name when it is in range.

After setup you get:

- **Covers**: Head, Feet, Both (position 0–100%, open/close/stop)
- **Light**: Bed light on/off
- **Switches**: Head Up, Head Down, Feet Up, Feet Down (hold to move, turn off to stop)
- **Buttons**: Stop All, Search for Device, Send Keep-Alive

## Options

From the integration’s **Configure** you can change:

- Head calibration (seconds)
- Feet calibration (seconds)

## Notes

- Position (head/feet 0–100%) is **estimated** from movement time; the remote does not report position. Run calibration (or set the durations in options) to match your bed.
- For best range and reliability, use an **ESP32 Bluetooth Proxy** close to the bed.
- If the remote is not found, use the **Search for Device** button and ensure the remote is on and near the proxy.

## Protocol

The integration talks to the bed remote over BLE (service `FFE0`, characteristic `FFE1`), using the same command set as the [Octo Bed ESPHome configuration](https://github.com/bramboe/octo-esp32). It is compatible with remotes that advertise as **RC2** (or the name you configure).

## License

MIT
