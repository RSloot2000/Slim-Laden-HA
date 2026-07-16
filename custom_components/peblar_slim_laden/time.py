"""Vertrektijd (time) voor Peblar Slim Laden."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SET_VERTREKTIJD
from .coordinator import PeblarCoordinator
from .entity import PeblarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PeblarVertrektijd(coordinator)])


class PeblarVertrektijd(PeblarEntity, TimeEntity):
    _attr_name = "Vertrektijd"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: PeblarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{SET_VERTREKTIJD}"

    @property
    def native_value(self) -> time | None:
        raw = self.coordinator.get_setting(SET_VERTREKTIJD)
        if not raw:
            return None
        try:
            h, m, s = (int(x) for x in str(raw).split(":"))
            return time(hour=h, minute=m, second=s)
        except (ValueError, TypeError):
            return None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_setting(
            SET_VERTREKTIJD, value.strftime("%H:%M:%S")
        )
        self.async_write_ha_state()
