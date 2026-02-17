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

from .const import (
    CMD_BOTH_DOWN,
    CMD_BOTH_UP,
    CMD_FEET_DOWN,
    CMD_FEET_UP,
    CMD_HEAD_DOWN,
    CMD_HEAD_UP,
    COVER_DEBOUNCE_SEC,
    DOMAIN,
)
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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._debounce_timer: asyncio.TimerHandle | None = None
        self._pending_target: float | None = None

    @property
    def current_cover_position(self) -> int | None:
        return int(round(self.coordinator.head_position))

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self._run_to_position(100.0, is_head=True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self._run_to_position(0.0, is_head=True)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            return
        target = float(position)
        self._cancel_debounce()
        self._pending_target = target
        self._debounce_timer = self.hass.loop.call_later(
            COVER_DEBOUNCE_SEC, self._debounce_timer_fired_head
        )

    def _debounce_timer_fired_head(self) -> None:
        self._debounce_timer = None
        target = self._pending_target
        self._pending_target = None
        if target is not None:
            self.hass.async_create_task(self._run_to_position(target, is_head=True))

    def _cancel_debounce(self) -> None:
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        self._pending_target = None

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_debounce()
        await super().async_will_remove_from_hass()

    async def _run_to_position(self, target: float, is_head: bool) -> None:
        """Run head or feet to target 0-100 over a single BLE connection (smooth movement).
        Skip stop when at 100%% or 0%% (bed already stopped). Retries once on BLE failure.
        Keeps movement_active=True for the whole operation so coordinator skips BLE checks."""
        coordinator = self.coordinator
        coordinator.set_movement_active(True)
        try:
            at_limit = (
                (is_head and (abs(coordinator.head_position - 100) < 2 or abs(coordinator.head_position) < 2))
                or (not is_head and (abs(coordinator.feet_position - 100) < 2 or abs(coordinator.feet_position) < 2))
            )
            if not at_limit:
                await coordinator.async_send_stop()
                await asyncio.sleep(0.1)
            for attempt in range(2):
                if is_head:
                    current = coordinator.head_position
                    cal_ms = coordinator.head_calibration_ms
                    command = CMD_HEAD_UP if target > current else CMD_HEAD_DOWN
                    set_pos = coordinator.set_head_position
                else:
                    current = coordinator.feet_position
                    cal_ms = coordinator.feet_calibration_ms
                    command = CMD_FEET_UP if target > current else CMD_FEET_DOWN
                    set_pos = coordinator.set_feet_position
                diff = abs(target - current)
                if diff < 0.5:
                    return
                duration_ms = int((diff / 100.0) * cal_ms)
                duration_ms = max(300, min(cal_ms, duration_ms))
                duration_sec = duration_ms / 1000.0
                ok = await coordinator.async_run_movement_for_duration(command, duration_sec)
                if ok:
                    set_pos(target)
                    break
                if attempt == 0:
                    await asyncio.sleep(0.5)
            self.async_write_ha_state()
        finally:
            coordinator.set_movement_active(False)


class OctoBedFeetCoverEntity(OctoBedCoverEntity):
    """Feet section cover."""

    _attr_name = "Feet"
    _attr_unique_id = "feet_cover"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._debounce_timer: asyncio.TimerHandle | None = None
        self._pending_target: float | None = None

    @property
    def current_cover_position(self) -> int | None:
        return int(round(self.coordinator.feet_position))

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self._run_to_position(100.0, is_head=False)

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self._run_to_position(0.0, is_head=False)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            return
        target = float(position)
        self._cancel_debounce()
        self._pending_target = target
        self._debounce_timer = self.hass.loop.call_later(
            COVER_DEBOUNCE_SEC, self._debounce_timer_fired_feet
        )

    def _debounce_timer_fired_feet(self) -> None:
        self._debounce_timer = None
        target = self._pending_target
        self._pending_target = None
        if target is not None:
            self.hass.async_create_task(self._run_to_position(target, is_head=False))

    def _cancel_debounce(self) -> None:
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        self._pending_target = None

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_debounce()
        await super().async_will_remove_from_hass()

    async def _run_to_position(self, target: float, is_head: bool) -> None:
        """Run feet to target. Skip stop when at limit. Retries once on BLE failure.
        Keeps movement_active=True for the whole operation so coordinator skips BLE checks."""
        coordinator = self.coordinator
        coordinator.set_movement_active(True)
        try:
            at_limit = abs(coordinator.feet_position - 100) < 2 or abs(coordinator.feet_position) < 2
            if not at_limit:
                await coordinator.async_send_stop()
                await asyncio.sleep(0.1)
            for attempt in range(2):
                current = coordinator.feet_position
                cal_ms = coordinator.feet_calibration_ms
                diff = abs(target - current)
                if diff < 0.5:
                    return
                duration_ms = int((diff / 100.0) * cal_ms)
                duration_ms = max(300, min(cal_ms, duration_ms))
                duration_sec = duration_ms / 1000.0
                command = CMD_FEET_UP if target > current else CMD_FEET_DOWN
                ok = await coordinator.async_run_movement_for_duration(command, duration_sec)
                if ok:
                    coordinator.set_feet_position(target)
                    break
                if attempt == 0:
                    await asyncio.sleep(0.5)
            self.async_write_ha_state()
        finally:
            coordinator.set_movement_active(False)


class OctoBedBothCoverEntity(OctoBedCoverEntity):
    """Both sections cover (moves head and feet together)."""

    _attr_name = "Both"
    _attr_unique_id = "both_cover"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._debounce_timer: asyncio.TimerHandle | None = None
        self._pending_target: float | None = None

    @property
    def current_cover_position(self) -> int | None:
        h = self.coordinator.head_position
        f = self.coordinator.feet_position
        return int(round((h + f) / 2.0))

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self._run_both_to_position(100.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self._run_both_to_position(0.0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self._cancel_debounce()
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            return
        target = float(position)
        self._cancel_debounce()
        self._pending_target = target
        self._debounce_timer = self.hass.loop.call_later(
            COVER_DEBOUNCE_SEC, self._debounce_timer_fired_both
        )

    def _debounce_timer_fired_both(self) -> None:
        self._debounce_timer = None
        target = self._pending_target
        self._pending_target = None
        if target is not None:
            self.hass.async_create_task(self._run_both_to_position(target))

    def _cancel_debounce(self) -> None:
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        self._pending_target = None

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_debounce()
        await super().async_will_remove_from_hass()

    async def _run_both_to_position(self, target: float) -> None:
        """Move both sections to target. Never combines movement commands (per YAML).
        Same direction: phase 1 = both_up/down until faster section done; phase 2 = head or feet only.
        Different directions: sequential head then feet (never alternating). Retries once on BLE failure.
        Skip stop when both at 100%% or 0%%. Keeps movement_active=True for whole operation."""
        coordinator = self.coordinator
        coordinator.set_movement_active(True)
        try:
            both_at_limit = (
                (abs(coordinator.head_position - 100) < 2 or abs(coordinator.head_position) < 2)
                and (abs(coordinator.feet_position - 100) < 2 or abs(coordinator.feet_position) < 2)
            )
            if not both_at_limit:
                await coordinator.async_send_stop()
                await asyncio.sleep(0.1)
            for attempt in range(2):
                head_current = coordinator.head_position
                feet_current = coordinator.feet_position
                head_diff = abs(target - head_current)
                feet_diff = abs(target - feet_current)
                head_duration_sec = (head_diff / 100.0) * (coordinator.head_calibration_ms / 1000.0) if head_diff >= 0.5 else 0.0
                feet_duration_sec = (feet_diff / 100.0) * (coordinator.feet_calibration_ms / 1000.0) if feet_diff >= 0.5 else 0.0
                head_duration_sec = max(0.3, head_duration_sec)
                feet_duration_sec = max(0.3, feet_duration_sec)
                all_ok = True
                if target > head_current and target > feet_current:
                    phase1 = min(head_duration_sec, feet_duration_sec)
                    ok = await coordinator.async_run_movement_for_duration(CMD_BOTH_UP, phase1)
                    if not ok:
                        all_ok = False
                    else:
                        head_remaining = head_duration_sec - phase1
                        feet_remaining = feet_duration_sec - phase1
                        if head_remaining > 0.1:
                            await asyncio.sleep(0.5)
                            ok = await coordinator.async_run_movement_for_duration(CMD_HEAD_UP, head_remaining)
                        elif feet_remaining > 0.1:
                            await asyncio.sleep(0.5)
                            ok = await coordinator.async_run_movement_for_duration(CMD_FEET_UP, feet_remaining)
                        else:
                            ok = True
                        if ok:
                            coordinator.set_head_position(target)
                            coordinator.set_feet_position(target)
                        else:
                            all_ok = False
                elif target < head_current and target < feet_current:
                    phase1 = min(head_duration_sec, feet_duration_sec)
                    ok = await coordinator.async_run_movement_for_duration(CMD_BOTH_DOWN, phase1)
                    if not ok:
                        all_ok = False
                    else:
                        head_remaining = head_duration_sec - phase1
                        feet_remaining = feet_duration_sec - phase1
                        if head_remaining > 0.1:
                            await asyncio.sleep(0.5)
                            ok = await coordinator.async_run_movement_for_duration(CMD_HEAD_DOWN, head_remaining)
                        elif feet_remaining > 0.1:
                            await asyncio.sleep(0.5)
                            ok = await coordinator.async_run_movement_for_duration(CMD_FEET_DOWN, feet_remaining)
                        else:
                            ok = True
                        if ok:
                            coordinator.set_head_position(target)
                            coordinator.set_feet_position(target)
                        else:
                            all_ok = False
                else:
                    if head_diff >= 0.5:
                        cmd = CMD_HEAD_UP if target > head_current else CMD_HEAD_DOWN
                        head_ok = await coordinator.async_run_movement_for_duration(
                            cmd, head_duration_sec
                        )
                    else:
                        head_ok = True
                    if feet_diff >= 0.5:
                        await asyncio.sleep(0.5)
                        cmd = CMD_FEET_UP if target > feet_current else CMD_FEET_DOWN
                        feet_ok = await coordinator.async_run_movement_for_duration(
                            cmd, feet_duration_sec
                        )
                    else:
                        feet_ok = True
                    if head_ok and feet_ok:
                        coordinator.set_head_position(target)
                        coordinator.set_feet_position(target)
                    else:
                        all_ok = False
                if all_ok or (head_diff < 0.5 and feet_diff < 0.5):
                    break
                if attempt == 0:
                    await asyncio.sleep(0.5)
            self.async_write_ha_state()
        finally:
            coordinator.set_movement_active(False)


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
