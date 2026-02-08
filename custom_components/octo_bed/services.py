"""Services for Octo Bed (set head/feet position, set PIN on device)."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import CONF_PIN, DOMAIN
from .coordinator import OctoBedCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_HEAD_POSITION = "set_head_position"
SERVICE_SET_FEET_POSITION = "set_feet_position"
SERVICE_SET_PIN = "set_pin"
SERVICE_SEND_SYSTEM_COMMAND = "send_system_command"

ATTR_POSITION = "position"
ATTR_PIN = "pin"
ATTR_DEVICE_ID = "device_id"
ATTR_COMMAND_FAMILY = "command_family"
ATTR_OPCODE = "opcode"

SET_POSITION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_POSITION): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    }
)

SET_PIN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PIN): vol.All(str, vol.Length(min=4, max=4), vol.Match(r"^\d{4}$")),
        vol.Optional(ATTR_DEVICE_ID): str,
    }
)

SEND_SYSTEM_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_COMMAND_FAMILY): vol.In(("short", "72")),
        vol.Required(ATTR_OPCODE): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
        vol.Optional(ATTR_DEVICE_ID): str,
    }
)


def _get_coordinator(hass: HomeAssistant, device_id: str | None = None) -> OctoBedCoordinator | None:
    """Return coordinator for the given device_id, or the first (single bed) if device_id is None."""
    domain_data = hass.data.get(DOMAIN) or {}
    if device_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(device_id)
        if not device or not device.config_entries:
            return None
        entry_id = next(iter(device.config_entries))
        coord = domain_data.get(entry_id)
        return coord if isinstance(coord, OctoBedCoordinator) else None
    for coord in domain_data.values():
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


async def async_set_pin(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set or change the PIN on the device (e.g. after hard reset). Sends 40 20 3c... and updates config."""
    device_id = call.data.get(ATTR_DEVICE_ID)
    if isinstance(device_id, dict):
        device_id = device_id.get("device_id")
    coordinator = _get_coordinator(hass, device_id)
    if not coordinator:
        _LOGGER.warning("Octo Bed: no device found for set_pin (check device_id)")
        return
    pin = call.data[ATTR_PIN].strip()[:4].ljust(4, "0")
    ok = await coordinator.async_set_pin_on_device(pin)
    if ok:
        new_data = {**coordinator._entry.data, CONF_PIN: pin}
        hass.config_entries.async_update_entry(coordinator._entry, data=new_data)
        _LOGGER.info("Octo Bed: PIN updated on device and in config")
    else:
        _LOGGER.warning("Octo Bed: set_pin failed (device did not accept or not in range)")


async def async_send_system_command(hass: HomeAssistant, call: ServiceCall) -> None:
    """Send a system command by family and opcode (for testing; check BLE status for response)."""
    device_id = call.data.get(ATTR_DEVICE_ID)
    if isinstance(device_id, dict):
        device_id = device_id.get("device_id")
    coordinator = _get_coordinator(hass, device_id)
    if not coordinator:
        _LOGGER.warning("Octo Bed: no device found for send_system_command (check device_id)")
        return
    family = call.data[ATTR_COMMAND_FAMILY]
    opcode = int(call.data[ATTR_OPCODE]) & 0xFF
    ok = await coordinator.async_send_system_command(family, opcode)
    if ok:
        _LOGGER.info("Octo Bed: sent system command %s opcode 0x%02X", family, opcode)
    else:
        _LOGGER.warning("Octo Bed: send_system_command failed (device not available)")


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
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PIN,
        async_set_pin,
        schema=SET_PIN_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SYSTEM_COMMAND,
        async_send_system_command,
        schema=SEND_SYSTEM_COMMAND_SCHEMA,
    )


