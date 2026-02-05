"""Octo Bed - BLE bed control via Bluetooth Proxy."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import OctoBedCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.COVER,
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Octo Bed integration (YAML not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Octo Bed from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = OctoBedCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    async_setup_services(hass)

    # Start keep-alive loop only after HA has finished starting (avoids blocking bootstrap).
    # Must schedule on the event loop: EVENT_HOMEASSISTANT_STARTED can fire from a thread.
    def _start_keep_alive(_event=None) -> None:
        hass.loop.call_soon_threadsafe(coordinator.start_keep_alive_loop)

    if hass.is_running:
        coordinator.start_keep_alive_loop()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start_keep_alive)
        )
    entry.async_on_unload(coordinator.cancel_keep_alive_loop)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
