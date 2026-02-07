# Octo Bed – Home Assistant integration

Control your **Octo Bed** (or compatible BLE bed) from Home Assistant using an **ESP32 Bluetooth Proxy** (or any HA Bluetooth adapter). Same BLE protocol as the official app; no dedicated ESPHome device required.

## Requirements

- Home Assistant with **Bluetooth** (native or [ESP32 Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html))
- Bed base powered on and **in range of the proxy** (advertises as **RC2** by default)
- Your bed’s **4-digit PIN** (used to authenticate; tested during setup)

## Installation

### Via HACS (recommended)

1. **HACS** → **Integrations** → **⋮** → **Custom repositories** → add `https://github.com/bramboe/octo-esp32`
2. Category **Integration** → install **Octo Bed** → restart Home Assistant

### Manual

1. Copy `custom_components/octo_bed` into your HA `custom_components` folder
2. Restart Home Assistant → **Settings** → **Devices & Services** → **Add Integration** → **Octo Bed**

**HACS 404:** Use Manual install, or Redownload and select the default branch (e.g. `main`).

## Configuration

1. **Add Integration** → **Octo Bed** → choose **Search for beds** or **Enter details manually**.
2. **Search:** Pick the bed from the list (MAC shown to tell beds apart), then **Set PIN for bed** and enter your 4-digit PIN. The integration tests the connection before adding.
3. **Manual:** Enter the bed’s **BLE MAC address** (required), remote name (e.g. `RC2`), and **PIN**. Connection is tested before adding.
4. **Two beds:** Add the integration twice (or scan twice). Use each bed’s **MAC address** so each config is bound to the correct bed.

**Connection = authenticated:** The integration only treats the bed as “connected” when the correct PIN is accepted and commands work (not just “device in range”). If you see “PIN not accepted”, check the PIN and that you use the **bed base** MAC, not the remote’s.

After setup you get:

- **Covers**: Head, Feet, Both (0–100%, open/close/stop)
- **Light**: Bed light on/off (permanent duration, like the official app)
- **Switches**: Head Up/Down, Feet Up/Down (hold to move, turn off to stop)
- **Buttons**: Stop All, Calibrate Head/Feet, Calibration Stop, Reset BLE Connection
- **Sensors**: Connection status, MAC address, head/feet position

## Options

From the device’s **Configure** you can change:

- Head / feet calibration (seconds)
- Device nickname, MAC address, PIN

## Notes

- **Position** (head/feet 0–100%) is estimated from movement time; the remote does not report position. Use **Calibrate Head/Feet** (or set durations in options) to match your bed.
- **Range:** Place the Bluetooth proxy close to the bed. If the device is not found, use **Reset BLE Connection** and ensure the bed is on and in range.
- **Protocol:** BLE service `FFE0`, characteristic `FFE1`; same command set as the official app and the [Octo Bed ESPHome config](https://github.com/bramboe/octo-esp32).

## License

MIT
