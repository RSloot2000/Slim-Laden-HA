"""De Peblar Slim Laden integratie."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PV_DAILY_ENERGY,
    CONF_SOLCAST_TODAY,
    DOMAIN,
    LEARN_REFRESH_INTERVAL,
    PLATFORMS,
)
from .coordinator import PeblarCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Zet een config entry op."""
    coordinator = PeblarCoordinator(hass, entry)
    await coordinator.async_load_store()
    # Geleerde signalen ophalen vóór de eerste regelcyclus (Fase C-E).
    await coordinator.async_refresh_learned()
    await coordinator.async_config_entry_first_refresh()
    coordinator.setup_listeners()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Geleerde signalen periodiek verversen.
    entry.async_on_unload(
        async_track_time_interval(
            hass, coordinator.async_refresh_learned, LEARN_REFRESH_INTERVAL
        )
    )

    # Sessiedetectie elke 10 minuten.
    async def _sessions(_now) -> None:
        await coordinator.async_process_sessions()

    entry.async_on_unload(
        async_track_time_change(hass, _sessions, minute=range(0, 60, 10), second=0)
    )

    # Forecast vastleggen: 00:10 (voorspelling) en 23:55 (werkelijk).
    async def _forecast_morning(_now) -> None:
        fc = coordinator._num(CONF_SOLCAST_TODAY)
        if fc is not None:
            await coordinator.async_forecast_capture(fc, None)

    async def _forecast_actual(_now) -> None:
        act = coordinator._num(CONF_PV_DAILY_ENERGY)
        if act is not None:
            await coordinator.async_forecast_capture(None, act)

    entry.async_on_unload(
        async_track_time_change(hass, _forecast_morning, hour=0, minute=10, second=0)
    )
    entry.async_on_unload(
        async_track_time_change(hass, _forecast_actual, hour=23, minute=55, second=0)
    )

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Verwijder een config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: PeblarCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.shutdown()
        await coordinator.async_save_store()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Herlaad de entry na een optie-wijziging."""
    await hass.config_entries.async_reload(entry.entry_id)
