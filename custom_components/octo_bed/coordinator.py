"""Coordinator for Octo Bed - resolves BLE device via Bluetooth Proxy and sends commands."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Callable

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth, persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BLE_CHAR_UUID,
    CMD_APP_INIT,
    CONF_DEVICE_ADDRESS,
    DELAY_AFTER_CONNECT_CALIBRATION_SEC,
    DELAY_AFTER_CONNECT_MOVEMENT_SEC,
    DELAY_AFTER_CONNECT_SEC,
    DELAY_AFTER_STOP_SAME_CONN_SEC,
    DOMAIN,
    CONF_DEVICE_NICKNAME,
    CONNECT_TIMEOUT,
    CMD_BOTH_DOWN,
    CMD_BOTH_UP,
    CMD_FEET_DOWN,
    CMD_FEET_UP,
    CMD_HEAD_DOWN,
    CMD_HEAD_UP,
    CMD_LIGHT_OFF,
    CMD_LIGHT_ON,
    CMD_MAKE_DISCOVERABLE,
    CMD_SOFT_RESET,
    CMD_STOP,
    DEFAULT_FEET_CALIBRATION_SEC,
    DEFAULT_HEAD_CALIBRATION_SEC,
    KEEP_ALIVE_DELAY_SEC,
    KEEP_ALIVE_ACTIVE_MOVEMENT_SEC,
    KEEP_ALIVE_INTERVAL_SEC,
    KEEP_ALIVE_PREFIX,
    KEEP_ALIVE_SUFFIX,
    SET_PIN_PREFIX,
    MOVEMENT_COMMAND_INTERVAL_SEC,
    PIN_RESPONSE_ACCEPTED,
    PIN_RESPONSE_NOT_SET,
    PIN_RESPONSE_REJECTED,
    PIN_RESPONSE_REJECTED_1B,
    PIN_RESPONSE_REJECTED_ALT,
    PIN_RESPONSE_STATUS_BYTE_INDEX,
    WRITE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_pin_str(pin: str) -> str:
    """Normalize PIN to exactly 4 digit characters. Non-digits are skipped; result is left-padded with '0'."""
    raw = (pin or "0000").strip()
    digits_only = "".join(c for c in raw if c in "0123456789")[:4]
    return digits_only.ljust(4, "0")


def normalize_pin(pin: str) -> str:
    """Normalize PIN to exactly 4 digits. Use when saving to config entry or sending to device."""
    return _normalize_pin_str(pin)


def _pin_to_digits(pin: str) -> bytes:
    """Convert PIN string to exactly 4 bytes (0-9). Non-digits become 0 so the bed never gets invalid bytes."""
    s = _normalize_pin_str(pin)
    return bytes(
        ord(c) - ord("0") if c in "0123456789" else 0 for c in s
    )


def _make_keep_alive(pin: str) -> bytes:
    """Build keep-alive packet with 4-digit PIN."""
    return KEEP_ALIVE_PREFIX + _pin_to_digits(pin) + KEEP_ALIVE_SUFFIX


def _make_set_pin(pin: str) -> bytes:
    """Build first-time set-PIN packet (40 20 3c 04 00 04 02 01 + digits + 40). Bed replies with two notifications; second is 40 21 43 ... 1a (accepted)."""
    return SET_PIN_PREFIX + _pin_to_digits(pin) + KEEP_ALIVE_SUFFIX


async def _write_gatt_char_flexible(
    client: Any, data: bytes, response: bool = False
) -> None:
    """Write to FFE1 characteristic (Handle 0x0011 per captures). Use UUID only - handle fallback fails on some proxies ('Characteristic 17 was not found').
    Retries once on 'characteristic not found' – no delay to avoid movement pause."""
    try:
        await client.write_gatt_char(BLE_CHAR_UUID, data, response=response)
    except Exception as e:
        err = str(e).lower()
        if "not found" in err and "characteristic" in err:
            await client.write_gatt_char(BLE_CHAR_UUID, data, response=response)
        else:
            raise


def _find_char_specifier(client: Any) -> str:
    """Return UUID for FFE1 (YAML: characteristic_uuid ffe1). Use UUID only - handle fails on Bluetooth proxy.
    Do NOT send CMD_STOP here - official app never sends stop before keep-alive/0x7F (per captures)."""
    return BLE_CHAR_UUID


async def _start_notify_flexible(client: Any, callback: Any) -> None:
    """Start notifications on FFE1. Use UUID only (handle fallback fails on some proxies)."""
    await client.start_notify(BLE_CHAR_UUID, callback)


async def _stop_notify_flexible(client: Any) -> None:
    """Stop notifications on FFE1."""
    try:
        await client.stop_notify(BLE_CHAR_UUID)
    except Exception:
        pass


async def _safe_disconnect(client: Any) -> None:
    """Disconnect BLE client. Only disconnect when connected to avoid 'Removing a non-existing connecting' from Bluetooth proxy."""
    if client is None:
        return
    try:
        if client.is_connected:
            await client.disconnect()
    except Exception:
        pass


def _parse_pin_response(data: bytes) -> bool | None:
    """Parse bed notification after keep-alive. True = PIN accepted (0x1A), False = rejected (0x18, 0x1b, 0x00, 0x1f), None = unknown.
    Accepts 40 21 ... or 46 21 ... prefix; status at index 5 or last byte. 0x1f = no PIN set (e.g. after hard reset)."""
    if not data or len(data) < 2:
        return None
    if data[1] != 0x21:
        return None
    if data[0] not in (0x40, 0x46):
        return None
    def accepted(s: int) -> bool:
        return s == PIN_RESPONSE_ACCEPTED
    def rejected(s: int) -> bool:
        return s in (PIN_RESPONSE_REJECTED, PIN_RESPONSE_REJECTED_ALT, PIN_RESPONSE_REJECTED_1B, PIN_RESPONSE_NOT_SET)
    # Check status at index 5 (40 21 43 00 01 XX ...)
    if len(data) > PIN_RESPONSE_STATUS_BYTE_INDEX:
        status = data[PIN_RESPONSE_STATUS_BYTE_INDEX]
        if accepted(status):
            return True
        if rejected(status):
            return False
    # Some beds send 46 21 ... 18 or 46 21 43 80 01 36 00 (0x00 = rejected at last byte)
    if len(data) >= 2:
        last = data[-1]
        if accepted(last):
            return True
        if rejected(last):
            return False
    return None


class OctoBedCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Stores bed state and sends BLE commands via Bluetooth Proxy."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=60),
        )
        self._entry = entry
        _addr = entry.data.get(CONF_DEVICE_ADDRESS)
        self._device_address: str | None = (_addr and _addr.strip()) or None
        self._device_name = entry.data.get("device_name", "RC2")
        self._pin = _normalize_pin_str(entry.data.get("pin", "0000"))
        head_sec = entry.options.get("head_calibration_seconds", entry.data.get("head_calibration_seconds", DEFAULT_HEAD_CALIBRATION_SEC))
        feet_sec = entry.options.get("feet_calibration_seconds", entry.data.get("feet_calibration_seconds", DEFAULT_FEET_CALIBRATION_SEC))
        self._head_calibration_ms = int(float(head_sec) * 1000)
        self._feet_calibration_ms = int(float(feet_sec) * 1000)

        # Position state (persisted in options like YAML restore_value)
        self._head_position = float(entry.options.get("head_position", 0))
        self._feet_position = float(entry.options.get("feet_position", 0))
        self._light_on = False
        self._movement_active = False
        self._last_movement_end_time: float = 0.0
        self._cancel_discovery: Any = None
        self._keep_alive_task: asyncio.Task[None] | None = None
        # Calibration: 0=idle, 1=head, 2=feet
        self._calibration_mode = 0
        self._calibration_start_time: float = 0.0
        self._calibration_task: asyncio.Task[None] | None = None
        self._calibration_active = False
        self._calibration_stop_event: asyncio.Event | None = None
        self._calibration_notification_task: asyncio.Task[None] | None = None
        self._calibration_stopping = False
        # Test scan: send pattern-based system commands with delay; Stop test scan cancels it
        self._test_scan_task: asyncio.Task[None] | None = None
        self._test_scan_stop: asyncio.Event | None = None
        self._test_scan_last_desc: str = ""
        self._test_scan_last_index: int = 0
        self._test_scan_total: int = 0
        self._test_scan_set_id: int = 0
        # True only after we've sent keep-alive with PIN and device stayed connected (wrong PIN = disconnect)
        self._authenticated: bool = False
        # True when device reported 0x1F (no PIN set) — use CMD_APP_INIT instead of keep-alive before commands
        self._device_has_no_pin: bool = False
        # Last FFE1 notification that was not a PIN response (e.g. c0 21 status) – for diagnostics / future parsing
        self._last_device_notification_hex: str = ""

    @property
    def device_address(self) -> str | None:
        """Configured MAC from entry, or discovered address. Empty string is treated as None."""
        addr = self._entry.data.get(CONF_DEVICE_ADDRESS) or self._device_address
        return addr if (addr and addr.strip()) else None

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def pin(self) -> str:
        return _normalize_pin_str(self._entry.data.get("pin", self._pin))

    @property
    def head_position(self) -> float:
        return self._head_position

    @property
    def feet_position(self) -> float:
        return self._feet_position

    @property
    def light_on(self) -> bool:
        return self._light_on

    @property
    def movement_active(self) -> bool:
        return self._movement_active

    @property
    def head_calibration_ms(self) -> int:
        sec = self._entry.options.get(
            "head_calibration_seconds",
            self._entry.data.get("head_calibration_seconds", DEFAULT_HEAD_CALIBRATION_SEC),
        )
        return max(1000, min(120000, int(float(sec) * 1000)))

    @property
    def feet_calibration_ms(self) -> int:
        sec = self._entry.options.get(
            "feet_calibration_seconds",
            self._entry.data.get("feet_calibration_seconds", DEFAULT_FEET_CALIBRATION_SEC),
        )
        return max(1000, min(120000, int(float(sec) * 1000)))

    def set_head_position(self, value: float, *, persist: bool = True) -> None:
        self._head_position = max(0.0, min(100.0, value))
        if persist:
            self._persist_position()
        # Lightweight: push to entities without BLE check (avoids blocking during movement)
        self.async_set_updated_data(self._data())

    def set_feet_position(self, value: float, *, persist: bool = True) -> None:
        self._feet_position = max(0.0, min(100.0, value))
        if persist:
            self._persist_position()
        self.async_set_updated_data(self._data())

    def _persist_position(self) -> None:
        """Persist position to config entry options (like YAML restore_value)."""
        opts = dict(self._entry.options)
        opts["head_position"] = self._head_position
        opts["feet_position"] = self._feet_position
        self.hass.config_entries.async_update_entry(self._entry, options=opts)

    def set_light_on(self, value: bool) -> None:
        self._light_on = value

    def set_movement_active(self, value: bool) -> None:
        self._movement_active = value

    def set_calibration(self, head_sec: float | None = None, feet_sec: float | None = None) -> None:
        if head_sec is not None:
            self._head_calibration_ms = max(1000, min(120000, int(head_sec * 1000)))
        if feet_sec is not None:
            self._feet_calibration_ms = max(1000, min(120000, int(feet_sec * 1000)))

    @property
    def calibration_active(self) -> bool:
        return self._calibration_active

    def _address_present(self, addr: str | None) -> bool:
        """True if any adapter (including Bluetooth proxy) has seen this address."""
        if not addr:
            return False
        return (
            bluetooth.async_address_present(self.hass, addr, connectable=True)
            or bluetooth.async_address_present(self.hass, addr, connectable=False)
        )

    def _data(self) -> dict[str, Any]:
        addr = self.device_address
        present = bool(addr and self._address_present(addr))
        # Connected = authenticated: we can send commands because the correct PIN was accepted (like ESPHome).
        # Not just "BLE MAC in range" – wrong PIN or no auth means disconnected.
        connected = bool(present and self._authenticated)
        if not addr:
            connection_status = "searching"
        elif not present:
            connection_status = "disconnected"
        elif not self._authenticated:
            connection_status = "pin_not_accepted"
        else:
            connection_status = "connected"
        data: dict[str, Any] = {
            "head_position": self._head_position,
            "feet_position": self._feet_position,
            "light_on": self._light_on,
            "movement_active": self._movement_active,
            "device_address": addr,
            "available": addr is not None,
            "connected": connected,
            "connection_status": connection_status,
            "calibration_active": self._calibration_active,
        }
        if self._calibration_active:
            elapsed = self.hass.loop.time() - self._calibration_start_time
            data["calibration_elapsed_sec"] = round(elapsed, 1)
            data["calibration_elapsed_formatted"] = _format_elapsed(elapsed)
            data["calibration_section"] = "head" if self._calibration_mode == 1 else "feet"
        if self._last_device_notification_hex:
            data["last_device_notification"] = self._last_device_notification_hex
        if self._test_scan_total and self._test_scan_last_index:
            data["last_test_command"] = f"{self._test_scan_last_desc} ({self._test_scan_last_index}/{self._test_scan_total})"
            data["last_test_set_id"] = self._test_scan_set_id
        return data

    async def _check_pin_accepted(self) -> bool:
        """Establish connection, send keep-alive with PIN. Use bed notification (0x1A=accepted, 0x18=rejected) when present, else fall back to disconnect behaviour."""
        addr = self.device_address
        if not addr or not self._address_present(addr):
            return False
        ble_device = self._get_ble_device()
        if not ble_device:
            return False
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
            keep_alive = _make_keep_alive(self.pin)
            received: list[bytes] = []
            notif_event = asyncio.Event()

            def _on_notification(_char_handle: int, data: bytearray) -> None:
                raw = bytes(data)
                received.append(raw)
                if _parse_pin_response(raw) is None:
                    self._last_device_notification_hex = raw.hex()
                notif_event.set()

            try:
                await _start_notify_flexible(client, _on_notification)
            except Exception as e:
                _LOGGER.debug("Could not start notifications for PIN response: %s", e)
            try:
                try:
                    await _write_gatt_char_flexible(client, keep_alive, response=True)
                except Exception:
                    try:
                        await _write_gatt_char_flexible(client, keep_alive, response=False)
                    except Exception:
                        return False
                try:
                    await asyncio.wait_for(notif_event.wait(), timeout=2.5)
                except asyncio.TimeoutError:
                    pass
                # Check all notifications: 0x1F = no PIN (use app init); 0x18 = rejected; 0x1A = accepted
                for data in received:
                    if PIN_RESPONSE_NOT_SET in data:
                        _LOGGER.debug("Device has no PIN set, sending app init (0x7F) per No pin given.txt")
                        self._device_has_no_pin = True
                        await _write_gatt_char_flexible(client, CMD_APP_INIT, response=False)
                        await asyncio.sleep(KEEP_ALIVE_DELAY_SEC)
                        return True
                    parsed = _parse_pin_response(data)
                    if parsed is False:
                        _LOGGER.debug("Bed reported PIN rejected")
                        self._device_has_no_pin = False
                        return False
                    if parsed is True:
                        self._device_has_no_pin = False
                        return True
            finally:
                try:
                    await _stop_notify_flexible(client)
                except Exception:
                    pass

            # Fallback: wrong PIN = device disconnects. If still connected, PIN was accepted (bed may not always send 0x1A).
            await asyncio.sleep(2.0)
            if not client.is_connected:
                _LOGGER.debug("Device disconnected after keep-alive (wrong PIN or not bed base)")
                return False
            _LOGGER.debug("Device stayed connected after keep-alive (PIN accepted, no explicit 0x1A)")
            return True
        except Exception as e:
            _LOGGER.debug("PIN check failed: %s", e)
            return False
        finally:
            await _safe_disconnect(client)

    async def _async_update_data(self) -> dict[str, Any]:
        """Ensure we have a device address and verify PIN is accepted for 'connected' state."""
        # Skip BLE check during movement or calibration - avoid competing connections and disconnects
        if self._movement_active or self._calibration_active or self._calibration_stopping:
            return self._data()
        # Cooldown after movement/calibration: device may need time to become connectable again
        if self._last_movement_end_time:
            elapsed = self.hass.loop.time() - self._last_movement_end_time
            if elapsed < 15.0:
                return self._data()
        addr = self.device_address
        if addr and self._address_present(addr):
            self._authenticated = await self._check_pin_accepted()
            return self._data()
        self._authenticated = False
        if addr:
            _LOGGER.debug("Device %s not present, will retry discovery", addr)
        await self._async_ensure_address()
        return self._data()

    async def _async_ensure_address(self) -> None:
        """Resolve device address from config or discovery."""
        addr = self.device_address
        if addr:
            if self._address_present(addr):
                return
            _LOGGER.debug("Configured address %s not seen by any Bluetooth adapter", addr)
        # Discover by name (check both connectable and non-connectable, e.g. proxy)
        infos_conn = bluetooth.async_discovered_service_info(self.hass, connectable=True)
        infos_any = bluetooth.async_discovered_service_info(self.hass, connectable=False)
        seen_addrs: set[str] = set()
        for info in infos_conn:
            addr_key = (info.address or "").upper().replace(":", "")
            if addr_key and addr_key not in seen_addrs:
                seen_addrs.add(addr_key)
                if info.name and self._device_name and info.name.strip().upper() == self._device_name.strip().upper():
                    self._device_address = info.address
                    self._persist_device_address(info.address)
                    _LOGGER.info("Discovered Octo Bed remote at %s (name: %s)", info.address, info.name)
                    return
        for info in infos_any:
            addr_key = (info.address or "").upper().replace(":", "")
            if addr_key and addr_key not in seen_addrs:
                seen_addrs.add(addr_key)
                if info.name and self._device_name and info.name.strip().upper() == self._device_name.strip().upper():
                    self._device_address = info.address
                    self._persist_device_address(info.address)
                    _LOGGER.info("Discovered Octo Bed remote at %s (name: %s)", info.address, info.name)
                    return
        _LOGGER.debug("No device named %s found; ensure remote is on and in range of Bluetooth Proxy", self._device_name)

    def _persist_device_address(self, address: str) -> None:
        """Save discovered MAC to config entry so it survives reload/restart. Updates title if it was empty."""
        if not address or not address.strip():
            return
        address = address.strip()
        if self._entry.data.get(CONF_DEVICE_ADDRESS) == address:
            return
        new_data = {**self._entry.data, CONF_DEVICE_ADDRESS: address}
        title = self._entry.title or ""
        if self._entry.data.get(CONF_DEVICE_NICKNAME):
            title = f"Octo Bed ({self._entry.data[CONF_DEVICE_NICKNAME]})"
        elif not title or title == "Octo Bed" or "()" in title.replace(" ", ""):
            title = f"Octo Bed ({address})"
        self.hass.config_entries.async_update_entry(
            self._entry,
            data=new_data,
            title=title,
        )

    def _get_ble_device(self):
        """Get BLEDevice for current address (from Bluetooth Proxy or local adapter)."""
        addr = self.device_address
        if not addr:
            return None
        # Prefer connectable; some proxies expose the device as non-connectable in cache
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, addr, connectable=True
        )
        if ble_device is None:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, addr, connectable=False
            )
        return ble_device

    def _get_auth_command(self) -> bytes:
        """Auth command before other commands: CMD_APP_INIT when no PIN, else keep-alive with PIN (per captures)."""
        if self._device_has_no_pin:
            return CMD_APP_INIT
        return _make_keep_alive(self.pin)

    async def _send_command(self, data: bytes) -> bool:
        """Connect to device (via proxy) and write command. Retries once on failure (transient BLE).
        Sends auth first (app init or keep-alive per No pin given / Pin given captures) before other commands."""
        ble_device = self._get_ble_device()
        if not ble_device:
            if self.device_address:
                _LOGGER.warning(
                    "No BLE device available for Octo Bed (address: %s)",
                    self.device_address,
                )
            else:
                _LOGGER.debug("Octo Bed: no address configured, skipping BLE command")
            return False
        auth_cmd = self._get_auth_command()
        for attempt in range(2):
            client = None
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    self._device_name or "Octo Bed",
                    disconnected_callback=None,
                    timeout=CONNECT_TIMEOUT,
                    use_services_cache=False,
                    ble_device_callback=self._get_ble_device_for_reconnect,
                )
                await asyncio.sleep(DELAY_AFTER_CONNECT_MOVEMENT_SEC)
                if data != auth_cmd:
                    await _write_gatt_char_flexible(client, auth_cmd, response=False)
                    await asyncio.sleep(KEEP_ALIVE_DELAY_SEC)
                await _write_gatt_char_flexible(client, data, response=False)
                return True
            except Exception as e:
                err = str(e).lower()
                if attempt == 0:
                    _LOGGER.debug("BLE write failed (will retry once): %s", e)
                    backoff = 4.0 if "characteristic" in err and "not found" in err else 1.0
                    await asyncio.sleep(backoff)
                else:
                    _LOGGER.warning("BLE write failed after retry: %s", e)
            finally:
                await _safe_disconnect(client)
        return False

    async def _send_command_and_capture_notification(self, data: bytes, wait_s: float = 2.5) -> bool:
        """Send command, enable notifications, wait for first response; store it in _last_device_notification_hex (see BLE status sensor)."""
        ble_device = self._get_ble_device()
        if not ble_device and self.device_address:
            ble_device = await _wait_for_ble_device(self.hass, self.device_address)
        if not ble_device:
            return False
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
            received: list[bytes] = []
            notif_event = asyncio.Event()

            def _on_notification(_char_handle: int, payload: bytearray) -> None:
                received.append(bytes(payload))
                notif_event.set()

            await _start_notify_flexible(client, _on_notification)
            try:
                await _write_gatt_char_flexible(client, data, response=False)
                try:
                    await asyncio.wait_for(notif_event.wait(), timeout=wait_s)
                except asyncio.TimeoutError:
                    pass
                if received:
                    self._last_device_notification_hex = received[-1].hex()
                else:
                    self._last_device_notification_hex = ""
            finally:
                try:
                    await _stop_notify_flexible(client)
                except Exception:
                    pass
            return True
        except Exception as e:
            _LOGGER.debug("Send and capture failed: %s", e)
            return False
        finally:
            await _safe_disconnect(client)

    async def async_send_stop(self) -> bool:
        """Send stop command twice (ESPHome pattern for reliability). Single connection to reduce latency."""
        ble_device = self._get_ble_device()
        if not ble_device:
            return False
        auth_cmd = self._get_auth_command()
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
            await _write_gatt_char_flexible(client, auth_cmd, response=False)
            await asyncio.sleep(KEEP_ALIVE_DELAY_SEC)
            await _write_gatt_char_flexible(client, CMD_STOP, response=False)
            await asyncio.sleep(0.1)
            await _write_gatt_char_flexible(client, CMD_STOP, response=False)
            return True
        except Exception as e:
            _LOGGER.debug("async_send_stop failed: %s", e)
            return False
        finally:
            await _safe_disconnect(client)

    async def async_send_make_discoverable(self) -> bool:
        """Send make-discoverable command twice (like pressing hub button 2× = teach remote)."""
        ok1 = await self._send_command(CMD_MAKE_DISCOVERABLE)
        await asyncio.sleep(0.5)
        ok2 = await self._send_command(CMD_MAKE_DISCOVERABLE)
        return ok1 or ok2

    async def async_send_soft_reset(self) -> bool:
        """Send soft/low reset (40 20 ae 00 00 b2 40). Does not require re-adding the bed."""
        return await self._send_command(CMD_SOFT_RESET)

    async def async_send_system_command(self, family: str, opcode: int) -> bool:
        """Build and send a system command by pattern. family='short' -> 7 bytes (40 20 OP 00 00 CK 40, CK=0x160-OP). family='72' -> 15 bytes (40 20 72 00 08 OP ...)."""
        op = opcode & 0xFF
        if family == "short":
            cmd = bytes([0x40, 0x20, op, 0x00, 0x00, (0x160 - op) & 0xFF, 0x40])
        elif family == "72":
            cmd = bytes([
                0x40, 0x20, 0x72, 0x00, 0x08, op, 0x00, 0x00,
                0x10, 0x01, 0x01, 0x01, 0x01, 0x01, 0x40,
            ])
        else:
            return False
        return await self._send_command(cmd)

    # Test scan: (family, opcode) per set. Press Stop test scan to cancel.
    # Set 2 excludes 0xAE (use Soft reset). Set 3 removed: D0–D4 disables BLE control.
    # Set 5: ~50 commands to find hard reset; stop when you see it happen, then check BLE status "last_test_command".
    _TEST_SCAN_DELAY_SEC = 0.25
    _TEST_SCAN_SETS: dict[int, list[tuple[str, int]]] = {
        1: [("short", 0x6E), ("short", 0x6F), ("short", 0x70), ("short", 0x71), ("short", 0x72)],
        2: [("short", 0x7E), ("short", 0x7F), ("short", 0x80), ("short", 0xAD), ("short", 0xAF)],
        4: [("72", x) for x in (0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD)],
        5: (
            [("short", x) for x in range(0xA0, 0xC0)]
            + [("72", x) for x in list(range(0xC0, 0xCA)) + list(range(0xE0, 0xE8))]
        ),
    }

    async def _run_test_scan(self, set_id: int) -> None:
        """Send commands for the given set with delay; stop when _test_scan_stop is set."""
        stop = self._test_scan_stop
        commands = self._TEST_SCAN_SETS.get(set_id, [])
        total = len(commands)
        self._test_scan_set_id = set_id
        self._test_scan_total = total
        try:
            for i, (family, opcode) in enumerate(commands):
                if stop and stop.is_set():
                    _LOGGER.debug("Test scan set %s stopped by user", set_id)
                    break
                idx = i + 1
                desc = f"{family} 0x{opcode:02X}"
                self._test_scan_last_desc = desc
                self._test_scan_last_index = idx
                _LOGGER.info("Test scan set %s: sending %s (%s/%s)", set_id, desc, idx, total)
                await self.async_send_system_command(family, opcode)
                await asyncio.sleep(self._TEST_SCAN_DELAY_SEC)
        except asyncio.CancelledError:
            pass
        finally:
            self._test_scan_task = None

    def async_start_test_scan(self, set_id: int) -> None:
        """Start sending test-set commands (use Stop test scan to cancel)."""
        if set_id not in self._TEST_SCAN_SETS:
            return
        if self._test_scan_task is not None and not self._test_scan_task.done():
            return
        self._test_scan_stop = asyncio.Event()
        self._test_scan_stop.clear()
        self._test_scan_task = self.hass.async_create_task(self._run_test_scan(set_id))
        _LOGGER.info("Test scan set %s started (%s commands); press Stop test scan to cancel", set_id, len(self._TEST_SCAN_SETS[set_id]))

    def async_stop_test_scan(self) -> None:
        """Stop the test scan loop."""
        if self._test_scan_stop:
            self._test_scan_stop.set()
        if self._test_scan_task is not None and not self._test_scan_task.done():
            self._test_scan_task.cancel()
        self._test_scan_task = None

    @property
    def test_scan_running(self) -> bool:
        """True if a test scan is running."""
        return self._test_scan_task is not None and not self._test_scan_task.done()

    async def async_set_pin_on_device(self, new_pin: str) -> bool:
        """Send first-time set-PIN command (40 20 3c...). Use after hard reset to set or change PIN on the device. Returns True if bed replied with 0x1A (accepted)."""
        addr = self.device_address
        if not addr or not self._address_present(addr):
            return False
        ble_device = self._get_ble_device()
        if not ble_device:
            ble_device = await _wait_for_ble_device(self.hass, addr, max_sec=15.0)
        if not ble_device:
            return False
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
                max_attempts=2,
            )
            await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
            set_pin_cmd = _make_set_pin(new_pin)
            received: list[bytes] = []
            notif_event = asyncio.Event()

            def _on_notification(_char_handle: int, data: bytearray) -> None:
                received.append(bytes(data))
                notif_event.set()

            try:
                await _start_notify_flexible(client, _on_notification)
            except Exception as e:
                _LOGGER.debug("Set PIN: could not start notifications: %s", e)
                return False
            try:
                await _write_gatt_char_flexible(client, set_pin_cmd, response=True)
            except Exception:
                try:
                    await _write_gatt_char_flexible(client, set_pin_cmd, response=False)
                except Exception:
                    return False
            try:
                await asyncio.wait_for(notif_event.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
            # Bed sends 40 21 3c... then 40 21 43 00 01 1a 01 40 (accepted); or 40 21 3c 01 00 00 1f 40 (no PIN set yet)
            for data in received:
                if _parse_pin_response(data) is True:
                    _LOGGER.info("Set PIN on device: bed accepted new PIN")
                    return True
            if any(PIN_RESPONSE_NOT_SET in d for d in received):
                _LOGGER.info(
                    "Set PIN on device: bed reports no PIN set (e.g. after hard reset). Use set_pin service with your desired PIN to regain control."
                )
            return False
        except Exception as e:
            _LOGGER.warning("Set PIN on device failed: %s", e)
            return False
        finally:
            await _safe_disconnect(client)

    async def async_send_head_up(self) -> bool:
        return await self._send_command(CMD_HEAD_UP)

    async def async_send_head_down(self) -> bool:
        return await self._send_command(CMD_HEAD_DOWN)

    async def async_send_feet_up(self) -> bool:
        return await self._send_command(CMD_FEET_UP)

    async def async_send_feet_down(self) -> bool:
        return await self._send_command(CMD_FEET_DOWN)

    async def async_send_both_up(self) -> bool:
        return await self._send_command(CMD_BOTH_UP)

    async def async_send_both_down(self) -> bool:
        return await self._send_command(CMD_BOTH_DOWN)

    def update_position_after_switch_movement(
        self, command: bytes, duration_sec: float
    ) -> None:
        """Update estimated head/feet position after switch movement.
        Bed does not report position over BLE; we estimate from movement duration vs calibration time."""
        if duration_sec <= 0:
            return
        head_cal_sec = self.head_calibration_ms / 1000.0
        feet_cal_sec = self.feet_calibration_ms / 1000.0
        if command == CMD_HEAD_UP:
            delta = min(100.0, (duration_sec / max(0.1, head_cal_sec)) * 100.0)
            self.set_head_position(self._head_position + delta)
        elif command == CMD_HEAD_DOWN:
            delta = min(100.0, (duration_sec / max(0.1, head_cal_sec)) * 100.0)
            self.set_head_position(self._head_position - delta)
        elif command == CMD_FEET_UP:
            delta = min(100.0, (duration_sec / max(0.1, feet_cal_sec)) * 100.0)
            self.set_feet_position(self._feet_position + delta)
        elif command == CMD_FEET_DOWN:
            delta = min(100.0, (duration_sec / max(0.1, feet_cal_sec)) * 100.0)
            self.set_feet_position(self._feet_position - delta)
        elif command == CMD_BOTH_UP:
            both_cal = max(head_cal_sec, feet_cal_sec)
            delta_both = min(100.0, (duration_sec / max(0.1, both_cal)) * 100.0)
            self.set_head_position(self._head_position + delta_both)
            self.set_feet_position(self._feet_position + delta_both)
        elif command == CMD_BOTH_DOWN:
            both_cal = max(head_cal_sec, feet_cal_sec)
            delta_both = min(100.0, (duration_sec / max(0.1, both_cal)) * 100.0)
            self.set_head_position(self._head_position - delta_both)
            self.set_feet_position(self._feet_position - delta_both)

    async def async_run_movement_loop(
        self,
        command: bytes,
        is_cancelled: Callable[[], bool],
    ) -> tuple[float, bool]:
        """Send movement command every 300ms until cancelled or position limit reached.
        Returns (duration_sec, hit_limit). When hit_limit is True, position was set to 100%/0%."""
        ble_device = self._get_ble_device()
        if not ble_device:
            self.set_movement_active(False)
            return (0.0, False)
        self.set_movement_active(True)
        client = None
        start_time = self.hass.loop.time()
        start_head = self._head_position
        start_feet = self._feet_position
        hit_limit = False
        head_cal_sec = self.head_calibration_ms / 1000.0
        feet_cal_sec = self.feet_calibration_ms / 1000.0
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
            await _write_gatt_char_flexible(
                client, self._get_auth_command(), response=False
            )
            await asyncio.sleep(KEEP_ALIVE_DELAY_SEC)
            last_keep_alive = self.hass.loop.time()
            while not is_cancelled():
                elapsed = self.hass.loop.time() - start_time
                if command in (CMD_HEAD_UP, CMD_FEET_UP, CMD_BOTH_UP):
                    if command == CMD_HEAD_UP:
                        est = start_head + (elapsed / max(0.1, head_cal_sec)) * 100.0
                        self.set_head_position(min(100.0, est), persist=False)
                    elif command == CMD_FEET_UP:
                        est = start_feet + (elapsed / max(0.1, feet_cal_sec)) * 100.0
                        self.set_feet_position(min(100.0, est), persist=False)
                    else:
                        both_cal = max(head_cal_sec, feet_cal_sec)
                        delta = (elapsed / max(0.1, both_cal)) * 100.0
                        est = min(start_head + delta, start_feet + delta)
                        self.set_head_position(min(100.0, start_head + delta), persist=False)
                        self.set_feet_position(min(100.0, start_feet + delta), persist=False)
                    if est >= 100.0:
                        if command == CMD_HEAD_UP:
                            self.set_head_position(100.0)
                        elif command == CMD_FEET_UP:
                            self.set_feet_position(100.0)
                        else:
                            self.set_head_position(100.0)
                            self.set_feet_position(100.0)
                        hit_limit = True
                        break
                else:
                    if command == CMD_HEAD_DOWN:
                        est = start_head - (elapsed / max(0.1, head_cal_sec)) * 100.0
                        self.set_head_position(max(0.0, est), persist=False)
                    elif command == CMD_FEET_DOWN:
                        est = start_feet - (elapsed / max(0.1, feet_cal_sec)) * 100.0
                        self.set_feet_position(max(0.0, est), persist=False)
                    else:
                        both_cal = max(head_cal_sec, feet_cal_sec)
                        delta = (elapsed / max(0.1, both_cal)) * 100.0
                        est = max(start_head - delta, start_feet - delta)
                        self.set_head_position(max(0.0, start_head - delta), persist=False)
                        self.set_feet_position(max(0.0, start_feet - delta), persist=False)
                    if est <= 0.0:
                        if command == CMD_HEAD_DOWN:
                            self.set_head_position(0.0)
                        elif command == CMD_FEET_DOWN:
                            self.set_feet_position(0.0)
                        else:
                            self.set_head_position(0.0)
                            self.set_feet_position(0.0)
                        hit_limit = True
                        break
                await _write_gatt_char_flexible(client, command, response=False)
                now = self.hass.loop.time()
                if now - last_keep_alive >= KEEP_ALIVE_ACTIVE_MOVEMENT_SEC:
                    await _write_gatt_char_flexible(
                        client, self._get_auth_command(), response=False
                    )
                    last_keep_alive = now
                await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
            await _write_gatt_char_flexible(client, CMD_STOP, response=False)
            await asyncio.sleep(0.1)
            await _write_gatt_char_flexible(client, CMD_STOP, response=False)
            if hit_limit:
                self.async_set_updated_data(self._data())
        except asyncio.CancelledError:
            await self._send_command(CMD_STOP)
            raise
        except Exception as e:
            _LOGGER.warning("Movement loop BLE error: %s", e)
            await self._send_command(CMD_STOP)
        finally:
            await _safe_disconnect(client)
            self.set_movement_active(False)
            self._last_movement_end_time = self.hass.loop.time()
        duration = self.hass.loop.time() - start_time
        return (duration, hit_limit)

    async def async_run_movement_for_duration(
        self, command: bytes, duration_sec: float
    ) -> bool:
        """Run a movement command for a fixed duration over a single BLE connection.
        Sends stop first (same connection), then command repeatedly. Returns True on success.
        Retries up to 3 times on characteristic-not-found, resuming from elapsed time (Bluetooth proxy).
        """
        if duration_sec <= 0:
            return True
        ble_device = self._get_ble_device()
        if not ble_device:
            _LOGGER.warning(
                "Movement: no BLE device for %s (device may be out of range or not discovered)",
                self.device_address,
            )
            return False
        self.set_movement_active(True)
        client = None
        elapsed_total = 0.0
        start_time: float = 0.0
        try:
            for attempt in range(3):
                remaining = duration_sec - elapsed_total
                if remaining <= 0.1:
                    return True
                try:
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        ble_device,
                        self._device_name or "Octo Bed",
                        disconnected_callback=None,
                        timeout=CONNECT_TIMEOUT,
                        use_services_cache=False,
                        ble_device_callback=self._get_ble_device_for_reconnect,
                    )
                    await asyncio.sleep(DELAY_AFTER_CONNECT_MOVEMENT_SEC)
                    auth_cmd = self._get_auth_command()
                    await _write_gatt_char_flexible(client, auth_cmd, response=False)
                    await asyncio.sleep(KEEP_ALIVE_DELAY_SEC)
                    await _write_gatt_char_flexible(client, CMD_STOP, response=False)
                    await asyncio.sleep(DELAY_AFTER_STOP_SAME_CONN_SEC)
                    await _write_gatt_char_flexible(client, CMD_STOP, response=False)
                    await asyncio.sleep(0.1)
                    start_time = self.hass.loop.time()
                    end_ts = start_time + remaining
                    start_head = self._head_position
                    start_feet = self._feet_position
                    head_cal_sec = self.head_calibration_ms / 1000.0
                    feet_cal_sec = self.feet_calibration_ms / 1000.0
                    while self.hass.loop.time() < end_ts:
                        await _write_gatt_char_flexible(client, command, response=False)
                        now = self.hass.loop.time()
                        elapsed = now - start_time
                        if command == CMD_HEAD_UP:
                            est = start_head + (elapsed / max(0.1, head_cal_sec)) * 100.0
                            self.set_head_position(min(100.0, est), persist=False)
                        elif command == CMD_HEAD_DOWN:
                            est = start_head - (elapsed / max(0.1, head_cal_sec)) * 100.0
                            self.set_head_position(max(0.0, est), persist=False)
                        elif command == CMD_FEET_UP:
                            est = start_feet + (elapsed / max(0.1, feet_cal_sec)) * 100.0
                            self.set_feet_position(min(100.0, est), persist=False)
                        elif command == CMD_FEET_DOWN:
                            est = start_feet - (elapsed / max(0.1, feet_cal_sec)) * 100.0
                            self.set_feet_position(max(0.0, est), persist=False)
                        elif command == CMD_BOTH_UP:
                            both_cal = max(head_cal_sec, feet_cal_sec)
                            delta = (elapsed / max(0.1, both_cal)) * 100.0
                            self.set_head_position(min(100.0, start_head + delta), persist=False)
                            self.set_feet_position(min(100.0, start_feet + delta), persist=False)
                        elif command == CMD_BOTH_DOWN:
                            both_cal = max(head_cal_sec, feet_cal_sec)
                            delta = (elapsed / max(0.1, both_cal)) * 100.0
                            self.set_head_position(max(0.0, start_head - delta), persist=False)
                            self.set_feet_position(max(0.0, start_feet - delta), persist=False)
                        await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
                    await _write_gatt_char_flexible(client, CMD_STOP, response=False)
                    await asyncio.sleep(0.1)
                    await _write_gatt_char_flexible(client, CMD_STOP, response=False)
                    return True
                except Exception as e:
                    await _safe_disconnect(client)
                    client = None
                    elapsed_this_attempt = (
                        self.hass.loop.time() - start_time if start_time > 0 else 0.0
                    )
                    elapsed_total += max(0.0, elapsed_this_attempt)
                    err = str(e).lower()
                    is_char_not_found = "characteristic" in err and "not found" in err
                    if attempt < 2 and is_char_not_found:
                        _LOGGER.debug(
                            "Movement: characteristic not found at ~%.0f%% (resuming in 1s): %s",
                            100.0 * elapsed_total / duration_sec if duration_sec else 0,
                            e,
                        )
                        await asyncio.sleep(1.0)
                        ble_device = self._get_ble_device()
                        if not ble_device:
                            _LOGGER.warning("Movement: no BLE device for retry")
                            await self._send_command(CMD_STOP)
                            return False
                        continue
                    _LOGGER.warning("Movement-for-duration BLE error: %s", e)
                    await self._send_command(CMD_STOP)
                    return False
        finally:
            await _safe_disconnect(client)
            self.set_movement_active(False)
            self._last_movement_end_time = self.hass.loop.time()

    async def async_set_head_position(self, position: float) -> bool:
        """Move head to 0-100%% (like cover set_position). Single BLE connection for smooth movement."""
        position = max(0.0, min(100.0, position))
        current = self._head_position
        if abs(position - current) < 0.5:
            return True
        diff = abs(position - current)
        duration_ms = int((diff / 100.0) * self._head_calibration_ms)
        duration_ms = max(300, min(self._head_calibration_ms, duration_ms))
        duration_sec = duration_ms / 1000.0
        command = CMD_HEAD_UP if position > current else CMD_HEAD_DOWN
        ok = await self.async_run_movement_for_duration(command, duration_sec)
        if ok:
            self.set_head_position(position)
        return ok

    async def async_set_feet_position(self, position: float) -> bool:
        """Move feet to 0-100%% (like cover set_position). Single BLE connection for smooth movement."""
        position = max(0.0, min(100.0, position))
        current = self._feet_position
        if abs(position - current) < 0.5:
            return True
        diff = abs(position - current)
        duration_ms = int((diff / 100.0) * self._feet_calibration_ms)
        duration_ms = max(300, min(self._feet_calibration_ms, duration_ms))
        duration_sec = duration_ms / 1000.0
        command = CMD_FEET_UP if position > current else CMD_FEET_DOWN
        ok = await self.async_run_movement_for_duration(command, duration_sec)
        if ok:
            self.set_feet_position(position)
        return ok

    async def async_set_light(self, on: bool) -> bool:
        if on:
            ok = await self._send_command(CMD_LIGHT_ON)
        else:
            ok = await self._send_command(CMD_LIGHT_OFF)
            if ok:
                await asyncio.sleep(0.2)
                await self._send_command(CMD_LIGHT_OFF)
        if ok:
            self._light_on = on
        return ok

    async def async_send_keep_alive(self) -> bool:
        return await self._send_command(self._get_auth_command())

    async def _keep_alive_loop(self) -> None:
        """Send keep-alive every 30s (same as YAML keep_connection_alive script)."""
        try:
            while True:
                await asyncio.sleep(KEEP_ALIVE_INTERVAL_SEC)
                addr = self.device_address
                if addr and self._address_present(addr):
                    await self.async_send_keep_alive()
                    _LOGGER.debug("Keep-alive sent to %s", addr)
        except asyncio.CancelledError:
            _LOGGER.debug("Keep-alive loop stopped")
            raise

    def start_keep_alive_loop(self) -> None:
        """Start the periodic keep-alive task (call from async_setup_entry)."""
        if self._keep_alive_task is not None and not self._keep_alive_task.done():
            return
        self._keep_alive_task = self.hass.async_create_task(self._keep_alive_loop())
        _LOGGER.debug("Keep-alive loop started (every %ss)", KEEP_ALIVE_INTERVAL_SEC)

    def cancel_keep_alive_loop(self) -> None:
        """Cancel the keep-alive task (call on integration unload)."""
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
            self._keep_alive_task = None

    async def async_ensure_address_from_discovery(self) -> bool:
        """Run discovery once to try to get device address. Returns True if address is set."""
        await self._async_ensure_address()
        return self.device_address is not None

    def reset_ble_connection(self) -> None:
        """Clear discovered address so next refresh will rediscover (like YAML Reset BLE Connection)."""
        self._device_address = None

    def _get_ble_device_for_reconnect(self):
        """Fresh BLE device ref for reconnects (avoids stale proxy cache)."""
        return self._get_ble_device()

    async def _calibration_loop(self, head: bool) -> None:
        """Same as Head Up / Feet Up switch: keep-alive, then CMD_HEAD_UP or CMD_FEET_UP every 300ms until stop.
        Reconnects on BLE error so calibration continues until user presses stop.
        Uses fresh device ref and service cache disabled for stable proxy reconnects.
        """
        command = CMD_HEAD_UP if head else CMD_FEET_UP
        stop_event = self._calibration_stop_event
        if not stop_event:
            return
        section = "head" if head else "feet"
        while not stop_event.is_set():
            ble_device = self._get_ble_device()
            if not ble_device and self.device_address:
                ble_device = await _wait_for_ble_device(
                    self.hass, self.device_address, max_sec=15.0
                )
            if not ble_device:
                _LOGGER.warning("Calibration: BLE device not available, stopping")
                return
            client = None
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    self._device_name or "Octo Bed",
                    disconnected_callback=None,
                    timeout=CONNECT_TIMEOUT,
                    max_attempts=3,
                    use_services_cache=False,
                    ble_device_callback=self._get_ble_device_for_reconnect,
                )
                await asyncio.sleep(DELAY_AFTER_CONNECT_CALIBRATION_SEC)
                await _write_gatt_char_flexible(
                    client, self._get_auth_command(), response=False
                )
                await asyncio.sleep(KEEP_ALIVE_DELAY_SEC)
                await _write_gatt_char_flexible(client, CMD_STOP, response=False)
                await asyncio.sleep(DELAY_AFTER_STOP_SAME_CONN_SEC)
                await _write_gatt_char_flexible(client, CMD_STOP, response=False)
                await asyncio.sleep(0.1)
                last_keep_alive = self.hass.loop.time()
                while not stop_event.is_set():
                    await _write_gatt_char_flexible(
                        client, command, response=False
                    )
                    now = self.hass.loop.time()
                    if now - last_keep_alive >= KEEP_ALIVE_ACTIVE_MOVEMENT_SEC:
                        await _write_gatt_char_flexible(
                            client, self._get_auth_command(), response=False
                        )
                        last_keep_alive = now
                    await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
                await _write_gatt_char_flexible(
                    client, CMD_STOP, response=False
                )
                await asyncio.sleep(0.1)
                await _write_gatt_char_flexible(
                    client, CMD_STOP, response=False
                )
            except asyncio.CancelledError:
                if client:
                    try:
                        await _write_gatt_char_flexible(
                            client, CMD_STOP, response=False
                        )
                    except Exception:
                        pass
                raise
            except Exception as e:
                _LOGGER.warning(
                    "Calibration %s BLE error (reconnecting): %s", section, e
                )
                try:
                    await self._send_command(CMD_STOP)
                except Exception:
                    pass
                if stop_event.is_set():
                    break
                err = str(e).lower()
                backoff = 4.0 if "characteristic" in err and "not found" in err else 0.5
                await asyncio.sleep(backoff)
            finally:
                await _safe_disconnect(client)
        await self._send_command(CMD_STOP)

    def _calibration_notification_id(self) -> str:
        return f"octo_bed_calibration_{self._entry.entry_id}"

    async def _calibration_notification_loop(self) -> None:
        """Update calibration popup and coordinator every second while calibrating."""
        section = "head" if self._calibration_mode == 1 else "feet"
        title = f"Octo Bed – Calibrating {section.capitalize()}"
        notification_id = self._calibration_notification_id()
        try:
            while self._calibration_active:
                elapsed = self.hass.loop.time() - self._calibration_start_time
                elapsed_str = _format_elapsed(elapsed)
                message = (
                    f"**Elapsed: {elapsed_str}**\n\n"
                    f"Move the bed {section} fully up, then press **Calibration Stop** when done."
                )
                persistent_notification.async_create(
                    self.hass,
                    message,
                    title=title,
                    notification_id=notification_id,
                )
                await self.async_request_refresh()
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            persistent_notification.async_dismiss(self.hass, notification_id)

    def _start_calibration_notification(self) -> None:
        """Start the calibration popup and timer update loop."""
        self._calibration_notification_task = self.hass.async_create_task(
            self._calibration_notification_loop()
        )

    async def _stop_calibration_notification(self) -> None:
        """Cancel the calibration notification task and dismiss popup."""
        if self._calibration_notification_task and not self._calibration_notification_task.done():
            self._calibration_notification_task.cancel()
            try:
                await asyncio.wait_for(self._calibration_notification_task, timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._calibration_notification_task = None
        persistent_notification.async_dismiss(
            self.hass, self._calibration_notification_id()
        )

    async def async_start_calibration_head(self) -> bool:
        """Start head calibration (move head up until user stops). Returns True if started."""
        if self._calibration_task and not self._calibration_task.done():
            return False
        await self.async_send_stop()
        await asyncio.sleep(1.0)
        self._calibration_stop_event = asyncio.Event()
        self._calibration_stop_event.clear()
        self._calibration_mode = 1
        self._calibration_active = True
        self._calibration_start_time = self.hass.loop.time()
        self.set_head_position(0.0)
        self._calibration_task = self.hass.async_create_task(self._calibration_loop(head=True))
        self._calibration_task.add_done_callback(self._on_calibration_task_done)
        self._start_calibration_notification()
        _LOGGER.info("Head calibration started; press CALIBRATION STOP when head is fully up")
        return True

    async def async_start_calibration_feet(self) -> bool:
        """Start feet calibration (move feet up until user stops). Returns True if started."""
        if self._calibration_task and not self._calibration_task.done():
            return False
        await self.async_send_stop()
        await asyncio.sleep(1.0)
        self._calibration_stop_event = asyncio.Event()
        self._calibration_stop_event.clear()
        self._calibration_mode = 2
        self._calibration_active = True
        self._calibration_start_time = self.hass.loop.time()
        self.set_feet_position(0.0)
        self._calibration_task = self.hass.async_create_task(self._calibration_loop(head=False))
        self._calibration_task.add_done_callback(self._on_calibration_task_done)
        self._start_calibration_notification()
        _LOGGER.info("Feet calibration started; press CALIBRATION STOP when feet are fully up")
        return True

    def _on_calibration_task_done(self, task: asyncio.Task[None]) -> None:
        """When calibration task completes unexpectedly (e.g. BLE error), stop notification."""
        if not self._calibration_active or self._calibration_stopping:
            return
        # Task finished without user pressing stop – clean up
        self._calibration_active = False
        self._calibration_mode = 0
        self.hass.async_create_task(self._stop_calibration_notification())
        self.hass.async_create_task(self.async_request_refresh())

    async def async_stop_calibration(self) -> tuple[bool, float | None, float | None]:
        """Stop calibration, save elapsed time as 100%% duration, set position to 100%%, move calibrated section back to 0%%. Returns (ok, head_sec, feet_sec)."""
        # Capture mode before task completes (done callback may clear it on BLE error)
        was_head = self._calibration_mode == 1
        was_feet = self._calibration_mode == 2
        self._calibration_stopping = True
        self._last_movement_end_time = self.hass.loop.time()
        try:
            if self._calibration_stop_event:
                self._calibration_stop_event.set()
            if self._calibration_task:
                try:
                    await asyncio.wait_for(self._calibration_task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    self._calibration_task.cancel()
                    try:
                        await self._calibration_task
                    except asyncio.CancelledError:
                        pass
                self._calibration_task = None
            await self.async_send_stop()
            await asyncio.sleep(0.2)
            head_sec = feet_sec = None
            duration_ms = int((self.hass.loop.time() - self._calibration_start_time) * 1000)
            duration_ms = max(1000, min(120000, duration_ms))
            if was_head:
                head_sec = duration_ms / 1000.0
                self._head_calibration_ms = duration_ms
                self.set_head_position(100.0)
                _LOGGER.info("Head calibration saved: %.1f s (100%% = full travel)", head_sec)
            elif was_feet:
                feet_sec = duration_ms / 1000.0
                self._feet_calibration_ms = duration_ms
                self.set_feet_position(100.0)
                _LOGGER.info("Feet calibration saved: %.1f s (100%% = full travel)", feet_sec)
            self._calibration_mode = 0
            self._calibration_active = False
            await self._stop_calibration_notification()
            # Move only the calibrated section back to 0%%
            await self.async_move_to_zero(head_only=was_head, feet_only=was_feet)
            return True, head_sec, feet_sec
        finally:
            self._calibration_stopping = False

    async def async_move_to_zero(
        self, head_only: bool = False, feet_only: bool = False
    ) -> None:
        """Move head and/or feet down to 0%%. head_only/feet_only: move only that section (e.g. after calibration stop)."""
        move_head = head_only or (not feet_only and self._head_position > 0.5)
        move_feet = feet_only or (not head_only and self._feet_position > 0.5)
        sections = " ".join(filter(None, ["head" if move_head else "", "feet" if move_feet else ""]))
        _LOGGER.info("Moving to zero (flat): %s", sections or "none")
        if move_head:
            head_start = self._head_position
            if head_start > 0.5:
                duration_ms = int((head_start / 100.0) * self._head_calibration_ms)
                duration_ms = max(300, duration_ms)
                await self.async_run_movement_for_duration(
                    CMD_HEAD_DOWN, duration_ms / 1000.0
                )
            self.set_head_position(0.0)
            if move_feet:
                await asyncio.sleep(0.5)
        if move_feet:
            feet_start = self._feet_position
            if feet_start > 0.5:
                duration_ms = int((feet_start / 100.0) * self._feet_calibration_ms)
                duration_ms = max(300, duration_ms)
                await self.async_run_movement_for_duration(
                    CMD_FEET_DOWN, duration_ms / 1000.0
                )
            self.set_feet_position(0.0)
        _LOGGER.info("Move to zero complete")


# --- Standalone helpers for config flow calibration (no config entry yet) ---

def _standalone_calibration_tasks(hass: HomeAssistant) -> dict[str, asyncio.Task[None]]:
    """Get or create the dict of address -> calibration task."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "_calibration_tasks" not in domain_data:
        domain_data["_calibration_tasks"] = {}
    return domain_data["_calibration_tasks"]


def _standalone_calibration_progress(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Get or create the dict of address -> {start_time, head_sec, feet_sec, head} for progress display."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "_calibration_progress" not in domain_data:
        domain_data["_calibration_progress"] = {}
    return domain_data["_calibration_progress"]


def _normalize_addr(address: str) -> str:
    """Normalize address to 12 hex chars uppercase for use as key."""
    if not address:
        return ""
    return "".join(c for c in address.strip() if c in "0123456789AaBbCcDdEeFf").upper()


# Wrong PIN used to probe whether the device disconnects on invalid PIN (e.g. bed base does, RC2 remote may not)
_PROBE_WRONG_PIN = "9999"

# How long to wait for device to appear in scanner cache before giving up
_WAIT_FOR_DEVICE_SEC = 25.0
_WAIT_FOR_DEVICE_INTERVAL_SEC = 2.0


async def _wait_for_ble_device(
    hass: HomeAssistant,
    address: str,
    max_sec: float | None = None,
) -> Any:
    """Wait for the BLE device to appear in the scanner cache (device may advertise intermittently)."""
    addr = (address or "").strip()
    if not addr:
        return None
    timeout = max_sec if max_sec is not None else _WAIT_FOR_DEVICE_SEC
    # Try colon format if we have 12 hex chars
    normalized = _normalize_addr(addr)
    addresses_to_try = [addr]
    if len(normalized) == 12:
        colon = ":".join(normalized[i : i + 2] for i in (0, 2, 4, 6, 8, 10))
        if colon != addr:
            addresses_to_try.append(colon)
    elapsed = 0.0
    while elapsed < timeout:
        for a in addresses_to_try:
            ble_device = bluetooth.async_ble_device_from_address(hass, a, connectable=True)
            if ble_device is None:
                ble_device = bluetooth.async_ble_device_from_address(hass, a, connectable=False)
            if ble_device:
                return ble_device
        await asyncio.sleep(_WAIT_FOR_DEVICE_INTERVAL_SEC)
        elapsed += _WAIT_FOR_DEVICE_INTERVAL_SEC
    return None


async def probe_device_validates_pin(
    hass: HomeAssistant,
    address: str,
    device_name: str,
) -> bool | None:
    """Send keep-alive with a wrong PIN. Return True if device validates (0x18 or disconnect), False if stays connected with no reject, None if inconclusive (no notifications received, e.g. proxy doesn't forward)."""
    addr = address and address.strip()
    if not addr:
        return False
    ble_device = await _wait_for_ble_device(hass, addr)
    if not ble_device:
        return False
    client = None
    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            device_name or "Octo Bed",
            disconnected_callback=None,
            timeout=CONNECT_TIMEOUT,
            max_attempts=2,
        )
        await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
        keep_alive = _make_keep_alive(_PROBE_WRONG_PIN)
        received: list[bytes] = []
        notif_event = asyncio.Event()

        def _on_notification(_char_handle: int, data: bytearray) -> None:
            received.append(bytes(data))
            notif_event.set()

        try:
            await _start_notify_flexible(client, _on_notification)
            await asyncio.sleep(0.2)
        except Exception as e:
            _LOGGER.debug("Probe: could not start notifications: %s", e)
        try:
            try:
                await _write_gatt_char_flexible(client, keep_alive, response=True)
            except Exception:
                try:
                    await _write_gatt_char_flexible(client, keep_alive, response=False)
                except Exception:
                    return False
            try:
                await asyncio.wait_for(notif_event.wait(), timeout=2.5)
            except asyncio.TimeoutError:
                pass
            # If bed sends 0x18 (rejected), it validates PIN – return immediately
            for data in received:
                if _parse_pin_response(data) is False:
                    _LOGGER.debug("Probe: bed reported PIN rejected (0x18) – device validates PIN")
                    return True
        finally:
            try:
                await _stop_notify_flexible(client)
            except Exception:
                pass
        # No rejection notification – wait briefly to see if device disconnects
        await asyncio.sleep(2.0)
        if not client.is_connected:
            _LOGGER.debug("Probe: device disconnected after wrong PIN (supports PIN verification)")
            return True
        if not received:
            _LOGGER.debug("Probe: no notifications received (proxy may not forward) – inconclusive")
            return None
        _LOGGER.info("Probe: device stayed connected after wrong PIN (does not support PIN verification)")
        return False
    except Exception as e:
        _LOGGER.debug("Probe failed: %s", e)
        return False
    finally:
        await _safe_disconnect(client)


async def validate_pin_with_probe(
    hass: HomeAssistant,
    address: str,
    device_name: str,
    pin: str,
) -> str:
    """Validate user's PIN first (fast path). If it fails, probe to distinguish wrong_pin vs no_pin_check.
    Returns: 'ok' (PIN accepted), 'wrong_pin', 'no_pin_check', 'device_not_found', or 'connection_failed'."""
    result = await validate_pin(hass, address, device_name, pin)
    if result == "ok":
        return "ok"
    if result in ("device_not_found", "connection_failed"):
        return result
    # User PIN failed: probe to distinguish wrong_pin vs no_pin_check (RC2)
    probe_validates = await probe_device_validates_pin(hass, address, device_name)
    if probe_validates is True:
        return "wrong_pin"
    if probe_validates is None:
        _LOGGER.debug("Probe inconclusive (no notifications) – assume wrong_pin so user can retry")
        return "wrong_pin"
    return "no_pin_check"


async def validate_pin(
    hass: HomeAssistant,
    address: str,
    device_name: str,
    pin: str,
) -> str:
    """Connect, send keep-alive with PIN. Returns 'ok', 'wrong_pin', 'device_not_found', or 'connection_failed'."""
    pin = _normalize_pin_str(pin)
    addr = address and address.strip()
    if not addr:
        return "connection_failed"
    ble_device = await _wait_for_ble_device(hass, addr)
    if not ble_device:
        _LOGGER.warning("PIN validation: no BLE device for %s (not seen by scanner within %ss)", addr, _WAIT_FOR_DEVICE_SEC)
        return "device_not_found"

    def _get_ble_device() -> Any:
        """Return fresh device from scanner for retries (avoids stale refs via proxy)."""
        d = bluetooth.async_ble_device_from_address(hass, addr, connectable=True)
        if d is None:
            d = bluetooth.async_ble_device_from_address(hass, addr, connectable=False)
        return d

    client = None
    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            device_name or "Octo Bed",
            disconnected_callback=None,
            timeout=CONNECT_TIMEOUT,
            max_attempts=4,
            use_services_cache=False,
            ble_device_callback=_get_ble_device,
        )
        await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
        keep_alive = _make_keep_alive(pin)
        received: list[bytes] = []
        notif_event = asyncio.Event()

        def _on_notification(_char_handle: int, data: bytearray) -> None:
            received.append(bytes(data))
            notif_event.set()

        try:
            await _start_notify_flexible(client, _on_notification)
            await asyncio.sleep(0.2)  # Let CCC enable settle (official app enables before commands)
        except Exception as e:
            _LOGGER.debug("PIN validation: could not start notifications: %s", e)
        try:
            try:
                await _write_gatt_char_flexible(client, keep_alive, response=True)
            except Exception:
                try:
                    await _write_gatt_char_flexible(client, keep_alive, response=False)
                except Exception:
                    return "connection_failed"
            try:
                await asyncio.wait_for(notif_event.wait(), timeout=3.5)
            except asyncio.TimeoutError:
                pass
            # Check all notifications: 0x1F = no PIN (send app init); 0x18 = rejected; 0x1A = accepted
            for data in received:
                if PIN_RESPONSE_NOT_SET in data:
                    _LOGGER.debug("PIN validation: device has no PIN, sending app init (0x7F)")
                    await _write_gatt_char_flexible(client, CMD_APP_INIT, response=False)
                    await asyncio.sleep(0.2)
                    return "ok"
                parsed = _parse_pin_response(data)
                if parsed is False:
                    _LOGGER.info("PIN validation: bed reported PIN rejected")
                    return "wrong_pin"
                if parsed is True:
                    return "ok"
        finally:
            try:
                await _stop_notify_flexible(client)
            except Exception:
                pass

        # Fallback: no explicit 0x1A or 0x18 received (e.g. Bluetooth proxy does not forward notifications).
        await asyncio.sleep(1.5)
        # Re-check in case notification arrived during sleep
        for data in received:
            parsed = _parse_pin_response(data)
            if parsed is False:
                return "wrong_pin"
            if parsed is True:
                return "ok"
        await asyncio.sleep(1.0)
        if not client.is_connected:
            # Disconnect without explicit 0x18 reject: could be wrong PIN or connection drop.
            # Do NOT return wrong_pin – that would trigger probe and can falsely show "no_pin_check".
            # Return connection_failed so user can retry (avoids misclassifying bed base as RC2).
            _LOGGER.info(
                "PIN validation: device disconnected without explicit reject (0x18). "
                "Treating as connection issue – retry with bed base MAC and correct PIN."
            )
            return "connection_failed"
        # Device stayed connected – treat as accepted (proxy may not forward 0x1A).
        _LOGGER.debug("PIN validation: no 0x1A/0x18 received but device stayed connected (proxy may not forward notifications)")
        return "ok"
    except Exception as e:
        err_msg = str(e).lower()
        if "timeout" in err_msg or "failed to connect" in err_msg:
            _LOGGER.warning("PIN validation: connection failed for %s: %s", addr, e)
            return "connection_failed"
        _LOGGER.warning("PIN validation failed for %s: %s", addr, e)
        return "connection_failed"
    finally:
        await _safe_disconnect(client)


async def send_single_command(
    hass: HomeAssistant,
    address: str,
    device_name: str,
    data: bytes,
) -> bool:
    """Send one BLE command (e.g. CMD_STOP) without a config entry. Returns True on success."""
    addr = address and address.strip()
    if not addr:
        return False
    ble_device = bluetooth.async_ble_device_from_address(hass, addr, connectable=True)
    if ble_device is None:
        ble_device = bluetooth.async_ble_device_from_address(hass, addr, connectable=False)
    if not ble_device:
        _LOGGER.warning("No BLE device for %s", addr)
        return False
    client = None
    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            device_name or "Octo Bed",
            disconnected_callback=None,
            timeout=CONNECT_TIMEOUT,
        )
        await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
        await _write_gatt_char_flexible(client, data, response=False)
        return True
    except Exception as e:
        err = str(e).lower()
        if "characteristic" in err and "not found" in err:
            _LOGGER.warning(
                "BLE write failed: device at %s does not expose the bed control characteristic (FFE1). "
                "Use the bed base unit's BLE MAC address, not the remote (RC2).",
                addr,
            )
        else:
            _LOGGER.warning("BLE write failed: %s", e)
        return False
    finally:
        await _safe_disconnect(client)


async def _standalone_calibration_loop(
    hass: HomeAssistant,
    address: str,
    device_name: str,
    head: bool,
) -> None:
    """Run head-up or feet-up in a loop until cancelled. Sends CMD_STOP on cancel."""
    command = CMD_HEAD_UP if head else CMD_FEET_UP
    addr = address and address.strip()
    if not addr:
        return
    ble_device = bluetooth.async_ble_device_from_address(hass, addr, connectable=True)
    if ble_device is None:
        ble_device = bluetooth.async_ble_device_from_address(hass, addr, connectable=False)
    if not ble_device:
        _LOGGER.warning("No BLE device for calibration: %s", addr)
        return
    client = None
    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            device_name or "Octo Bed",
            disconnected_callback=None,
            timeout=CONNECT_TIMEOUT,
        )
        await asyncio.sleep(DELAY_AFTER_CONNECT_SEC)
        while True:
            await _write_gatt_char_flexible(client, command, response=False)
            await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
    except asyncio.CancelledError:
        try:
            if client:
                await _write_gatt_char_flexible(client, CMD_STOP, response=False)
        except Exception:
            pass
        raise
    except Exception as e:
        err = str(e).lower()
        if "characteristic" in err and "not found" in err:
            _LOGGER.warning(
                "Calibration failed: device at %s does not expose the bed control characteristic (FFE1). "
                "Use the bed base unit's BLE MAC address, not the remote (RC2).",
                addr,
            )
        else:
            _LOGGER.warning("Calibration loop error: %s", e)
    finally:
        await _safe_disconnect(client)
        tasks = _standalone_calibration_tasks(hass)
        tasks.pop(_normalize_addr(addr), None)


def _format_elapsed(seconds: float) -> str:
    """Format seconds as M:SS."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _update_calibration_flow_description(
    hass: HomeAssistant,
    flow_id: str,
    status_text: str,
) -> None:
    """Update the calibrate step's description_placeholders so progress shows in the dialog."""
    flow_mgr = getattr(hass.config_entries, "flow", None)
    if not flow_mgr:
        return
    progress = getattr(flow_mgr, "_progress", None)
    if not progress:
        return
    flow = progress.get(flow_id)
    if not flow or not getattr(flow, "cur_step", None):
        return
    step = flow.cur_step
    if step.get("step_id") != "calibrate":
        return
    placeholders = step.get("description_placeholders") or {}
    if not isinstance(placeholders, dict):
        return
    placeholders["status"] = status_text
    step["description_placeholders"] = placeholders
    flow.async_notify_flow_changed()


async def _standalone_calibration_progress_updater(
    hass: HomeAssistant,
    address: str,
    head: bool,
    flow_id: str | None,
) -> None:
    """Update the calibration dialog's description every second with elapsed time and progress %."""
    key = _normalize_addr(address)
    progress_data = _standalone_calibration_progress(hass)
    try:
        while is_standalone_calibration_running(hass, address):
            info = progress_data.get(key)
            if not info:
                break
            start = info["start_time"]
            cal_sec = info["head_sec"] if head else info["feet_sec"]
            elapsed = hass.loop.time() - start
            elapsed_sec = int(elapsed)
            progress_pct = min(100, int((elapsed / cal_sec) * 100)) if cal_sec and cal_sec > 0 else 0
            elapsed_str = _format_elapsed(elapsed)
            full_travel_label = "Head full travel" if head else "Feet full travel"
            bar_len = 20
            filled = int(progress_pct / 100.0 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            status_text = (
                f"\n\n**{full_travel_label}:** {elapsed_sec} s  \n"
                f"**Elapsed:** {elapsed_str}  \n"
                f"**Progress (estimate):** {progress_pct}%  \n\n"
                f"{bar}  \n\n"
                "Click **Stop** when fully up, then **Not now** to finish."
            )
            if flow_id:
                _update_calibration_flow_description(hass, flow_id, status_text)
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass


def start_standalone_calibration(
    hass: HomeAssistant,
    address: str,
    device_name: str,
    head: bool,
    head_sec: float | None = None,
    feet_sec: float | None = None,
    flow_id: str | None = None,
) -> None:
    """Start head or feet calibration loop (no config entry). Progress shown in the calibration dialog."""
    addr = address and address.strip()
    if not addr:
        return
    key = _normalize_addr(addr)
    tasks = _standalone_calibration_tasks(hass)
    progress_data = _standalone_calibration_progress(hass)
    if key in tasks and not tasks[key].done():
        tasks[key].cancel()
    head_sec = head_sec if head_sec is not None and head_sec > 0 else DEFAULT_HEAD_CALIBRATION_SEC
    feet_sec = feet_sec if feet_sec is not None and feet_sec > 0 else DEFAULT_FEET_CALIBRATION_SEC
    progress_data[key] = {
        "start_time": hass.loop.time(),
        "head_sec": float(head_sec),
        "feet_sec": float(feet_sec),
        "head": head,
    }
    section = "Head" if head else "Feet"
    if flow_id:
        full_travel_label = "Head full travel" if head else "Feet full travel"
        initial_status = (
            f"\n\n**{full_travel_label}:** 0 s  \n"
            "**Elapsed:** 0:00  \n**Progress (estimate):** 0%  \n\n"
            "░░░░░░░░░░░░░░░░░░░░  \n\n"
            "Click **Stop** when fully up, then **Not now** to finish."
        )
        _update_calibration_flow_description(hass, flow_id, initial_status)
    task = hass.async_create_task(
        _standalone_calibration_loop(hass, addr, device_name or "Octo Bed", head)
    )
    tasks[key] = task
    hass.async_create_task(_standalone_calibration_progress_updater(hass, addr, head, flow_id))

    def _remove(_: asyncio.Task[None]) -> None:
        tasks.pop(key, None)
        progress_data.pop(key, None)

    task.add_done_callback(_remove)
    _LOGGER.info("%s calibration started (standalone); use Stop when done", section)


def stop_standalone_calibration(hass: HomeAssistant, address: str) -> bool:
    """Cancel standalone calibration task for this address. Returns True if a task was cancelled."""
    key = _normalize_addr(address)
    _standalone_calibration_progress(hass).pop(key, None)
    tasks = _standalone_calibration_tasks(hass)
    task = tasks.get(key)
    if not task or task.done():
        return False
    task.cancel()
    return True


def is_standalone_calibration_running(hass: HomeAssistant, address: str) -> bool:
    """True if head or feet calibration is currently running for this address (config flow)."""
    key = _normalize_addr(address)
    if not key:
        return False
    tasks = _standalone_calibration_tasks(hass)
    task = tasks.get(key)
    return bool(task and not task.done())
