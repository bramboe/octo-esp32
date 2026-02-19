"""Binary sensors for Octo Bed (calibration active, connection status)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity


class OctoBedCalibrationActiveBinarySensor(OctoBedEntity, BinarySensorEntity):
    """Whether calibration is in progress (head or feet)."""

    _attr_name = "Calibration active"
    _attr_unique_id = "calibration_active"
    _attr_device_class = "running"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.coordinator.calibration_active

    @property
    def available(self) -> bool:
        return True


class OctoBedConnectionBinarySensor(OctoBedEntity, BinarySensorEntity):
    """On when the bed is authenticated: correct PIN accepted and commands work. Off when not authenticated or device not in range."""

    _attr_name = "Connection status"
    _attr_unique_id = "connection_status"
    _attr_device_class = "connectivity"

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("connected"))

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        data = self.coordinator.data or {}
        status = data.get("connection_status", "disconnected")
        if status == "connected":
            return {}
        if status == "searching":
            return {"status": "searching for device"}
        if status == "pin_not_accepted":
            return {"status": "PIN not accepted"}
        return {"status": "disconnected"}

    @property
    def available(self) -> bool:
        return self.coordinator.device_address is not None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Octo Bed binary sensors."""
    coordinator: OctoBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        OctoBedCalibrationActiveBinarySensor(coordinator, entry),
        OctoBedConnectionBinarySensor(coordinator, entry),
    ])
