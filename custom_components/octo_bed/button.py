"""Button entities for Octo Bed (stop, search, keep-alive)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
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
    ])
