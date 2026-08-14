"""Diagnostics voor Peblar Slim Laden."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DB_URL, DOMAIN
from .coordinator import PeblarCoordinator

TO_REDACT = {CONF_DB_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Verzamel diagnostiek voor een config entry."""
    coordinator: PeblarCoordinator = hass.data[DOMAIN][entry.entry_id]
    decision = coordinator.data
    return {
        "config": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "settings": coordinator.settings,
        "state": coordinator.state_data,
        "learned": coordinator.learned,
        "db_status": coordinator.db_status,
        "decision": vars(decision) if decision is not None else None,
    }
