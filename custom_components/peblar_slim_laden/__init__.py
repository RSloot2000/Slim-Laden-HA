"""De Peblar Slim Laden integratie."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval

from .const import DOMAIN, LEARN_REFRESH_INTERVAL
from .coordinator import PeblarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

# Entiteiten uit oudere versies die naar een ander platform verhuisd zijn.
_MOVED_ENTITIES: list[tuple[str, str]] = [
    (Platform.SENSOR, "behind_schedule"),
]


@callback
def _async_cleanup_moved_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Verwijder registry-resten van entiteiten die van platform gewisseld zijn."""
    registry = er.async_get(hass)
    for domain, key in _MOVED_ENTITIES:
        entity_id = registry.async_get_entity_id(
            domain, DOMAIN, f"{entry.entry_id}_{key}"
        )
        if entity_id:
            registry.async_remove(entity_id)
            _LOGGER.debug("peblar_slim_laden: oude entiteit %s verwijderd", entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Zet een config entry op."""
    coordinator = PeblarCoordinator(hass, entry)
    await coordinator.async_load_store()
    await coordinator.async_ensure_schema()
    # Geleerde signalen ophalen vóór de eerste regelcyclus (Fase C-E).
    await coordinator.async_refresh_learned()
    await coordinator.async_config_entry_first_refresh()
    coordinator.setup_listeners()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    _async_cleanup_moved_entities(hass, entry)
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

    # Oude cyclusrijen dagelijks opruimen.
    entry.async_on_unload(
        async_track_time_change(
            hass, coordinator.async_prune_cycles, hour=3, minute=30, second=0
        )
    )

    # Forecast vastleggen: 's ochtends de voorspelling, 's avonds het resultaat.
    # De upsert houdt de eerste voorspelling van de dag vast, dus een herstart of
    # een late Solcast-update overschrijft de vergelijking niet.
    async def _forecast_morning(_now) -> None:
        await coordinator.async_capture_forecast_today()

    async def _forecast_actual(_now) -> None:
        await coordinator.async_capture_actual_today()

    entry.async_on_unload(
        async_track_time_change(hass, _forecast_morning, hour=6, minute=0, second=0)
    )
    entry.async_on_unload(
        async_track_time_change(hass, _forecast_actual, hour=23, minute=55, second=0)
    )
    # Inhaalslag na een herstart: ontbreekt de voorspelling van vandaag nog, dan
    # wordt hij alsnog vastgelegd.
    await coordinator.async_capture_forecast_today()

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Verwijder een config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: PeblarCoordinator | None = hass.data.get(DOMAIN, {}).pop(
            entry.entry_id, None
        )
        if coordinator is not None:
            coordinator.shutdown()
            await coordinator.async_save_store()
            await coordinator.async_close_db()
        if not hass.data.get(DOMAIN):
            hass.data.pop(DOMAIN, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Herlaad de entry na een optie-wijziging."""
    await hass.config_entries.async_reload(entry.entry_id)
