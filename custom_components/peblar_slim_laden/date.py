"""Vertrekdatum (date) voor Peblar Slim Laden (automatisch beheerd)."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SET_VERTREKDATUM
from .coordinator import PeblarCoordinator
from .entity import PeblarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PeblarVertrekdatum(coordinator)])


class PeblarVertrekdatum(PeblarEntity, DateEntity):
    _attr_name = "Vertrekdatum"
    _attr_icon = "mdi:calendar"

    def __init__(self, coordinator: PeblarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{SET_VERTREKDATUM}"

    @property
    def native_value(self) -> date | None:
        raw = self.coordinator.get_setting(SET_VERTREKDATUM)
        if not raw:
            return None
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    async def async_set_value(self, value: date) -> None:
        await self.coordinator.async_set_setting(
            SET_VERTREKDATUM, value.strftime("%Y-%m-%d")
        )
        self.async_write_ha_state()
