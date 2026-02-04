"""Cover entities for Octo Bed (head, feet, both)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity

_LOGGER = logging.getLogger(__name__)


class OctoBedCoverEntity(OctoBedEntity, CoverEntity):
    """Base cover for Octo Bed."""

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    @property
    def current_cover_position(self) -> int | None:
        """Return current position 0-100."""
        return int(round(self.coordinator.head_position))

    @property
    def is_closed(self) -> bool | None:
        return self.current_cover_position == 0


class OctoBedHeadCoverEntity(OctoBedCoverEntity):
    """Head section cover."""

    _attr_name = "Head"
    _attr_unique_id = "head_cover"

    @property
    def current_cover_position(self) -> int | None:
        return int(round(self.coordinator.head_position))

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._run_to_position(100.0, is_head=True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._run_to_position(0.0, is_head=True)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is not None:
            await self._run_to_position(float(position), is_head=True)

    async def _run_to_position(self, target: float, is_head: bool) -> None:
        """Run head to target 0-100 (time-based, then stop)."""
        coordinator = self.coordinator
        current = coordinator.head_position
        cal_ms = coordinator.head_calibration_ms
        diff = abs(target - current)
        if diff < 0.5:
            return
        duration_ms = int((diff / 100.0) * cal_ms)
        duration_ms = max(300, min(cal_ms, duration_ms))
        coordinator.set_movement_active(True)
        loop = asyncio.get_running_loop()
        end_ts = loop.time() + duration_ms / 1000.0
        try:
            if target > current:
                while loop.time() < end_ts:
                    await coordinator.async_send_head_up()
                    await asyncio.sleep(0.3)
            else:
                while loop.time() < end_ts:
                    await coordinator.async_send_head_down()
                    await asyncio.sleep(0.3)
        finally:
            await coordinator.async_send_stop()
        coordinator.set_head_position(target)
        coordinator.set_movement_active(False)
        self.async_write_ha_state()


class OctoBedFeetCoverEntity(OctoBedCoverEntity):
    """Feet section cover."""

    _attr_name = "Feet"
    _attr_unique_id = "feet_cover"

    @property
    def current_cover_position(self) -> int | None:
        return int(round(self.coordinator.feet_position))

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._run_to_position(100.0, is_head=False)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._run_to_position(0.0, is_head=False)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is not None:
            await self._run_to_position(float(position), is_head=False)

    async def _run_to_position(self, target: float, is_head: bool) -> None:
        coordinator = self.coordinator
        current = coordinator.feet_position
        cal_ms = coordinator.feet_calibration_ms
        diff = abs(target - current)
        if diff < 0.5:
            return
        duration_ms = int((diff / 100.0) * cal_ms)
        duration_ms = max(300, min(cal_ms, duration_ms))
        coordinator.set_movement_active(True)
        loop = asyncio.get_running_loop()
        end_ts = loop.time() + duration_ms / 1000.0
        try:
            if target > current:
                while loop.time() < end_ts:
                    await coordinator.async_send_feet_up()
                    await asyncio.sleep(0.3)
            else:
                while loop.time() < end_ts:
                    await coordinator.async_send_feet_down()
                    await asyncio.sleep(0.3)
        finally:
            await coordinator.async_send_stop()
        coordinator.set_feet_position(target)
        coordinator.set_movement_active(False)
        self.async_write_ha_state()


class OctoBedBothCoverEntity(OctoBedCoverEntity):
    """Both sections cover (moves head and feet together)."""

    _attr_name = "Both"
    _attr_unique_id = "both_cover"

    @property
    def current_cover_position(self) -> int | None:
        h = self.coordinator.head_position
        f = self.coordinator.feet_position
        return int(round((h + f) / 2.0))

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._run_both_to_position(100.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._run_both_to_position(0.0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is not None:
            await self._run_both_to_position(float(position))

    async def _run_both_to_position(self, target: float) -> None:
        coordinator = self.coordinator
        head_current = coordinator.head_position
        feet_current = coordinator.feet_position
        head_cal = coordinator.head_calibration_ms
        feet_cal = coordinator.feet_calibration_ms
        head_diff = abs(target - head_current)
        feet_diff = abs(target - feet_current)
        head_duration_ms = int((head_diff / 100.0) * head_cal) if head_diff >= 0.5 else 0
        feet_duration_ms = int((feet_diff / 100.0) * feet_cal) if feet_diff >= 0.5 else 0
        duration_total = max(head_duration_ms, feet_duration_ms, 300)
        coordinator.set_movement_active(True)
        loop = asyncio.get_running_loop()
        end_ts = loop.time() + duration_total / 1000.0
        try:
            if target > head_current and target > feet_current:
                while loop.time() < end_ts:
                    await coordinator.async_send_both_up()
                    await asyncio.sleep(0.3)
            elif target < head_current and target < feet_current:
                while loop.time() < end_ts:
                    await coordinator.async_send_both_down()
                    await asyncio.sleep(0.3)
            else:
                while loop.time() < end_ts:
                    if target > head_current:
                        await coordinator.async_send_head_up()
                    if target < head_current:
                        await coordinator.async_send_head_down()
                    if target > feet_current:
                        await coordinator.async_send_feet_up()
                    if target < feet_current:
                        await coordinator.async_send_feet_down()
                    await asyncio.sleep(0.3)
        finally:
            await coordinator.async_send_stop()
        coordinator.set_head_position(target)
        coordinator.set_feet_position(target)
        coordinator.set_movement_active(False)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Octo Bed cover entities."""
    coordinator: OctoBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        OctoBedHeadCoverEntity(coordinator, entry),
        OctoBedFeetCoverEntity(coordinator, entry),
        OctoBedBothCoverEntity(coordinator, entry),
    ])
