"""Config flow for Octo Bed integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_FEET_CALIBRATION_SEC,
    CONF_HEAD_CALIBRATION_SEC,
    CONF_PIN,
    DEFAULT_DEVICE_NAME,
    DEFAULT_FEET_CALIBRATION_SEC,
    DEFAULT_HEAD_CALIBRATION_SEC,
    DEFAULT_PIN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME, default=DEFAULT_DEVICE_NAME): str,
        vol.Optional(CONF_DEVICE_ADDRESS, default=""): str,
        vol.Required(CONF_PIN, default=DEFAULT_PIN): str,
        vol.Required(CONF_HEAD_CALIBRATION_SEC, default=DEFAULT_HEAD_CALIBRATION_SEC): vol.Coerce(float),
        vol.Required(CONF_FEET_CALIBRATION_SEC, default=DEFAULT_FEET_CALIBRATION_SEC): vol.Coerce(float),
    }
)


def _normalize_mac(mac: str) -> str:
    """Normalize MAC to 12 hex chars uppercase, no colons."""
    if not mac or not mac.strip():
        return ""
    cleaned = "".join(c for c in mac.strip() if c in "0123456789AaBbCcDdEeFf")
    return cleaned.upper() if len(cleaned) == 12 else ""


def _format_mac_display(mac: str) -> str:
    """Format 12 hex chars as AA:BB:CC:DD:EE:FF."""
    mac = _normalize_mac(mac)
    if len(mac) != 12:
        return mac
    return ":".join(mac[i : i + 2] for i in range(0, 12, 2))


class OctoBedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Octo Bed config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            device_name = (user_input.get(CONF_DEVICE_NAME) or DEFAULT_DEVICE_NAME).strip()
            raw_mac = (user_input.get(CONF_DEVICE_ADDRESS) or "").strip()
            pin = (user_input.get(CONF_PIN) or DEFAULT_PIN).strip()[:4].ljust(4, "0")
            head_sec = float(user_input.get(CONF_HEAD_CALIBRATION_SEC, DEFAULT_HEAD_CALIBRATION_SEC))
            feet_sec = float(user_input.get(CONF_FEET_CALIBRATION_SEC, DEFAULT_FEET_CALIBRATION_SEC))
            head_sec = max(1.0, min(120.0, head_sec))
            feet_sec = max(1.0, min(120.0, feet_sec))

            normalized_mac = _normalize_mac(raw_mac)
            if raw_mac and len(normalized_mac) != 12:
                return self.async_show_form(
                    step_id="user",
                    data_schema=STEP_USER_SCHEMA,
                    errors={"base": "invalid_mac"},
                )

            data = {
                CONF_DEVICE_NAME: device_name,
                CONF_PIN: pin,
                CONF_HEAD_CALIBRATION_SEC: head_sec,
                CONF_FEET_CALIBRATION_SEC: feet_sec,
            }
            if normalized_mac:
                data[CONF_DEVICE_ADDRESS] = _format_mac_display(normalized_mac)

            return self.async_create_entry(title=f"Octo Bed ({device_name})", data=data)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OctoBedOptionsFlow:
        return OctoBedOptionsFlow(config_entry)


class OctoBedOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Octo Bed."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            head_sec = max(1.0, min(120.0, float(user_input.get(CONF_HEAD_CALIBRATION_SEC, 30))))
            feet_sec = max(1.0, min(120.0, float(user_input.get(CONF_FEET_CALIBRATION_SEC, 30))))
            return self.async_create_entry(
                data={
                    CONF_HEAD_CALIBRATION_SEC: head_sec,
                    CONF_FEET_CALIBRATION_SEC: feet_sec,
                }
            )

        head = self._entry.options.get(
            CONF_HEAD_CALIBRATION_SEC,
            self._entry.data.get(CONF_HEAD_CALIBRATION_SEC, DEFAULT_HEAD_CALIBRATION_SEC),
        )
        feet = self._entry.options.get(
            CONF_FEET_CALIBRATION_SEC,
            self._entry.data.get(CONF_FEET_CALIBRATION_SEC, DEFAULT_FEET_CALIBRATION_SEC),
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_HEAD_CALIBRATION_SEC, default=head): vol.Coerce(float),
                vol.Required(CONF_FEET_CALIBRATION_SEC, default=feet): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
