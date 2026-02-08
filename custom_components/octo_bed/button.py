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


class OctoBedTestSet1Button(OctoBedEntity, ButtonEntity):
    """Send short-form commands 0x6E–0x72 (near 70/71). Press Stop test scan to cancel."""

    _attr_name = "Test set 1 (short 6E–72)"
    _attr_unique_id = "test_set_1"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        self.coordinator.async_start_test_scan(1)
        self.async_write_ha_state()


class OctoBedTestSet2Button(OctoBedEntity, ButtonEntity):
    """Send short-form commands 0x7E, 0x7F, 0x80, 0xAD–0xAF (near 7F, AE). Press Stop test scan to cancel."""

    _attr_name = "Test set 2 (short 7E–80, AD–AF)"
    _attr_unique_id = "test_set_2"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        self.coordinator.async_start_test_scan(2)
        self.async_write_ha_state()


class OctoBedTestSet3Button(OctoBedEntity, ButtonEntity):
    """Send 72-family commands 0xD0–0xD4. Press Stop test scan to cancel."""

    _attr_name = "Test set 3 (72 D0–D4)"
    _attr_unique_id = "test_set_3"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        self.coordinator.async_start_test_scan(3)
        self.async_write_ha_state()


class OctoBedTestSet4Button(OctoBedEntity, ButtonEntity):
    """Send 72-family commands 0xD5–0xDD. Press Stop test scan to cancel."""

    _attr_name = "Test set 4 (72 D5–DD)"
    _attr_unique_id = "test_set_4"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        self.coordinator.async_start_test_scan(4)
        self.async_write_ha_state()


class OctoBedStopTestScanButton(OctoBedEntity, ButtonEntity):
    """Stop the running test scan (Test set 1–4)."""

    _attr_name = "Stop test scan"
    _attr_unique_id = "stop_test_scan"
    _attr_icon = "mdi:stop-circle"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        self.coordinator.async_stop_test_scan()
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
        OctoBedTestSet1Button(coordinator, entry),
        OctoBedTestSet2Button(coordinator, entry),
        OctoBedTestSet3Button(coordinator, entry),
        OctoBedTestSet4Button(coordinator, entry),
        OctoBedStopTestScanButton(coordinator, entry),
        OctoBedResetBleButton(coordinator, entry),
    ])
