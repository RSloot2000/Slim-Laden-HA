"""Laadmodus-select voor Peblar Slim Laden."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LAADMODI, SET_LAADMODUS
from .coordinator import PeblarCoordinator
from .entity import PeblarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PeblarLaadmodusSelect(coordinator)])


class PeblarLaadmodusSelect(PeblarEntity, SelectEntity):
    _attr_name = "Laadmodus"
    _attr_icon = "mdi:ev-station"
    _attr_options = LAADMODI

    def __init__(self, coordinator: PeblarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{SET_LAADMODUS}"

    @property
    def current_option(self) -> str | None:
        return self.coordinator.get_setting(SET_LAADMODUS)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_setting(SET_LAADMODUS, option)
        self.async_write_ha_state()
