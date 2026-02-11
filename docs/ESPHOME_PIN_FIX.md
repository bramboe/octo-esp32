# ESPHome Octo Bed: "PIN incorrect" after disconnect/reboot

## Root cause

The bed often disconnects and reports "PIN incorrect" even when the PIN is correct because of **when** the PIN is used:

1. **Global `stored_pin`** has `initial_value: "0000"` and is **not** restored from flash.
2. **PIN text entity** (`device_pin`) has `restore_value: true`, so after a reboot it **does** restore your real PIN (e.g. `1234`) from flash.
3. **On boot**, the global is still `"0000"` until you change the PIN in the UI again (which triggers `on_value` and updates `stored_pin`).
4. The **keep-alive** script runs every 30s and sends whatever is in `stored_pin`. So after every reboot it sends **0000** until you re-enter the PIN, which makes the bed reject the connection.

So the PIN is correct in the UI, but the device is sending the wrong one from memory.

## Fix 1: Sync PIN from entity on boot

In your ESPHome YAML, under `esphome:` → `on_boot:` → `then:`, add a step that runs **after** the existing 2s delay and **syncs** `stored_pin` from the text entity. That way the first keep-alive after reboot uses your saved PIN.

**Add this block right after the existing `- delay: 2s` (and before the lambda that updates head/feet calibration seconds):**

```yaml
    # Sync PIN from restored entity so keep-alive sends the correct PIN after reboot
    - lambda: |-
        std::string raw = id(device_pin).state;
        std::string pin = "";
        for (size_t i = 0; i < raw.length() && pin.length() < 4; i++) {
          char c = raw[i];
          if (c >= '0' && c <= '9') pin += c;
        }
        while (pin.length() < 4) pin = "0" + pin;
        id(stored_pin) = pin;
        ESP_LOGI("boot", "PIN synced from entity: %s", id(stored_pin).c_str());
```

So the start of your `on_boot` section should look like:

```yaml
esphome:
  name: octo-bed
  friendly_name: Octo Bed
  min_version: 2024.11.0
  name_add_mac_suffix: false
  on_boot:
    priority: 600
    then:
      - delay: 2s
      # Sync PIN from restored entity so keep-alive sends the correct PIN after reboot
      - lambda: |-
          std::string raw = id(device_pin).state;
          std::string pin = "";
          for (size_t i = 0; i < raw.length() && pin.length() < 4; i++) {
            char c = raw[i];
            if (c >= '0' && c <= '9') pin += c;
          }
          while (pin.length() < 4) pin = "0" + pin;
          id(stored_pin) = pin;
          ESP_LOGI("boot", "PIN synced from entity: %s", id(stored_pin).c_str());
      - lambda: |-
          // Update text fields with current values
          char buffer[16];
          // ... rest of your existing on_boot lambdas ...
```

## Fix 2: Harden keep-alive PIN bytes

In the **keep_connection_alive** script, the PIN is sent as `pin[i] - '0'`. If any character is not a digit (e.g. space or typo), that can produce wrong bytes. Sanitize so only digits 0–9 are sent:

**Replace the existing keep-alive `value: !lambda |-` block** (the one that builds the vector with `pin[0] - '0'`, etc.) with:

```yaml
      - ble_client.ble_write:
          id: star2octo
          service_uuid: ffe0
          characteristic_uuid: ffe1
          value: !lambda |-
            std::string pin = id(stored_pin);
            while (pin.length() < 4) pin = "0" + pin;
            if (pin.length() > 4) pin = pin.substr(0, 4);
            uint8_t d0 = (pin[0] >= '0' && pin[0] <= '9') ? (pin[0] - '0') : 0;
            uint8_t d1 = (pin[1] >= '0' && pin[1] <= '9') ? (pin[1] - '0') : 0;
            uint8_t d2 = (pin[2] >= '0' && pin[2] <= '9') ? (pin[2] - '0') : 0;
            uint8_t d3 = (pin[3] >= '0' && pin[3] <= '9') ? (pin[3] - '0') : 0;
            return std::vector<uint8_t> {
              0x40, 0x20, 0x43, 0x00, 0x04, 0x00,
              d0, d1, d2, d3,
              0x40
            };
```

This matches the format used by the Octo Bed integration (`40 20 43 00 04 00` + 4 digit bytes + `40`) and avoids sending invalid bytes if the string ever contains non-digits.

## Summary

- **Fix 1** ensures that after every reboot, `stored_pin` is set from the restored PIN entity, so keep-alive sends the correct PIN.
- **Fix 2** ensures that only valid digit bytes (0–9) are sent, even if the stored string is ever invalid.

After applying both changes, reflash the ESP32 and the bed should stop reporting "PIN incorrect" after disconnects/reboots.
