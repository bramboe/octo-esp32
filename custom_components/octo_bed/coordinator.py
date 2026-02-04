"""Coordinator for Octo Bed - resolves BLE device via Bluetooth Proxy and sends commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BLE_CHAR_UUID,
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
    KEEP_ALIVE_PREFIX,
    KEEP_ALIVE_SUFFIX,
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
            update_interval=None,
        )
        self._entry = entry
        self._device_address: str | None = entry.data.get("device_address")
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

    @property
    def device_address(self) -> str | None:
        return self._device_address

    @property
    def device_name(self) -> str:
        return self._device_name

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
        return self._head_calibration_ms

    @property
    def feet_calibration_ms(self) -> int:
        return self._feet_calibration_ms

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

    def _data(self) -> dict[str, Any]:
        return {
            "head_position": self._head_position,
            "feet_position": self._feet_position,
            "light_on": self._light_on,
            "movement_active": self._movement_active,
            "device_address": self._device_address,
            "available": self._device_address is not None,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Ensure we have a device address (from discovery if needed)."""
        if self._device_address:
            if bluetooth.async_address_present(self.hass, self._device_address, connectable=True):
                return self._data()
            _LOGGER.debug("Device %s not present, will retry discovery", self._device_address)
        await self._async_ensure_address()
        return self._data()

    async def _async_ensure_address(self) -> None:
        """Resolve device address from config or discovery."""
        if self._device_address:
            if bluetooth.async_address_present(self.hass, self._device_address, connectable=True):
                return
            _LOGGER.warning("Configured address %s not seen by any Bluetooth adapter", self._device_address)
        # Discover by name
        infos = bluetooth.async_discovered_service_info(self.hass, connectable=True)
        for info in infos:
            if info.name and self._device_name and info.name.strip().upper() == self._device_name.strip().upper():
                self._device_address = info.address
                _LOGGER.info("Discovered Octo Bed remote at %s (name: %s)", info.address, info.name)
                return
        _LOGGER.debug("No device named %s found; ensure remote is on and in range of Bluetooth Proxy", self._device_name)

    def _get_ble_device(self):
        """Get BLEDevice for current address (from Bluetooth Proxy or local adapter)."""
        if not self._device_address:
            return None
        return bluetooth.async_ble_device_from_address(
            self.hass, self._device_address, connectable=True
        )

    async def _send_command(self, data: bytes) -> bool:
        """Connect to device (via proxy) and write command. Returns True on success."""
        ble_device = self._get_ble_device()
        if not ble_device:
            _LOGGER.warning("No BLE device available for Octo Bed (address: %s)", self._device_address)
            return False
        try:
            async with BleakClient(
                ble_device,
                timeout=CONNECT_TIMEOUT,
                disconnected_callback=None,
            ) as client:
                await client.write_gatt_char(BLE_CHAR_UUID, data, response=False)
        except Exception as e:
            _LOGGER.warning("BLE write failed: %s", e)
            return False
        return True

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

    async def async_set_light(self, on: bool) -> bool:
        ok = await self._send_command(CMD_LIGHT_ON if on else CMD_LIGHT_OFF)
        if ok:
            self._light_on = on
        return ok

    async def async_send_keep_alive(self) -> bool:
        return await self._send_command(_make_keep_alive(self._pin))

    async def async_ensure_address_from_discovery(self) -> bool:
        """Run discovery once to try to get device address. Returns True if address is set."""
        await self._async_ensure_address()
        return self._device_address is not None
