"""Coordinator for Octo Bed - resolves BLE device via Bluetooth Proxy and sends commands."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Callable

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BLE_CHAR_UUID,
    CONF_DEVICE_ADDRESS,
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
    CMD_STOP,
    DEFAULT_FEET_CALIBRATION_SEC,
    DEFAULT_HEAD_CALIBRATION_SEC,
    KEEP_ALIVE_INTERVAL_SEC,
    KEEP_ALIVE_PREFIX,
    KEEP_ALIVE_SUFFIX,
    MOVEMENT_COMMAND_INTERVAL_SEC,
    WRITE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


def _make_keep_alive(pin: str) -> bytes:
    """Build keep-alive packet with 4-digit PIN."""
    pin = (pin or "0000").strip()
    while len(pin) < 4:
        pin = "0" + pin
    pin = pin[:4]
    digits = bytes([ord(c) - ord("0") for c in pin])
    return KEEP_ALIVE_PREFIX + digits + KEEP_ALIVE_SUFFIX


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
        self._pin = entry.data.get("pin", "0000")
        head_sec = entry.options.get("head_calibration_seconds", entry.data.get("head_calibration_seconds", DEFAULT_HEAD_CALIBRATION_SEC))
        feet_sec = entry.options.get("feet_calibration_seconds", entry.data.get("feet_calibration_seconds", DEFAULT_FEET_CALIBRATION_SEC))
        self._head_calibration_ms = int(float(head_sec) * 1000)
        self._feet_calibration_ms = int(float(feet_sec) * 1000)

        # In-memory state (same model as your ESPHome config)
        self._head_position = 0.0
        self._feet_position = 0.0
        self._light_on = False
        self._movement_active = False
        self._cancel_discovery: Any = None
        self._keep_alive_task: asyncio.Task[None] | None = None
        # Calibration: 0=idle, 1=head, 2=feet
        self._calibration_mode = 0
        self._calibration_start_time: float = 0.0
        self._calibration_task: asyncio.Task[None] | None = None
        self._calibration_active = False
        self._calibration_stop_event: asyncio.Event | None = None

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
        return self._entry.data.get("pin", self._pin)

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

    def set_head_position(self, value: float) -> None:
        self._head_position = max(0.0, min(100.0, value))

    def set_feet_position(self, value: float) -> None:
        self._feet_position = max(0.0, min(100.0, value))

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
        connected = addr is not None and self._address_present(addr)
        return {
            "head_position": self._head_position,
            "feet_position": self._feet_position,
            "light_on": self._light_on,
            "movement_active": self._movement_active,
            "device_address": addr,
            "available": addr is not None,
            "connected": connected,
            "calibration_active": self._calibration_active,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Ensure we have a device address (from discovery if needed)."""
        addr = self.device_address
        if addr:
            if self._address_present(addr):
                return self._data()
            _LOGGER.debug("Device %s not present, will retry discovery", addr)
        await self._async_ensure_address()
        return self._data()

    async def _async_ensure_address(self) -> None:
        """Resolve device address from config or discovery."""
        addr = self.device_address
        if addr:
            if self._address_present(addr):
                return
            _LOGGER.warning("Configured address %s not seen by any Bluetooth adapter", addr)
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

    async def _send_command(self, data: bytes) -> bool:
        """Connect to device (via proxy) and write command. Returns True on success."""
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
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            await client.write_gatt_char(BLE_CHAR_UUID, data, response=False)
            return True
        except Exception as e:
            _LOGGER.warning("BLE write failed: %s", e)
            return False
        finally:
            if client:
                await client.disconnect()

    async def async_send_stop(self) -> bool:
        """Send stop command."""
        return await self._send_command(CMD_STOP)

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

    async def async_run_movement_loop(
        self,
        command: bytes,
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Run a movement command in a loop over a single BLE connection for smooth movement.
        Caller must ensure only one loop runs at a time. Sends CMD_STOP when done or cancelled.
        """
        ble_device = self._get_ble_device()
        if not ble_device:
            self.set_movement_active(False)
            return
        self.set_movement_active(True)
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            while not is_cancelled():
                await client.write_gatt_char(
                    BLE_CHAR_UUID, command, response=False
                )
                await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
            await client.write_gatt_char(
                BLE_CHAR_UUID, CMD_STOP, response=False
            )
        except asyncio.CancelledError:
            await self._send_command(CMD_STOP)
            raise
        except Exception as e:
            _LOGGER.warning("Movement loop BLE error: %s", e)
            await self._send_command(CMD_STOP)
        finally:
            if client:
                await client.disconnect()
            self.set_movement_active(False)

    async def async_run_movement_for_duration(
        self, command: bytes, duration_sec: float
    ) -> bool:
        """Run a movement command for a fixed duration over a single BLE connection.
        Sends command repeatedly at MOVEMENT_COMMAND_INTERVAL_SEC, then STOP. Returns True on success.
        """
        if duration_sec <= 0:
            return True
        ble_device = self._get_ble_device()
        if not ble_device:
            return False
        self.set_movement_active(True)
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            end_ts = self.hass.loop.time() + duration_sec
            while self.hass.loop.time() < end_ts:
                await client.write_gatt_char(
                    BLE_CHAR_UUID, command, response=False
                )
                await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
            await client.write_gatt_char(
                BLE_CHAR_UUID, CMD_STOP, response=False
            )
            return True
        except Exception as e:
            _LOGGER.warning("Movement-for-duration BLE error: %s", e)
            await self._send_command(CMD_STOP)
            return False
        finally:
            if client:
                await client.disconnect()
            self.set_movement_active(False)

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
        ok = await self._send_command(CMD_LIGHT_ON if on else CMD_LIGHT_OFF)
        if ok:
            self._light_on = on
        return ok

    async def async_send_keep_alive(self) -> bool:
        return await self._send_command(_make_keep_alive(self.pin))

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

    async def _calibration_loop(self, head: bool) -> None:
        """Send head up or feet up over a single BLE connection until stop event (smooth calibration)."""
        command = CMD_HEAD_UP if head else CMD_FEET_UP
        stop_event = self._calibration_stop_event
        if not stop_event:
            return
        ble_device = self._get_ble_device()
        if not ble_device:
            return
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._device_name or "Octo Bed",
                disconnected_callback=None,
                timeout=CONNECT_TIMEOUT,
            )
            while not stop_event.is_set():
                await client.write_gatt_char(
                    BLE_CHAR_UUID, command, response=False
                )
                await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
            await client.write_gatt_char(
                BLE_CHAR_UUID, CMD_STOP, response=False
            )
        except asyncio.CancelledError:
            if client:
                try:
                    await client.write_gatt_char(
                        BLE_CHAR_UUID, CMD_STOP, response=False
                    )
                except Exception:
                    pass
            raise
        except Exception as e:
            _LOGGER.warning("Calibration loop BLE error: %s", e)
            await self._send_command(CMD_STOP)
        finally:
            if client:
                await client.disconnect()

    async def async_start_calibration_head(self) -> bool:
        """Start head calibration (move head up until user stops). Returns True if started."""
        if self._calibration_task and not self._calibration_task.done():
            return False
        await self.async_send_stop()
        await asyncio.sleep(0.5)
        self._calibration_stop_event = asyncio.Event()
        self._calibration_stop_event.clear()
        self._calibration_mode = 1
        self._calibration_active = True
        self._calibration_start_time = self.hass.loop.time()
        self.set_head_position(0.0)
        self._calibration_task = self.hass.async_create_task(self._calibration_loop(head=True))
        _LOGGER.info("Head calibration started; press CALIBRATION STOP when head is fully up")
        return True

    async def async_start_calibration_feet(self) -> bool:
        """Start feet calibration (move feet up until user stops). Returns True if started."""
        if self._calibration_task and not self._calibration_task.done():
            return False
        await self.async_send_stop()
        await asyncio.sleep(0.5)
        self._calibration_stop_event = asyncio.Event()
        self._calibration_stop_event.clear()
        self._calibration_mode = 2
        self._calibration_active = True
        self._calibration_start_time = self.hass.loop.time()
        self.set_feet_position(0.0)
        self._calibration_task = self.hass.async_create_task(self._calibration_loop(head=False))
        _LOGGER.info("Feet calibration started; press CALIBRATION STOP when feet are fully up")
        return True

    async def async_stop_calibration(self) -> tuple[bool, float | None, float | None]:
        """Stop calibration, save duration, set position to 100%%, run move_to_zero. Returns (ok, head_sec, feet_sec)."""
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
        if self._calibration_mode == 1:
            head_sec = duration_ms / 1000.0
            self._head_calibration_ms = duration_ms
            self.set_head_position(100.0)
            _LOGGER.info("Head calibration saved: %.1f s", head_sec)
        elif self._calibration_mode == 2:
            feet_sec = duration_ms / 1000.0
            self._feet_calibration_ms = duration_ms
            self.set_feet_position(100.0)
            _LOGGER.info("Feet calibration saved: %.1f s", feet_sec)
        self._calibration_mode = 0
        self._calibration_active = False
        await self.async_move_to_zero()
        return True, head_sec, feet_sec

    async def async_move_to_zero(self) -> None:
        """Move head then feet down to 0%% (like YAML move_to_zero script). Single BLE connection per section."""
        _LOGGER.info("Moving to zero (flat)")
        head_start = self._head_position
        if head_start > 0.5:
            duration_ms = int((head_start / 100.0) * self._head_calibration_ms)
            duration_ms = max(300, duration_ms)
            await self.async_run_movement_for_duration(
                CMD_HEAD_DOWN, duration_ms / 1000.0
            )
        self.set_head_position(0.0)
        await asyncio.sleep(0.5)
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


async def validate_pin(
    hass: HomeAssistant,
    address: str,
    device_name: str,
    pin: str,
) -> bool:
    """Connect, send keep-alive with PIN, then verify device still accepts commands. Returns True only if PIN is accepted."""
    pin = (pin or "0000").strip()[:4].ljust(4, "0")
    addr = address and address.strip()
    if not addr:
        return False
    ble_device = bluetooth.async_ble_device_from_address(hass, addr, connectable=True)
    if ble_device is None:
        ble_device = bluetooth.async_ble_device_from_address(hass, addr, connectable=False)
    if not ble_device:
        _LOGGER.warning("PIN validation: no BLE device for %s", addr)
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
        keep_alive = _make_keep_alive(pin)
        try:
            await client.write_gatt_char(BLE_CHAR_UUID, keep_alive, response=True)
        except Exception:
            await client.write_gatt_char(BLE_CHAR_UUID, keep_alive, response=False)
        # Give device time to disconnect us if PIN was wrong
        await asyncio.sleep(2.0)
        await client.write_gatt_char(BLE_CHAR_UUID, CMD_STOP, response=False)
        return True
    except Exception as e:
        _LOGGER.warning("PIN validation failed for %s: %s", addr, e)
        return False
    finally:
        if client:
            await client.disconnect()


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
        await client.write_gatt_char(BLE_CHAR_UUID, data, response=False)
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
        if client:
            await client.disconnect()


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
        while True:
            await client.write_gatt_char(BLE_CHAR_UUID, command, response=False)
            await asyncio.sleep(MOVEMENT_COMMAND_INTERVAL_SEC)
    except asyncio.CancelledError:
        try:
            if client:
                await client.write_gatt_char(BLE_CHAR_UUID, CMD_STOP, response=False)
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
        if client:
            await client.disconnect()
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
