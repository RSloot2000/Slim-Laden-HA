"""Binaire toestandsensoren voor Peblar Slim Laden."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .calc import ChargeDecision
from .const import DOMAIN
from .coordinator import PeblarCoordinator
from .entity import PeblarDecisionEntity


@dataclass(frozen=True, kw_only=True)
class PeblarBinarySensorDescription(BinarySensorEntityDescription):
    """Beschrijving met een waarde-extractor uit de ChargeDecision."""

    value_fn: Callable[[ChargeDecision], bool]


BINARY_SENSORS: tuple[PeblarBinarySensorDescription, ...] = (
    PeblarBinarySensorDescription(
        key="behind_schedule",
        translation_key="behind_schedule",
        name="Achter op schema",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.behind_schedule,
    ),
    PeblarBinarySensorDescription(
        key="want_charge",
        translation_key="want_charge",
        name="Laadbehoefte",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.want_charge,
    ),
    PeblarBinarySensorDescription(
        key="car_here",
        translation_key="car_here",
        name="Auto aangesloten",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.car_here,
    ),
    PeblarBinarySensorDescription(
        key="solar_pause",
        translation_key="solar_pause",
        name="Laadpauze (wacht op zon)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.solar_pause,
    ),
    PeblarBinarySensorDescription(
        key="solar_only",
        translation_key="solar_only",
        name="Alleen zonoverschot",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.solar_only,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PeblarBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    )


class PeblarBinarySensor(PeblarDecisionEntity, BinarySensorEntity):
    entity_description: PeblarBinarySensorDescription

    def __init__(
        self,
        coordinator: PeblarCoordinator,
        description: PeblarBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
