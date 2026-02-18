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
        # Ensure unique_id is scoped to this config entry (avoids duplicates with multiple beds)
        if getattr(self, "_attr_unique_id", None) and not str(
            self._attr_unique_id
        ).startswith(entry.entry_id):
            self._attr_unique_id = f"{entry.entry_id}_{self._attr_unique_id}"

    @property
    def available(self) -> bool:
        # Stay available when we have an address – don't go unavailable on coordinator refresh
        # failures (BLE hiccups). Connection status entity still shows connected/off.
        return self.coordinator.device_address is not None
