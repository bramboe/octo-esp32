"""Button entities for Octo Bed (stop, search, keep-alive, calibration, reset BLE)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_FEET_CALIBRATION_SEC,
    CONF_HEAD_CALIBRATION_SEC,
    DOMAIN,
)
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity

_LOGGER = logging.getLogger(__name__)


class OctoBedStopButton(OctoBedEntity, ButtonEntity):
    """Stop all bed movement."""

    _attr_name = "Stop All"
    _attr_unique_id = "stop_all"

    async def async_press(self) -> None:
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)
        self.async_write_ha_state()


class OctoBedSearchButton(OctoBedEntity, ButtonEntity):
    """Trigger discovery for the bed remote."""

    _attr_name = "Search for Device"
    _attr_unique_id = "search_device"

    async def async_press(self) -> None:
        await self.coordinator.async_ensure_address_from_discovery()
        self.async_write_ha_state()


class OctoBedKeepAliveButton(OctoBedEntity, ButtonEntity):
    """Send keep-alive (PIN) to the remote."""

    _attr_name = "Send Keep-Alive"
    _attr_unique_id = "keep_alive"

    async def async_press(self) -> None:
        await self.coordinator.async_send_keep_alive()


class OctoBedCalibrateHeadButton(OctoBedEntity, ButtonEntity):
    """Start head calibration (move head up; press CALIBRATION STOP when fully up)."""

    _attr_name = "Calibrate Head"
    _attr_unique_id = "calibrate_head"
    _attr_icon = "mdi:ruler"
    _attr_entity_category = "config"

    async def async_press(self) -> None:
        await self.coordinator.async_start_calibration_head()
        self.async_write_ha_state()


class OctoBedCalibrateFeetButton(OctoBedEntity, ButtonEntity):
    """Start feet calibration (move feet up; press CALIBRATION STOP when fully up)."""

    _attr_name = "Calibrate Feet"
    _attr_unique_id = "calibrate_feet"
    _attr_icon = "mdi:ruler"
    _attr_entity_category = "config"

    async def async_press(self) -> None:
        await self.coordinator.async_start_calibration_feet()
        self.async_write_ha_state()


class OctoBedCalibrationStopButton(OctoBedEntity, ButtonEntity):
    """Stop calibration, save duration, and move bed to flat (0%)."""

    _attr_name = "Calibration Stop"
    _attr_unique_id = "calibration_stop"
    _attr_icon = "mdi:check-circle-outline"
    _attr_entity_category = "config"

    async def async_press(self) -> None:
        ok, head_sec, feet_sec = await self.coordinator.async_stop_calibration()
        if ok and (head_sec is not None or feet_sec is not None):
            opts = dict(self._entry.options)
            if head_sec is not None:
                opts[CONF_HEAD_CALIBRATION_SEC] = head_sec
            if feet_sec is not None:
                opts[CONF_FEET_CALIBRATION_SEC] = feet_sec
            self.hass.config_entries.async_update_entry(self._entry, options=opts)
        self.async_write_ha_state()


class OctoBedResetBleButton(OctoBedEntity, ButtonEntity):
    """Clear BLE address and trigger rediscovery (like YAML Reset BLE Connection)."""

    _attr_name = "Reset BLE Connection"
    _attr_unique_id = "reset_ble"
    _attr_icon = "mdi:bluetooth-refresh"
    _attr_entity_category = "config"

    async def async_press(self) -> None:
        self.coordinator.reset_ble_connection()
        await self.coordinator.async_config_entry_first_refresh()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Octo Bed buttons."""
    coordinator: OctoBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        OctoBedStopButton(coordinator, entry),
        OctoBedSearchButton(coordinator, entry),
        OctoBedKeepAliveButton(coordinator, entry),
        OctoBedCalibrateHeadButton(coordinator, entry),
        OctoBedCalibrateFeetButton(coordinator, entry),
        OctoBedCalibrationStopButton(coordinator, entry),
        OctoBedResetBleButton(coordinator, entry),
    ])
