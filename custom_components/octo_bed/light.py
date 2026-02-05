"""Light entity for Octo Bed (bed light)."""

from __future__ import annotations

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity


class OctoBedLightEntity(OctoBedEntity, LightEntity):
    """Bed light controlled via BLE."""

    _attr_name = "Light"
    _attr_unique_id = "light"
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.light_on

    async def async_turn_on(self, **kwargs) -> None:
        ok = await self.coordinator.async_set_light(True)
        if ok:
            self.coordinator.set_light_on(True)
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        ok = await self.coordinator.async_set_light(False)
        if ok:
            self.coordinator.set_light_on(False)
            self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Octo Bed light."""
    coordinator: OctoBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OctoBedLightEntity(coordinator, entry)])
