"""Switch entities for Octo Bed (continuous head/feet up/down - hold to move)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity

_LOGGER = logging.getLogger(__name__)


class OctoBedMovementSwitch(OctoBedEntity, SwitchEntity):
    """Base switch that runs movement while on."""

    _cmd_up = None
    _cmd_down = None
    _position_key = "head"  # "head" or "feet"
    _cal_key = "head"  # "head" or "feet"
    _task: asyncio.Task | None = None

    async def _run_loop(self, direction_up: bool) -> None:
        coordinator = self.coordinator
        coordinator.set_movement_active(True)
        try:
            while self._task and not self._task.cancelled():
                if direction_up:
                    await (coordinator.async_send_head_up() if self._cal_key == "head" else coordinator.async_send_feet_up())
                else:
                    await (coordinator.async_send_head_down() if self._cal_key == "head" else coordinator.async_send_feet_down())
                await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            pass
        finally:
            await coordinator.async_send_stop()
            coordinator.set_movement_active(False)
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._task and not self._task.done():
            return
        # Subclasses set _direction_up so we know which way to move
        self._task = asyncio.create_task(self._run_loop(direction_up=getattr(self, "_direction_up", True)))
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.coordinator.async_send_stop()
        self.coordinator.set_movement_active(False)
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
    ])
