"""Config flow voor Peblar Slim Laden."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAR_SOC,
    CONF_CHARGE_LIMIT_NUMBER,
    CONF_CHARGE_SWITCH,
    CONF_CHARGER_FAULTS,
    CONF_CHARGER_POWER,
    CONF_CHARGER_STATUS,
    CONF_CHARGER_WARNINGS,
    CONF_DB_URL,
    CONF_FC_NOW_POWER,
    CONF_FC_TODAY_REMAINING,
    CONF_FC_TOMORROW,
    CONF_GRID_POWER,
    CONF_PRECLIMATE_SWITCH,
    CONF_PV_DAILY_ENERGY,
    CONF_PV_POWER,
    CONF_RESTART_BUTTON,
    CONF_SESSION_ENERGY,
    CONF_SINGLE_PHASE_SWITCH,
    CONF_SOLCAST_NOW_POWER,
    CONF_SOLCAST_TODAY,
    CONF_SOLCAST_TODAY_REMAINING,
    CONF_SOLCAST_TOMORROW,
    DOMAIN,
)

# conf_key -> toegestane entity-domeinen voor de picker.
_ENTITY_DOMAINS: dict[str, list[str]] = {
    CONF_CHARGER_STATUS: ["sensor"],
    CONF_CHARGER_POWER: ["sensor"],
    CONF_SESSION_ENERGY: ["sensor"],
    CONF_CHARGER_WARNINGS: ["binary_sensor"],
    CONF_CHARGER_FAULTS: ["binary_sensor"],
    CONF_CAR_SOC: ["sensor"],
    CONF_GRID_POWER: ["sensor"],
    CONF_PV_POWER: ["sensor"],
    CONF_CHARGE_SWITCH: ["switch"],
    CONF_SINGLE_PHASE_SWITCH: ["switch"],
    CONF_CHARGE_LIMIT_NUMBER: ["number"],
    CONF_RESTART_BUTTON: ["button"],
    CONF_PRECLIMATE_SWITCH: ["switch"],
    CONF_PV_DAILY_ENERGY: ["sensor"],
    CONF_SOLCAST_TODAY_REMAINING: ["sensor"],
    CONF_SOLCAST_TOMORROW: ["sensor"],
    CONF_SOLCAST_NOW_POWER: ["sensor"],
    CONF_SOLCAST_TODAY: ["sensor"],
    CONF_FC_TODAY_REMAINING: ["sensor"],
    CONF_FC_TOMORROW: ["sensor"],
    CONF_FC_NOW_POWER: ["sensor"],
}

_REQUIRED = [
    CONF_CHARGER_STATUS,
    CONF_CHARGER_POWER,
    CONF_SESSION_ENERGY,
    CONF_CHARGER_WARNINGS,
    CONF_CHARGER_FAULTS,
    CONF_CAR_SOC,
    CONF_GRID_POWER,
    CONF_PV_POWER,
    CONF_CHARGE_SWITCH,
    CONF_SINGLE_PHASE_SWITCH,
    CONF_CHARGE_LIMIT_NUMBER,
    CONF_RESTART_BUTTON,
]

_OPTIONAL = [
    CONF_PRECLIMATE_SWITCH,
    CONF_PV_DAILY_ENERGY,
    CONF_SOLCAST_TODAY_REMAINING,
    CONF_SOLCAST_TOMORROW,
    CONF_SOLCAST_NOW_POWER,
    CONF_SOLCAST_TODAY,
    CONF_FC_TODAY_REMAINING,
    CONF_FC_TOMORROW,
    CONF_FC_NOW_POWER,
]


def _entity_selector(conf_key: str) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=_ENTITY_DOMAINS[conf_key])
    )


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    fields: dict = {}
    for key in _REQUIRED:
        marker = (
            vol.Required(key, default=defaults[key])
            if key in defaults
            else vol.Required(key)
        )
        fields[marker] = _entity_selector(key)
    for key in _OPTIONAL:
        marker = (
            vol.Optional(key, default=defaults[key])
            if key in defaults
            else vol.Optional(key)
        )
        fields[marker] = _entity_selector(key)
    db_marker = (
        vol.Optional(CONF_DB_URL, default=defaults[CONF_DB_URL])
        if CONF_DB_URL in defaults
        else vol.Optional(CONF_DB_URL)
    )
    fields[db_marker] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )
    return vol.Schema(fields)


class PeblarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow voor Peblar Slim Laden."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Peblar Slim Laden", data=user_input)

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_show_form(step_id="user", data_schema=_build_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PeblarOptionsFlow(config_entry)


class PeblarOptionsFlow(OptionsFlow):
    """Bewerk de gekoppelde entiteiten en db_url achteraf."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_build_schema(defaults)
        )
