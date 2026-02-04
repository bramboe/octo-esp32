"""Services for Octo Bed (set head/feet position from automations)."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from .const import DOMAIN
from .coordinator import OctoBedCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_HEAD_POSITION = "set_head_position"
SERVICE_SET_FEET_POSITION = "set_feet_position"

ATTR_POSITION = "position"

SET_POSITION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_POSITION): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    }
)


def _get_coordinator(hass: HomeAssistant) -> OctoBedCoordinator | None:
    """Return the first (typically only) Octo Bed coordinator."""
    for entry_id, coord in (hass.data.get(DOMAIN) or {}).items():
        if isinstance(coord, OctoBedCoordinator):
            return coord
    return None


async def async_set_head_position(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set head position to 0-100% (like cover set_position)."""
    coordinator = _get_coordinator(hass)
    if not coordinator:
        _LOGGER.warning("Octo Bed: no device found for service call")
        return
    position = call.data[ATTR_POSITION]
    await coordinator.async_set_head_position(position)


async def async_set_feet_position(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set feet position to 0-100% (like cover set_position)."""
    coordinator = _get_coordinator(hass)
    if not coordinator:
        _LOGGER.warning("Octo Bed: no device found for service call")
        return
    position = call.data[ATTR_POSITION]
    await coordinator.async_set_feet_position(position)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Octo Bed services."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_HEAD_POSITION):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_HEAD_POSITION,
        async_set_head_position,
        schema=SET_POSITION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FEET_POSITION,
        async_set_feet_position,
        schema=SET_POSITION_SCHEMA,
    )


