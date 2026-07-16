"""Schakelaars (switch) voor Peblar Slim Laden-instellingen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    SET_ANDERE_AUTO,
    SET_DAGELIJKSE_VERTREKTIJD,
    SET_DEBUG,
    SET_LAADLIMIET_OVERRIDE,
    SET_REGELEN_ACTIEF,
    SET_SLIM_LADEN_AAN,
)
from .coordinator import PeblarCoordinator
from .entity import PeblarEntity


@dataclass(frozen=True, kw_only=True)
class PeblarSwitchDescription(SwitchEntityDescription):
    setting_key: str = ""


SWITCHES: tuple[PeblarSwitchDescription, ...] = (
    PeblarSwitchDescription(
        key=SET_REGELEN_ACTIEF, setting_key=SET_REGELEN_ACTIEF,
        name="Regelen actief", icon="mdi:robot",
    ),
    PeblarSwitchDescription(
        key=SET_SLIM_LADEN_AAN, setting_key=SET_SLIM_LADEN_AAN,
        name="Slim laden aan", icon="mdi:lightning-bolt",
    ),
    PeblarSwitchDescription(
        key=SET_LAADLIMIET_OVERRIDE, setting_key=SET_LAADLIMIET_OVERRIDE,
        name="Laadlimiet override",
    ),
    PeblarSwitchDescription(
        key=SET_ANDERE_AUTO, setting_key=SET_ANDERE_AUTO,
        name="Andere auto aan lader",
    ),
    PeblarSwitchDescription(
        key=SET_DAGELIJKSE_VERTREKTIJD, setting_key=SET_DAGELIJKSE_VERTREKTIJD,
        name="Dagelijkse vertrektijd",
    ),
    PeblarSwitchDescription(
        key=SET_DEBUG, setting_key=SET_DEBUG, name="Debug-meldingen",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PeblarSwitch(coordinator, desc) for desc in SWITCHES)


class PeblarSwitch(PeblarEntity, SwitchEntity):
    entity_description: PeblarSwitchDescription

    def __init__(
        self, coordinator: PeblarCoordinator, description: PeblarSwitchDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_setting(self.entity_description.setting_key))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_setting(
            self.entity_description.setting_key, True
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_setting(
            self.entity_description.setting_key, False
        )
        self.async_write_ha_state()
