"""Gedeelde basis voor Peblar Slim Laden-entiteiten."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PeblarCoordinator


class PeblarEntity(CoordinatorEntity[PeblarCoordinator]):
    """Basisentiteit met gedeelde device-info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PeblarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Peblar Slim Laden",
            manufacturer="Peblar",
            model="Slim laden regelaar",
        )
