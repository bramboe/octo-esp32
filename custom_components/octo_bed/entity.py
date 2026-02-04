"""Base entity for Octo Bed."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OctoBedCoordinator


class OctoBedEntity(CoordinatorEntity[OctoBedCoordinator], Entity):
    """Base class for Octo Bed entities."""

    def __init__(self, coordinator: OctoBedCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Octo Bed",
            model="BLE Remote",
        )

    @property
    def available(self) -> bool:
        return self.coordinator._device_address is not None and super().available
