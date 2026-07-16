"""Instelbare getallen (number) voor Peblar Slim Laden."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    SET_ACCU_CAPACITEIT_KWH,
    SET_DOEL_SOC,
    SET_FASEWISSEL_MIN_MINUTEN,
    SET_MAX_A,
    SET_MIN_A,
    SET_PV_MARGE_WATT,
    SET_ZON_BENUT_FACTOR,
)
from .coordinator import PeblarCoordinator
from .entity import PeblarEntity


@dataclass(frozen=True, kw_only=True)
class PeblarNumberDescription(NumberEntityDescription):
    setting_key: str = ""


NUMBERS: tuple[PeblarNumberDescription, ...] = (
    PeblarNumberDescription(
        key=SET_DOEL_SOC, setting_key=SET_DOEL_SOC, name="Doel-SoC",
        native_min_value=0, native_max_value=100, native_step=1,
        native_unit_of_measurement="%", mode=NumberMode.SLIDER,
    ),
    PeblarNumberDescription(
        key=SET_ACCU_CAPACITEIT_KWH, setting_key=SET_ACCU_CAPACITEIT_KWH,
        name="Accu-capaciteit", native_min_value=10, native_max_value=120,
        native_step=0.1, native_unit_of_measurement="kWh", mode=NumberMode.BOX,
    ),
    PeblarNumberDescription(
        key=SET_PV_MARGE_WATT, setting_key=SET_PV_MARGE_WATT, name="PV-marge",
        native_min_value=0, native_max_value=2000, native_step=10,
        native_unit_of_measurement="W", mode=NumberMode.BOX,
    ),
    PeblarNumberDescription(
        key=SET_MIN_A, setting_key=SET_MIN_A, name="Laadvermogen min",
        native_min_value=6, native_max_value=16, native_step=1,
        native_unit_of_measurement="A", mode=NumberMode.BOX,
    ),
    PeblarNumberDescription(
        key=SET_MAX_A, setting_key=SET_MAX_A, name="Laadvermogen max",
        native_min_value=6, native_max_value=16, native_step=1,
        native_unit_of_measurement="A", mode=NumberMode.BOX,
    ),
    PeblarNumberDescription(
        key=SET_ZON_BENUT_FACTOR, setting_key=SET_ZON_BENUT_FACTOR,
        name="Zon benut-factor", native_min_value=0.1, native_max_value=1,
        native_step=0.05, mode=NumberMode.BOX,
    ),
    PeblarNumberDescription(
        key=SET_FASEWISSEL_MIN_MINUTEN, setting_key=SET_FASEWISSEL_MIN_MINUTEN,
        name="Fasewissel min-interval", native_min_value=0, native_max_value=60,
        native_step=1, native_unit_of_measurement="min", mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PeblarNumber(coordinator, desc) for desc in NUMBERS)


class PeblarNumber(PeblarEntity, NumberEntity):
    entity_description: PeblarNumberDescription

    def __init__(
        self, coordinator: PeblarCoordinator, description: PeblarNumberDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.get_setting(self.entity_description.setting_key)
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        key = self.entity_description.setting_key
        stored = int(value) if self.entity_description.native_step == 1 else value
        await self.coordinator.async_set_setting(key, stored)
        self.async_write_ha_state()
