"""Switch entities for Octo Bed (continuous head/feet up/down - hold to move)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    DOMAIN,
)
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity

_LOGGER = logging.getLogger(__name__)


class OctoBedMovementSwitch(OctoBedEntity, SwitchEntity):
    """Base switch that runs movement while on (single BLE connection for smooth movement)."""

    _cal_key = "head"  # "head" or "feet"
    _direction_up = True
    _task: asyncio.Task | None = None
    _stop_event: asyncio.Event | None = None

    def _get_command(self) -> bytes:
        if self._cal_key == "head":
            return CMD_HEAD_UP if self._direction_up else CMD_HEAD_DOWN
        return CMD_FEET_UP if self._direction_up else CMD_FEET_DOWN

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._task and not self._task.done():
            return
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self.coordinator.async_run_movement_loop(
                self._get_command(),
                self._stop_event.is_set,
            )
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._task is not None and not self._task.done()


class OctoBedHeadUpSwitch(OctoBedMovementSwitch):
    _attr_name = "Head Up"
    _attr_unique_id = "head_up"
    _cal_key = "head"
    _direction_up = True


class OctoBedHeadDownSwitch(OctoBedMovementSwitch):
    _attr_name = "Head Down"
    _attr_unique_id = "head_down"
    _cal_key = "head"
    _direction_up = False


class OctoBedFeetUpSwitch(OctoBedMovementSwitch):
    _attr_name = "Feet Up"
    _attr_unique_id = "feet_up"
    _cal_key = "feet"
    _direction_up = True


class OctoBedFeetDownSwitch(OctoBedMovementSwitch):
    _attr_name = "Feet Down"
    _attr_unique_id = "feet_down"
    _cal_key = "feet"
    _direction_up = False


class OctoBedBothUpSwitch(OctoBedEntity, SwitchEntity):
    """Both sections up (hold to move)."""

    _attr_name = "Both Up"
    _attr_unique_id = "both_up"
    _task: asyncio.Task | None = None
    _stop_event: asyncio.Event | None = None

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._task and not self._task.done():
            return
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self.coordinator.async_run_movement_loop(
                CMD_BOTH_UP,
                self._stop_event.is_set,
            )
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._task is not None and not self._task.done()


class OctoBedBothDownSwitch(OctoBedEntity, SwitchEntity):
    """Both sections down (hold to move)."""

    _attr_name = "Both Down"
    _attr_unique_id = "both_down"
    _task: asyncio.Task | None = None
    _stop_event: asyncio.Event | None = None

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._task and not self._task.done():
            return
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self.coordinator.async_run_movement_loop(
                CMD_BOTH_DOWN,
                self._stop_event.is_set,
            )
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._task is not None and not self._task.done()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Octo Bed movement switches."""
    coordinator: OctoBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        OctoBedHeadUpSwitch(coordinator, entry),
        OctoBedHeadDownSwitch(coordinator, entry),
        OctoBedFeetUpSwitch(coordinator, entry),
        OctoBedFeetDownSwitch(coordinator, entry),
        OctoBedBothUpSwitch(coordinator, entry),
        OctoBedBothDownSwitch(coordinator, entry),
    ])
