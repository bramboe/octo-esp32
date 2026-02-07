#!/usr/bin/env python3
"""
Test Octo Bed BLE PIN behaviour from your Mac (no Home Assistant).
Run: pip install bleak && python test_octo_ble_pin.py

Uses the same protocol as the integration: connect, send keep-alive with PIN,
wait; wrong PIN should cause disconnect, correct PIN should keep connection.
"""

import asyncio
import sys

# Protocol constants (must match custom_components/octo_bed/const.py)
BLE_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
KEEP_ALIVE_PREFIX = bytes([0x40, 0x20, 0x43, 0x00, 0x04, 0x00])
KEEP_ALIVE_SUFFIX = bytes([0x40])
CMD_STOP = bytes([0x40, 0x02, 0x73, 0x00, 0x00, 0x0B, 0x40])

WRONG_PIN = "9999"
WAIT_AFTER_KEEPALIVE = 5.0
CONNECT_TIMEOUT = 15.0


def make_keep_alive(pin: str) -> bytes:
    pin = (pin or "0000").strip()[:4].ljust(4, "0")
    digits = bytes([ord(c) - ord("0") for c in pin])
    return KEEP_ALIVE_PREFIX + digits + KEEP_ALIVE_SUFFIX


async def test_wrong_pin(address: str) -> tuple[bool, bool]:
    """(validates_pin, connected). If not connected, validates_pin is meaningless."""
    try:
        from bleak import BleakClient
    except ImportError:
        print("Install bleak: pip install bleak")
        sys.exit(1)

    print(f"\n--- Test 1: Wrong PIN ({WRONG_PIN}) ---")
    print("Connect, send keep-alive with wrong PIN, wait 5s...")
    client = BleakClient(address, timeout=CONNECT_TIMEOUT)
    try:
        await client.connect()
        print("  Connected.")
        keep_alive = make_keep_alive(WRONG_PIN)
        try:
            await client.write_gatt_char(BLE_CHAR_UUID, keep_alive, response=False)
        except Exception as e:
            print(f"  Write failed (device may have rejected): {e}")
            return (True, True)  # treat as "validates PIN"
        await asyncio.sleep(WAIT_AFTER_KEEPALIVE)
        still_connected = client.is_connected
        if still_connected:
            print("  Device stayed connected → does NOT validate PIN (e.g. RC2 remote).")
            return (False, True)
        print("  Device disconnected → validates PIN (expected for bed base).")
        return (True, True)
    except Exception as e:
        print(f"  Error: {e}")
        return (False, False)  # did not connect
    finally:
        if client.is_connected:
            await client.disconnect()


async def test_correct_pin(address: str, pin: str) -> tuple[bool, bool]:
    """(pin_accepted, connected). If not connected, pin_accepted is meaningless."""
    try:
        from bleak import BleakClient
    except ImportError:
        print("Install bleak: pip install bleak")
        sys.exit(1)

    print(f"\n--- Test 2: Correct PIN ({pin}) ---")
    print("Connect, send keep-alive with PIN, wait 5s, send CMD_STOP, wait 1s...")
    client = BleakClient(address, timeout=CONNECT_TIMEOUT)
    try:
        await client.connect()
        print("  Connected.")
        keep_alive = make_keep_alive(pin)
        try:
            await client.write_gatt_char(BLE_CHAR_UUID, keep_alive, response=False)
        except Exception as e:
            print(f"  Keep-alive write failed: {e}")
            return (False, True)
        await asyncio.sleep(WAIT_AFTER_KEEPALIVE)
        if not client.is_connected:
            print("  Device disconnected after keep-alive → wrong PIN or not bed base.")
            return (False, True)
        try:
            await client.write_gatt_char(BLE_CHAR_UUID, CMD_STOP, response=False)
        except Exception as e:
            print(f"  CMD_STOP failed: {e}")
            return (False, True)
        await asyncio.sleep(1.0)
        if not client.is_connected:
            print("  Device disconnected after CMD_STOP.")
            return (False, True)
        print("  Stayed connected and accepted command → PIN accepted.")
        return (True, True)
    except Exception as e:
        print(f"  Error: {e}")
        return (False, False)  # did not connect
    finally:
        if client.is_connected:
            await client.disconnect()


async def main():
    address = "F6:21:DD:DD:6F:19"
    pin = "1987"

    if len(sys.argv) >= 2:
        address = sys.argv[1].strip()
    if len(sys.argv) >= 3:
        pin = sys.argv[2].strip()

    # Normalize: 12 hex chars → BLE MAC (XX:XX:XX:XX:XX:XX). UUID (e.g. macOS CoreBluetooth id) leave as-is.
    hex_only = address.replace(":", "").replace("-", "").upper()
    if len(hex_only) == 12:
        address = ":".join(hex_only[i : i + 2] for i in (0, 2, 4, 6, 8, 10))

    print(f"Octo Bed BLE PIN test")
    print(f"Address: {address}  PIN: {pin}")

    validates, connected1 = await test_wrong_pin(address)
    ok, connected2 = await test_correct_pin(address, pin)

    print("\n--- Summary ---")
    if not connected1 and not connected2:
        print("Device was not found. This Mac's Bluetooth cannot see the bed.")
        print("→ Use Home Assistant to add the device: the BLE proxy (e.g. 192.168.1.192)")
        print("  talks to the bed; the integration will use the proxy. Ensure the proxy")
        print("  is connected in Settings → Devices & services → Bluetooth.")
    else:
        print(f"Device validates PIN (disconnects on wrong PIN): {validates}")
        print(f"Correct PIN accepted (stayed connected + CMD_STOP): {ok}")
        if validates and ok:
            print("→ Behaviour matches bed base; integration flow should work.")
        elif not validates and ok:
            print("→ Device does not disconnect on wrong PIN but accepted your PIN; integration can add it.")
        elif not validates:
            print("→ Device does not disconnect on wrong PIN (e.g. RC2 remote); use bed base MAC.")
        else:
            print("→ Correct PIN was not accepted; check PIN and that this is the bed base.")


if __name__ == "__main__":
    asyncio.run(main())
