"""Sensors for Octo Bed (connection status, MAC address, BLE status)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity


class OctoBedConnectionSensor(OctoBedEntity, SensorEntity):
    """Sensor for BLE connection status (connected / disconnected)."""

    _attr_name = "Connection"
    _attr_unique_id = "connection"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = "diagnostic"

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return "disconnected"
        return "connected" if self.coordinator.data.get("connected") else "disconnected"

    @property
    def available(self) -> bool:
        return True


class OctoBedMacAddressSensor(OctoBedEntity, SensorEntity):
    """Sensor showing the remote's MAC address (or Not set / Discovering)."""

    _attr_name = "MAC address"
    _attr_unique_id = "mac_address"
    _attr_icon = "mdi:identifier"
    _attr_entity_category = "diagnostic"

    @property
    def native_value(self) -> str:
        addr = self.coordinator.device_address
        if addr:
            return addr
        return "Not set"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "device_name": self.coordinator.device_name,
        }

    @property
    def available(self) -> bool:
        return True


class OctoBedHeadPositionSensor(OctoBedEntity, SensorEntity):
    """Head position 0-100%% (for dashboards and automations)."""

    _attr_name = "Head position"
    _attr_unique_id = "head_position"
    _attr_icon = "mdi:angle-acute"
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        return round(self.coordinator.head_position, 1)

    @property
    def available(self) -> bool:
        return True


class OctoBedFeetPositionSensor(OctoBedEntity, SensorEntity):
    """Feet position 0-100%% (for dashboards and automations)."""

    _attr_name = "Feet position"
    _attr_unique_id = "feet_position"
    _attr_icon = "mdi:angle-acute"
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        return round(self.coordinator.feet_position, 1)

    @property
    def available(self) -> bool:
        return True


class OctoBedBleStatusSensor(OctoBedEntity, SensorEntity):
    """Combined BLE status (device name, connection, MAC) like the ESPHome YAML."""

    _attr_name = "BLE status"
    _attr_unique_id = "ble_status"
    _attr_icon = "mdi:bluetooth-settings"
    _attr_entity_category = "diagnostic"

    @property
    def native_value(self) -> str:
        name = self.coordinator.device_name
        connected = (
            self.coordinator.data or {}
        ).get("connected", False)
        status = "Connected" if connected else "Disconnected"
        value = f"{name} ({status})"
        addr = self.coordinator.device_address
        if addr:
            value += f" [MAC: {addr}]"
        return value

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        return {
            "device_name": self.coordinator.device_name,
            "mac_address": self.coordinator.device_address or "Not set",
            "connected": (self.coordinator.data or {}).get("connected", False),
        }

    @property
    def available(self) -> bool:
        return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Octo Bed sensors."""
    coordinator: OctoBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        OctoBedConnectionSensor(coordinator, entry),
        OctoBedMacAddressSensor(coordinator, entry),
        OctoBedBleStatusSensor(coordinator, entry),
        OctoBedHeadPositionSensor(coordinator, entry),
        OctoBedFeetPositionSensor(coordinator, entry),
    ])
