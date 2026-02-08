"""Config flow for Octo Bed integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth, persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_DEVICE_NICKNAME,
    CONF_FEET_CALIBRATION_SEC,
    CONF_HEAD_CALIBRATION_SEC,
    CONF_PIN,
    DEFAULT_DEVICE_NAME,
    DEFAULT_FEET_CALIBRATION_SEC,
    DEFAULT_HEAD_CALIBRATION_SEC,
    DEFAULT_PIN,
    DOMAIN,
)
from .coordinator import set_pin_on_device_during_config, validate_pin_with_probe

_LOGGER = logging.getLogger(__name__)

# Max time for probe + PIN validation or set-PIN so the flow never hangs (progress task timeout)
VALIDATION_TIMEOUT_SEC = 75

CONF_PIN_MODE = "pin_mode"
PIN_MODE_SET_NEW = "set_new"
PIN_MODE_USE_EXISTING = "use_existing"


async def _validation_with_timeout(hass: HomeAssistant, address: str, device_name: str, pin: str) -> str:
    """Run validate_pin_with_probe with a timeout; return 'timeout' on timeout."""
    try:
        return await asyncio.wait_for(
            validate_pin_with_probe(hass, address, device_name, pin),
            timeout=VALIDATION_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        _LOGGER.warning("PIN validation timed out after %s seconds", VALIDATION_TIMEOUT_SEC)
        return "timeout"


async def _set_pin_with_timeout(hass: HomeAssistant, address: str, device_name: str, pin: str) -> str:
    """Run set_pin_on_device_during_config with a timeout; return 'timeout' on timeout."""
    try:
        return await asyncio.wait_for(
            set_pin_on_device_during_config(hass, address, device_name, pin),
            timeout=VALIDATION_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        _LOGGER.warning("Set PIN timed out after %s seconds", VALIDATION_TIMEOUT_SEC)
        return "timeout"


def _pin_result_to_error(result: str) -> str:
    """Map validation/set_pin result to config flow error key."""
    if result == "timeout":
        return "connection_timeout"
    if result == "no_pin_check":
        return "no_pin_check"
    if result == "set_pin_failed":
        return "set_pin_failed"
    return "invalid_pin"


def _confirm_bluetooth_schema(pending: dict[str, Any] | None = None) -> vol.Schema:
    """Schema for confirm_bluetooth step (pin_mode, pin, nickname)."""
    pending = pending or {}
    return vol.Schema({
        vol.Required(
            CONF_PIN_MODE,
            default=pending.get(CONF_PIN_MODE, PIN_MODE_SET_NEW),
        ): vol.In({
            PIN_MODE_SET_NEW: "Set a new PIN on the bed (no app needed)",
            PIN_MODE_USE_EXISTING: "I already know the current PIN",
        }),
        vol.Required(CONF_PIN, default=pending.get("pin", DEFAULT_PIN)): str,
        vol.Optional(CONF_DEVICE_NICKNAME, default=pending.get("nickname", "")): str,
    })


def _manual_schema(pending: dict[str, Any] | None = None) -> vol.Schema:
    """Schema for manual step (device name, MAC, pin_mode, pin, nickname)."""
    pending = pending or {}
    return vol.Schema({
        vol.Required(CONF_DEVICE_NAME, default=pending.get("device_name", DEFAULT_DEVICE_NAME)): str,
        vol.Required(CONF_DEVICE_ADDRESS, default=pending.get("addr", "")): str,
        vol.Optional(CONF_DEVICE_NICKNAME, default=pending.get("nickname", "")): str,
        vol.Required(
            CONF_PIN_MODE,
            default=pending.get(CONF_PIN_MODE, PIN_MODE_SET_NEW),
        ): vol.In({
            PIN_MODE_SET_NEW: "Set a new PIN on the bed (no app needed)",
            PIN_MODE_USE_EXISTING: "I already know the current PIN",
        }),
        vol.Required(CONF_PIN, default=pending.get("pin", DEFAULT_PIN)): str,
    })


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME, default=DEFAULT_DEVICE_NAME): str,
        vol.Required(CONF_DEVICE_ADDRESS, default=""): str,
        vol.Optional(CONF_DEVICE_NICKNAME, default=""): str,
        vol.Required(CONF_PIN_MODE, default=PIN_MODE_SET_NEW): vol.In({
            PIN_MODE_SET_NEW: "Set a new PIN on the bed (no app needed)",
            PIN_MODE_USE_EXISTING: "I already know the current PIN",
        }),
        vol.Required(CONF_PIN, default=DEFAULT_PIN): str,
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


def _format_mac_for_options(entry: config_entries.ConfigEntry) -> str:
    """Current MAC from entry for options form (empty string if not set)."""
    return entry.data.get(CONF_DEVICE_ADDRESS) or ""


def _entry_title_from_data(data: dict[str, Any]) -> str:
    """Build device title: Octo Bed (nickname) or Octo Bed (MAC address)."""
    nickname = (data.get(CONF_DEVICE_NICKNAME) or "").strip()
    if nickname:
        return f"Octo Bed ({nickname})"
    addr = data.get(CONF_DEVICE_ADDRESS) or ""
    if addr:
        return f"Octo Bed ({addr})"
    return f"Octo Bed ({data.get(CONF_DEVICE_NAME, 'Octo Bed')})"


class OctoBedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Octo Bed config flow."""

    VERSION = 1

    def _address_already_configured(self, address: str) -> bool:
        """Check if this Bluetooth address is already configured."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_DEVICE_ADDRESS, "").upper() == address.upper():
                return True
        return False

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfo
    ) -> FlowResult:
        """Handle a flow started by Bluetooth discovery (automatic or from scan)."""
        address = discovery_info.address
        name = discovery_info.name or discovery_info.address
        _LOGGER.info("Discovered Octo Bed: %s (%s)", name, address)
        if self._address_already_configured(address):
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        # Show discovery in Home Assistant notifications
        persistent_notification.async_create(
            self.hass,
            f"**{name or 'Octo Bed'}**\n\nMAC address: `{address}`\n\nYou can add this device from the dialog that appeared, or go to **Settings** → **Devices & Services** → **Discovered**.",
            title="Octo Bed discovered",
            notification_id=f"octo_bed_discovery_{address.replace(':', '_')}",
        )
        return await self.async_step_confirm_bluetooth(name=name, address=address)

    async def async_step_confirm_bluetooth(
        self,
        user_input: dict[str, Any] | None = None,
        *,
        name: str = "",
        address: str = "",
    ) -> FlowResult:
        """Confirm and complete setup of a discovered device (PIN only; MAC/name come from discovery)."""
        # Re-entry after progress: result may be in context (survives flow re-invoke)
        stored_result = self.context.pop("_confirm_result", None)
        stored_pending = self.context.pop("_confirm_pending", None)
        if stored_result is not None and stored_pending is not None:
            if stored_result == "ok":
                data = {
                    CONF_DEVICE_NAME: stored_pending["name"],
                    CONF_DEVICE_ADDRESS: stored_pending["address"],
                    CONF_PIN: stored_pending["pin"],
                    CONF_HEAD_CALIBRATION_SEC: DEFAULT_HEAD_CALIBRATION_SEC,
                    CONF_FEET_CALIBRATION_SEC: DEFAULT_FEET_CALIBRATION_SEC,
                }
                if stored_pending.get("nickname"):
                    data[CONF_DEVICE_NICKNAME] = stored_pending["nickname"]
                self._pending_entry = (_entry_title_from_data(data), data)
                return self.async_show_progress_done(next_step_id="create_entry")
            # Show form with error
            err = _pin_result_to_error(stored_result)
            return self.async_show_form(
                step_id="confirm_bluetooth",
                data_schema=_confirm_bluetooth_schema(stored_pending),
                description_placeholders={
                    "name": stored_pending.get("name", "Octo Bed"),
                    "address": stored_pending.get("address", ""),
                    "mac": stored_pending.get("address", ""),
                },
                errors={"base": err},
            )

        # Resuming while "Testing connection..." progress is still running
        task = getattr(self, "_confirm_validate_task", None)
        if task is not None:
            if not task.done():
                return self.async_show_progress(
                    progress_action="testing_connection",
                    progress_task=task,
                )
            try:
                result = task.result()
            except Exception as e:
                _LOGGER.debug("Validation task error: %s", e)
                result = "wrong_pin"
            del self._confirm_validate_task
            pending = getattr(self, "_confirm_pending", {})
            # Store in context first so it survives the transition
            self.context["_confirm_result"] = result
            self.context["_confirm_pending"] = pending
            # Use a dedicated step for failure so HA always re-invokes and shows the form (fixes spinner on wrong PIN)
            if result == "ok":
                data = {
                    CONF_DEVICE_NAME: pending["name"],
                    CONF_DEVICE_ADDRESS: pending["address"],
                    CONF_PIN: pending["pin"],
                    CONF_HEAD_CALIBRATION_SEC: DEFAULT_HEAD_CALIBRATION_SEC,
                    CONF_FEET_CALIBRATION_SEC: DEFAULT_FEET_CALIBRATION_SEC,
                }
                if pending.get("nickname"):
                    data[CONF_DEVICE_NICKNAME] = pending["nickname"]
                self._pending_entry = (_entry_title_from_data(data), data)
                return self.async_show_progress_done(next_step_id="create_entry")
            return self.async_show_progress_done(next_step_id="confirm_bluetooth_show_error")

        if getattr(self, "_confirm_validation_failed", False):
            self._confirm_validation_failed = False
            no_pin_check = getattr(self, "_confirm_no_pin_check", False)
            timeout = getattr(self, "_confirm_timeout", False)
            for attr in ("_confirm_no_pin_check", "_confirm_timeout"):
                if hasattr(self, attr):
                    delattr(self, attr)
            pending = getattr(self, "_confirm_pending", {})
            err = "connection_timeout" if timeout else ("no_pin_check" if no_pin_check else "invalid_pin")
            return self.async_show_form(
                step_id="confirm_bluetooth",
                data_schema=_confirm_bluetooth_schema(pending),
                description_placeholders={
                    "name": pending.get("name", "Octo Bed"),
                    "address": pending.get("address", ""),
                    "mac": pending.get("address", ""),
                },
                errors={"base": err},
            )

        if user_input is not None:
            name = self.context.get("discovered_name", name) or "Octo Bed"
            address = (self.context.get("discovered_address", address) or "").strip()
            if not address and self.unique_id:
                address = self.unique_id
            if not address:
                return await self.async_step_manual()
            pin = (user_input.get(CONF_PIN) or DEFAULT_PIN).strip()[:4].ljust(4, "0")
            nickname = (user_input.get(CONF_DEVICE_NICKNAME) or "").strip()
            pin_mode = user_input.get(CONF_PIN_MODE, PIN_MODE_SET_NEW)
            self._confirm_pending = {"name": name or "Octo Bed", "address": address, "pin": pin, "nickname": nickname, CONF_PIN_MODE: pin_mode}
            if pin_mode == PIN_MODE_SET_NEW:
                task = _set_pin_with_timeout(self.hass, address, name or "Octo Bed", pin)
            else:
                task = _validation_with_timeout(self.hass, address, name or "Octo Bed", pin)
            self._confirm_validate_task = self.hass.async_create_task(task)
            return self.async_show_progress(
                progress_action="testing_connection",
                progress_task=self._confirm_validate_task,
            )

        self.context["discovered_name"] = name
        self.context["discovered_address"] = address
        if address and not self.unique_id:
            await self.async_set_unique_id(address)
        self.context["title_placeholders"] = {"name": f"{name or 'Octo Bed'} ({address})"}
        return self.async_show_form(
            step_id="confirm_bluetooth",
            data_schema=_confirm_bluetooth_schema(None),
            description_placeholders={
                "name": name or "Octo Bed",
                "address": address,
                "mac": address,
            },
        )

    async def async_step_confirm_bluetooth_show_error(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show PIN error form after validation failed. Retry runs validation inline to avoid spinner stuck on second wrong PIN."""
        if user_input is not None:
            retry = self.context.pop("_confirm_retry_pending", None)
            if retry:
                pin = (user_input.get(CONF_PIN) or DEFAULT_PIN).strip()[:4].ljust(4, "0")
                nickname = (user_input.get(CONF_DEVICE_NICKNAME) or "").strip()
                pin_mode = user_input.get(CONF_PIN_MODE, PIN_MODE_SET_NEW)
                name = retry.get("name", "Octo Bed")
                address = retry.get("address", "")
                if pin_mode == PIN_MODE_SET_NEW:
                    result = await _set_pin_with_timeout(self.hass, address, name, pin)
                else:
                    result = await _validation_with_timeout(self.hass, address, name, pin)
                if result == "ok":
                    data = {
                        CONF_DEVICE_NAME: name,
                        CONF_DEVICE_ADDRESS: address,
                        CONF_PIN: pin,
                        CONF_HEAD_CALIBRATION_SEC: DEFAULT_HEAD_CALIBRATION_SEC,
                        CONF_FEET_CALIBRATION_SEC: DEFAULT_FEET_CALIBRATION_SEC,
                    }
                    if nickname:
                        data[CONF_DEVICE_NICKNAME] = nickname
                    return self.async_create_entry(title=_entry_title_from_data(data), data=data)
                err = _pin_result_to_error(result)
                retry_pending = {"name": name, "address": address, "pin": pin, "nickname": nickname, CONF_PIN_MODE: pin_mode}
                self.context["_confirm_retry_pending"] = retry_pending
                return self.async_show_form(
                    step_id="confirm_bluetooth_show_error",
                    data_schema=_confirm_bluetooth_schema(retry_pending),
                    description_placeholders={"name": name, "address": address, "mac": address},
                    errors={"base": err},
                )
        stored_result = self.context.pop("_confirm_result", None)
        stored_pending = self.context.pop("_confirm_pending", None)
        if stored_result is None or stored_pending is None:
            return await self.async_step_confirm_bluetooth()
        err = _pin_result_to_error(stored_result)
        self.context["_confirm_retry_pending"] = stored_pending
        return self.async_show_form(
            step_id="confirm_bluetooth_show_error",
            data_schema=_confirm_bluetooth_schema(stored_pending),
            description_placeholders={
                "name": stored_pending.get("name", "Octo Bed"),
                "address": stored_pending.get("address", ""),
                "mac": stored_pending.get("address", ""),
            },
            errors={"base": err},
        )

    async def async_step_create_entry(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Create the config entry after successful PIN validation."""
        title, data = self._pending_entry
        return self.async_create_entry(title=title, data=data)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step: choose scan or manual."""
        if user_input is not None:
            if user_input.get("next_step") == "scan":
                return await self.async_step_scan()
            return await self.async_step_manual()

        schema = vol.Schema(
            {
                vol.Required("next_step", default="scan"): vol.In({
                    "scan": "Search for nearby beds",
                    "manual": "Enter details manually",
                }),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    def _is_octo_bed_candidate(self, info: bluetooth.BluetoothServiceInfo) -> bool:
        """True if this device looks like an Octo Bed remote (FFE0 service or RC2/octo name)."""
        # service_uuids can be UUID objects or strings; normalize to string for "ffe0" check
        for u in info.service_uuids or []:
            if "ffe0" in str(u).lower():
                return True
        name = (info.name or "").strip()
        return bool(name and (name.upper() == "RC2" or "octo" in name.lower()))

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Scan for nearby Octo Bed remotes and let user pick one."""
        if user_input is not None:
            picked = user_input.get("picked")
            if picked and "|" in picked:
                name, address = picked.split("|", 1)
                return await self.async_step_confirm_bluetooth(name=name.strip(), address=address.strip())
            return await self.async_step_manual()

        # Include both connectable and non-connectable so we see devices from all adapters (e.g. proxy)
        infos_conn = bluetooth.async_discovered_service_info(self.hass, connectable=True)
        infos_any = bluetooth.async_discovered_service_info(self.hass, connectable=False)
        # Prefer connectable; merge by normalized address so we don't duplicate (address may be with/without colons)
        by_addr: dict[str, bluetooth.BluetoothServiceInfo] = {}
        for info in infos_conn:
            canonical = _normalize_mac(info.address or "")
            if canonical:
                by_addr[canonical] = info
        for info in infos_any:
            canonical = _normalize_mac(info.address or "")
            if canonical and canonical not in by_addr:
                by_addr[canonical] = info
        infos = list(by_addr.values())

        existing = {_normalize_mac(e.data.get(CONF_DEVICE_ADDRESS, "")) for e in self._async_current_entries()}
        devices = []
        seen: set[str] = set()
        for info in infos:
            canonical = _normalize_mac(info.address or "")
            if not canonical or canonical in seen or canonical in existing:
                continue
            if not self._is_octo_bed_candidate(info):
                continue
            seen.add(canonical)
            name = (info.name or "").strip()
            display_addr = info.address or _format_mac_display(canonical)
            label = f"{display_addr} — {name or 'Octo Bed'}"
            value = f"{name or display_addr}|{display_addr}"
            devices.append((label, value))

        if not devices:
            sample = [
                (getattr(i, "name", None), getattr(i, "address", None), [str(u) for u in (getattr(i, "service_uuids", None) or [])[:3]])
                for i in infos[:5]
            ]
            _LOGGER.debug(
                "Octo Bed scan: no candidates in %s discovered device(s). Sample (name, address, uuids): %s",
                len(infos),
                sample,
            )
            schema = vol.Schema(
                {
                    vol.Required("continue_manual"): vol.In({"manual": "Enter details manually"}),
                }
            )
            return self.async_show_form(
                step_id="scan",
                data_schema=schema,
                errors={"base": "no_devices_found"},
                description_placeholders={"msg": "No new Octo Bed remotes found. Ensure remotes are on and in range of your Bluetooth proxy."},
            )
        schema = vol.Schema(
            {
                vol.Required("picked"): vol.In({v: k for k, v in devices}),
            }
        )
        return self.async_show_form(
            step_id="scan",
            data_schema=schema,
            description_placeholders={"count": str(len(devices))},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manual entry (device name, MAC, device name/nickname, PIN)."""
        # Re-entry after progress: result in context (survives flow re-invoke)
        stored_result = self.context.pop("_manual_result", None)
        stored_pending = self.context.pop("_manual_pending", None)
        if stored_result is not None and stored_pending is not None:
            if stored_result == "ok":
                data = {
                    CONF_DEVICE_NAME: stored_pending["device_name"],
                    CONF_DEVICE_ADDRESS: stored_pending["addr"],
                    CONF_PIN: stored_pending["pin"],
                    CONF_HEAD_CALIBRATION_SEC: DEFAULT_HEAD_CALIBRATION_SEC,
                    CONF_FEET_CALIBRATION_SEC: DEFAULT_FEET_CALIBRATION_SEC,
                }
                if stored_pending.get("nickname"):
                    data[CONF_DEVICE_NICKNAME] = stored_pending["nickname"]
                self._pending_entry = (_entry_title_from_data(data), data)
                return self.async_show_progress_done(next_step_id="create_entry")
            err = _pin_result_to_error(stored_result)
            return self.async_show_form(step_id="manual", data_schema=_manual_schema(stored_pending), errors={"base": err})

        task = getattr(self, "_manual_validate_task", None)
        if task is not None:
            if not task.done():
                return self.async_show_progress(
                    progress_action="testing_connection",
                    progress_task=task,
                )
            try:
                result = task.result()
            except Exception as e:
                _LOGGER.debug("Validation task error: %s", e)
                result = "wrong_pin"
            del self._manual_validate_task
            pending = getattr(self, "_manual_pending", {})
            self.context["_manual_result"] = result
            self.context["_manual_pending"] = pending
            if result == "ok":
                data = {
                    CONF_DEVICE_NAME: pending["device_name"],
                    CONF_DEVICE_ADDRESS: pending["addr"],
                    CONF_PIN: pending["pin"],
                    CONF_HEAD_CALIBRATION_SEC: DEFAULT_HEAD_CALIBRATION_SEC,
                    CONF_FEET_CALIBRATION_SEC: DEFAULT_FEET_CALIBRATION_SEC,
                }
                if pending.get("nickname"):
                    data[CONF_DEVICE_NICKNAME] = pending["nickname"]
                self._pending_entry = (_entry_title_from_data(data), data)
                return self.async_show_progress_done(next_step_id="create_entry")
            return self.async_show_progress_done(next_step_id="manual_show_error")

        if getattr(self, "_manual_validation_failed", False):
            self._manual_validation_failed = False
            no_pin_check = getattr(self, "_manual_no_pin_check", False)
            timeout = getattr(self, "_manual_timeout", False)
            for attr in ("_manual_no_pin_check", "_manual_timeout"):
                if hasattr(self, attr):
                    delattr(self, attr)
            pending = getattr(self, "_manual_pending", {})
            err = "connection_timeout" if timeout else ("no_pin_check" if no_pin_check else "invalid_pin")
            return self.async_show_form(
                step_id="manual",
                data_schema=_manual_schema(pending),
                errors={"base": err},
            )

        if user_input is not None:
            device_name = (user_input.get(CONF_DEVICE_NAME) or DEFAULT_DEVICE_NAME).strip()
            raw_mac = (user_input.get(CONF_DEVICE_ADDRESS) or "").strip()
            pin = (user_input.get(CONF_PIN) or DEFAULT_PIN).strip()[:4].ljust(4, "0")
            pin_mode = user_input.get(CONF_PIN_MODE, PIN_MODE_SET_NEW)

            normalized_mac = _normalize_mac(raw_mac)
            if not raw_mac:
                return self.async_show_form(
                    step_id="manual",
                    data_schema=STEP_USER_SCHEMA,
                    errors={"base": "mac_required"},
                )
            if len(normalized_mac) != 12:
                return self.async_show_form(
                    step_id="manual",
                    data_schema=STEP_USER_SCHEMA,
                    errors={"base": "invalid_mac"},
                )

            nickname = (user_input.get(CONF_DEVICE_NICKNAME) or "").strip()
            addr = _format_mac_display(normalized_mac)
            self._manual_pending = {"device_name": device_name, "addr": addr, "pin": pin, "nickname": nickname, CONF_PIN_MODE: pin_mode}
            if pin_mode == PIN_MODE_SET_NEW:
                task = _set_pin_with_timeout(self.hass, addr, device_name, pin)
            else:
                task = _validation_with_timeout(self.hass, addr, device_name, pin)
            self._manual_validate_task = self.hass.async_create_task(task)
            return self.async_show_progress(
                progress_action="testing_connection",
                progress_task=self._manual_validate_task,
            )

        return self.async_show_form(step_id="manual", data_schema=STEP_USER_SCHEMA)

    async def async_step_manual_show_error(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show PIN error form after validation failed. Retry runs validation inline to avoid spinner stuck on second wrong PIN."""
        if user_input is not None:
            device_name = (user_input.get(CONF_DEVICE_NAME) or DEFAULT_DEVICE_NAME).strip()
            raw_mac = (user_input.get(CONF_DEVICE_ADDRESS) or "").strip()
            pin = (user_input.get(CONF_PIN) or DEFAULT_PIN).strip()[:4].ljust(4, "0")
            nickname = (user_input.get(CONF_DEVICE_NICKNAME) or "").strip()
            pin_mode = user_input.get(CONF_PIN_MODE, PIN_MODE_SET_NEW)
            normalized_mac = _normalize_mac(raw_mac)
            if not raw_mac or len(normalized_mac) != 12:
                pending = {"device_name": device_name, "addr": raw_mac, "pin": pin, "nickname": nickname, CONF_PIN_MODE: pin_mode}
                return self.async_show_form(step_id="manual_show_error", data_schema=_manual_schema(pending), errors={"base": "invalid_mac" if raw_mac else "mac_required"})
            addr = _format_mac_display(normalized_mac)
            if pin_mode == PIN_MODE_SET_NEW:
                result = await _set_pin_with_timeout(self.hass, addr, device_name, pin)
            else:
                result = await _validation_with_timeout(self.hass, addr, device_name, pin)
            if result == "ok":
                data = {
                    CONF_DEVICE_NAME: device_name,
                    CONF_DEVICE_ADDRESS: addr,
                    CONF_PIN: pin,
                    CONF_HEAD_CALIBRATION_SEC: DEFAULT_HEAD_CALIBRATION_SEC,
                    CONF_FEET_CALIBRATION_SEC: DEFAULT_FEET_CALIBRATION_SEC,
                }
                if nickname:
                    data[CONF_DEVICE_NICKNAME] = nickname
                return self.async_create_entry(title=_entry_title_from_data(data), data=data)
            err = _pin_result_to_error(result)
            pending = {"device_name": device_name, "addr": raw_mac, "pin": pin, "nickname": nickname, CONF_PIN_MODE: pin_mode}
            return self.async_show_form(step_id="manual_show_error", data_schema=_manual_schema(pending), errors={"base": err})
        stored_result = self.context.pop("_manual_result", None)
        stored_pending = self.context.pop("_manual_pending", None)
        if stored_result is None or stored_pending is None:
            return await self.async_step_manual()
        err = _pin_result_to_error(stored_result)
        return self.async_show_form(
            step_id="manual_show_error",
            data_schema=_manual_schema(stored_pending),
            errors={"base": err},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OctoBedOptionsFlow:
        return OctoBedOptionsFlow(config_entry)


class OctoBedOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Octo Bed (calibration, MAC, PIN)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options: calibration seconds, optional MAC, optional PIN."""
        if user_input is not None:
            head_sec = max(1.0, min(120.0, float(user_input.get(CONF_HEAD_CALIBRATION_SEC, 30))))
            feet_sec = max(1.0, min(120.0, float(user_input.get(CONF_FEET_CALIBRATION_SEC, 30))))
            raw_mac = (user_input.get(CONF_DEVICE_ADDRESS) or "").strip()
            pin = (user_input.get(CONF_PIN) or DEFAULT_PIN).strip()[:4].ljust(4, "0")
            normalized_mac = _normalize_mac(raw_mac)
            if raw_mac and len(normalized_mac) != 12:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(),
                    errors={"base": "invalid_mac"},
                )
            nickname = (user_input.get(CONF_DEVICE_NICKNAME) or "").strip()
            new_data = {**self._entry.data}
            new_data[CONF_HEAD_CALIBRATION_SEC] = head_sec
            new_data[CONF_FEET_CALIBRATION_SEC] = feet_sec
            new_data[CONF_PIN] = pin
            if normalized_mac:
                new_data[CONF_DEVICE_ADDRESS] = _format_mac_display(normalized_mac)
            elif raw_mac == "":
                new_data.pop(CONF_DEVICE_ADDRESS, None)
            if nickname:
                new_data[CONF_DEVICE_NICKNAME] = nickname
            else:
                new_data.pop(CONF_DEVICE_NICKNAME, None)
            title = _entry_title_from_data(new_data)
            self.hass.config_entries.async_update_entry(
                self._entry, data=new_data, title=title
            )
            return self.async_create_entry(
                data={
                    CONF_HEAD_CALIBRATION_SEC: head_sec,
                    CONF_FEET_CALIBRATION_SEC: feet_sec,
                }
            )

        return self.async_show_form(step_id="init", data_schema=self._schema())

    def _schema(self) -> vol.Schema:
        head = self._entry.options.get(
            CONF_HEAD_CALIBRATION_SEC,
            self._entry.data.get(CONF_HEAD_CALIBRATION_SEC, DEFAULT_HEAD_CALIBRATION_SEC),
        )
        feet = self._entry.options.get(
            CONF_FEET_CALIBRATION_SEC,
            self._entry.data.get(CONF_FEET_CALIBRATION_SEC, DEFAULT_FEET_CALIBRATION_SEC),
        )
        mac = _format_mac_for_options(self._entry)
        pin = self._entry.data.get(CONF_PIN, DEFAULT_PIN)
        nickname = self._entry.data.get(CONF_DEVICE_NICKNAME, "")
        return vol.Schema(
            {
                vol.Required(CONF_HEAD_CALIBRATION_SEC, default=head): vol.Coerce(float),
                vol.Required(CONF_FEET_CALIBRATION_SEC, default=feet): vol.Coerce(float),
                vol.Optional(CONF_DEVICE_NICKNAME, default=nickname): str,
                vol.Optional(CONF_DEVICE_ADDRESS, default=mac): str,
                vol.Required(CONF_PIN, default=pin): str,
            }
        )
