"""Button entities for Octo Bed (stop, calibration, reset BLE)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
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


class OctoBedCalibrateHeadButton(OctoBedEntity, ButtonEntity):
    """Start head calibration (move head up; press CALIBRATION STOP when fully up)."""

    _attr_name = "Calibrate Head"
    _attr_unique_id = "calibrate_head"
    _attr_icon = "mdi:ruler"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_start_calibration_head()
        self.async_write_ha_state()


class OctoBedCalibrateFeetButton(OctoBedEntity, ButtonEntity):
    """Start feet calibration (move feet up; press CALIBRATION STOP when fully up)."""

    _attr_name = "Calibrate Feet"
    _attr_unique_id = "calibrate_feet"
    _attr_icon = "mdi:ruler"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_start_calibration_feet()
        self.async_write_ha_state()


class OctoBedCalibrationStopButton(OctoBedEntity, ButtonEntity):
    """Stop calibration, save duration, and move bed to flat (0%)."""

    _attr_name = "Calibration Stop"
    _attr_unique_id = "calibration_stop"
    _attr_icon = "mdi:check-circle-outline"
    _attr_entity_category = EntityCategory.CONFIG

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
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        self.coordinator.reset_ble_connection()
        await self.coordinator.async_config_entry_first_refresh()
        self.async_write_ha_state()


class OctoBedMakeDiscoverableButton(OctoBedEntity, ButtonEntity):
    """Send make-discoverable command twice (teach new remote / make bed visible for pairing)."""

    _attr_name = "Make discoverable (teach new remote)"
    _attr_unique_id = "make_discoverable"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_send_make_discoverable()
        self.async_write_ha_state()


class OctoBedSoftResetButton(OctoBedEntity, ButtonEntity):
    """Send soft/low reset. Does not require re-adding the bed."""

    _attr_name = "Soft reset"
    _attr_unique_id = "soft_reset"
    _attr_icon = "mdi:restart"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_send_soft_reset()
        self.async_write_ha_state()


class OctoBedTest7fButton(OctoBedEntity, ButtonEntity):
    """Send test command 7f (app init). Check BLE status sensor for last_device_notification after pressing."""

    _attr_name = "Test command 7f"
    _attr_unique_id = "test_7f"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_test_7f()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTest70Button(OctoBedEntity, ButtonEntity):
    """Send test command 70. Check BLE status sensor for last_device_notification after pressing."""

    _attr_name = "Test command 70"
    _attr_unique_id = "test_70"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_test_70()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTest71Button(OctoBedEntity, ButtonEntity):
    """Send test command 71. Check BLE status sensor for last_device_notification after pressing."""

    _attr_name = "Test command 71"
    _attr_unique_id = "test_71"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_test_71()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTryHardAfButton(OctoBedEntity, ButtonEntity):
    """Try hard-reset candidate: 40 20 AF... (AE+1). Check BLE status last_device_notification."""

    _attr_name = "Try hard reset (AF)"
    _attr_unique_id = "try_hard_af"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_try_hard_af()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTryHardAdButton(OctoBedEntity, ButtonEntity):
    """Try hard-reset candidate: 40 20 AD... (AE-1)."""

    _attr_name = "Try hard reset (AD)"
    _attr_unique_id = "try_hard_ad"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_try_hard_ad()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTryHardB3Button(OctoBedEntity, ButtonEntity):
    """Try hard-reset candidate: 40 20 AE 00 00 B3 (B2+1)."""

    _attr_name = "Try hard reset (B3)"
    _attr_unique_id = "try_hard_b3"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_try_hard_b3()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTryHardB1Button(OctoBedEntity, ButtonEntity):
    """Try hard-reset candidate: 40 20 AE 00 00 B1 (B2-1)."""

    _attr_name = "Try hard reset (B1)"
    _attr_unique_id = "try_hard_b1"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_try_hard_b1()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTryHardD0Button(OctoBedEntity, ButtonEntity):
    """Try hard-reset candidate: 40 20 72 00 08 D0... (72 family, D0)."""

    _attr_name = "Try hard reset (D0)"
    _attr_unique_id = "try_hard_d0"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_try_hard_d0()
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class OctoBedTryHardD2Button(OctoBedEntity, ButtonEntity):
    """Try hard-reset candidate: 40 20 72 00 08 D2... (72 family, D2)."""

    _attr_name = "Try hard reset (D2)"
    _attr_unique_id = "try_hard_d2"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_send_try_hard_d2()
        await self.coordinator.async_request_refresh()
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
        OctoBedCalibrateHeadButton(coordinator, entry),
        OctoBedCalibrateFeetButton(coordinator, entry),
        OctoBedCalibrationStopButton(coordinator, entry),
        OctoBedMakeDiscoverableButton(coordinator, entry),
        OctoBedSoftResetButton(coordinator, entry),
        OctoBedTest7fButton(coordinator, entry),
        OctoBedTest70Button(coordinator, entry),
        OctoBedTest71Button(coordinator, entry),
        OctoBedTryHardAfButton(coordinator, entry),
        OctoBedTryHardAdButton(coordinator, entry),
        OctoBedTryHardB3Button(coordinator, entry),
        OctoBedTryHardB1Button(coordinator, entry),
        OctoBedTryHardD0Button(coordinator, entry),
        OctoBedTryHardD2Button(coordinator, entry),
        OctoBedResetBleButton(coordinator, entry),
    ])
