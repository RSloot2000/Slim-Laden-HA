"""Observability-sensoren voor Peblar Slim Laden."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .calc import ChargeDecision
from .const import DOMAIN
from .coordinator import PeblarCoordinator
from .entity import PeblarEntity


@dataclass(frozen=True, kw_only=True)
class PeblarSensorDescription(SensorEntityDescription):
    """Beschrijving met een waarde-extractor uit de ChargeDecision."""

    value_fn: Callable[[ChargeDecision, PeblarCoordinator], object] = None


def _power(key: str, name: str) -> PeblarSensorDescription:
    return PeblarSensorDescription(
        key=key,
        name=name,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d, c: getattr(d, key),
    )


SENSORS: tuple[PeblarSensorDescription, ...] = (
    PeblarSensorDescription(
        key="soc_now", name="SoC nu", native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda d, c: d.soc_now,
    ),
    PeblarSensorDescription(
        key="kwh_needed", name="Benodigde energie",
        native_unit_of_measurement="kWh", suggested_display_precision=2,
        value_fn=lambda d, c: d.kwh_needed,
    ),
    PeblarSensorDescription(
        key="hours_left", name="Uren tot deadline",
        native_unit_of_measurement="h", suggested_display_precision=2,
        value_fn=lambda d, c: d.hours_left,
    ),
    PeblarSensorDescription(
        key="amps_set", name="Ampère ingesteld",
        native_unit_of_measurement="A", state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, c: d.amps_set,
    ),
    _power("charger_w", "Laadvermogen"),
    _power("grid_w", "Netvermogen"),
    _power("pv_now_w", "PV nu"),
    _power("available_solar_w", "Beschikbaar zonoverschot"),
    _power("base_floor_w", "Grid-vloer"),
    _power("must_charge_w", "Must-charge"),
    _power("target_w", "Target"),
    PeblarSensorDescription(
        key="ramp_factor", name="Ramp-factor", suggested_display_precision=2,
        value_fn=lambda d, c: d.ramp_factor,
    ),
    PeblarSensorDescription(
        key="urgentie", name="Urgentie", suggested_display_precision=2,
        value_fn=lambda d, c: d.urgentie,
    ),
    PeblarSensorDescription(
        key="real_w_per_a", name="W per A (geleerd)",
        native_unit_of_measurement="W/A", suggested_display_precision=0,
        value_fn=lambda d, c: d.real_w_per_a,
    ),
    PeblarSensorDescription(
        key="wpa_meas", name="W per A (gemeten)",
        native_unit_of_measurement="W/A", suggested_display_precision=0,
        value_fn=lambda d, c: d.wpa_meas,
    ),
    PeblarSensorDescription(
        key="expected_solar_kwh", name="Verwachte zon",
        native_unit_of_measurement="kWh", suggested_display_precision=1,
        value_fn=lambda d, c: d.expected_solar_kwh,
    ),
    PeblarSensorDescription(
        key="desired_phase", name="Gewenste fase",
        value_fn=lambda d, c: d.desired_phase,
    ),
    PeblarSensorDescription(
        key="current_phase", name="Huidige fase",
        value_fn=lambda d, c: d.current_phase,
    ),
    PeblarSensorDescription(
        key="laadmodus_actief", name="Laadmodus (actief)",
        value_fn=lambda d, c: d.laadmodus,
    ),
    PeblarSensorDescription(
        key="behind_schedule", name="Achter op schema",
        value_fn=lambda d, c: "on" if d.behind_schedule else "off",
    ),
    PeblarSensorDescription(
        key="db_status", name="DB-status",
        value_fn=lambda d, c: c.db_status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PeblarSensor(coordinator, desc) for desc in SENSORS)


class PeblarSensor(PeblarEntity, SensorEntity):
    """Observability-sensor gevoed door de coordinator."""

    entity_description: PeblarSensorDescription

    def __init__(
        self, coordinator: PeblarCoordinator, description: PeblarSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, self.coordinator)
