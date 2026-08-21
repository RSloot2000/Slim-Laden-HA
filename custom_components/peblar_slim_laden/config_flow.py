"""Config flow voor Peblar Slim Laden."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import db
from .const import (
    CONF_CAR_PLUG_STATUS,
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
    CONF_GRID_CURRENT_L1,
    CONF_GRID_CURRENT_L2,
    CONF_GRID_CURRENT_L3,
    CONF_GRID_POWER,
    CONF_NIGHT_MIN_TEMP,
    CONF_OUTSIDE_TEMP,
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
    CONF_UNPLUGGED_STATES,
    DEFAULT_UNPLUGGED_STATES,
    DOMAIN,
    OPTIONAL_ENTITY_KEYS,
    REQUIRED_ENTITY_KEYS,
)

_LOGGER = logging.getLogger(__name__)

# conf_key -> toegestane entity-domeinen voor de picker.
_ENTITY_DOMAINS: dict[str, list[str]] = {
    CONF_CHARGER_STATUS: ["sensor"],
    CONF_CHARGER_POWER: ["sensor"],
    CONF_SESSION_ENERGY: ["sensor"],
    CONF_CHARGER_WARNINGS: ["binary_sensor"],
    CONF_CHARGER_FAULTS: ["binary_sensor"],
    CONF_CAR_SOC: ["sensor"],
    CONF_CAR_PLUG_STATUS: ["sensor", "binary_sensor"],
    CONF_GRID_POWER: ["sensor"],
    CONF_GRID_CURRENT_L1: ["sensor"],
    CONF_GRID_CURRENT_L2: ["sensor"],
    CONF_GRID_CURRENT_L3: ["sensor"],
    CONF_PV_POWER: ["sensor"],
    CONF_CHARGE_SWITCH: ["switch"],
    CONF_SINGLE_PHASE_SWITCH: ["switch"],
    CONF_CHARGE_LIMIT_NUMBER: ["number"],
    CONF_RESTART_BUTTON: ["button"],
    CONF_PRECLIMATE_SWITCH: ["switch"],
    CONF_PV_DAILY_ENERGY: ["sensor"],
    CONF_OUTSIDE_TEMP: ["sensor"],
    CONF_NIGHT_MIN_TEMP: ["sensor"],
    CONF_SOLCAST_TODAY_REMAINING: ["sensor"],
    CONF_SOLCAST_TOMORROW: ["sensor"],
    CONF_SOLCAST_NOW_POWER: ["sensor"],
    CONF_SOLCAST_TODAY: ["sensor"],
    CONF_FC_TODAY_REMAINING: ["sensor"],
    CONF_FC_TOMORROW: ["sensor"],
    CONF_FC_NOW_POWER: ["sensor"],
}


def _entity_selector(conf_key: str) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=_ENTITY_DOMAINS[conf_key])
    )


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    fields: dict = {}
    for key in REQUIRED_ENTITY_KEYS:
        marker = (
            vol.Required(key, default=defaults[key])
            if key in defaults
            else vol.Required(key)
        )
        fields[marker] = _entity_selector(key)
    for key in OPTIONAL_ENTITY_KEYS:
        marker = (
            vol.Optional(key, default=defaults[key])
            if key in defaults
            else vol.Optional(key)
        )
        fields[marker] = _entity_selector(key)
    states_marker = vol.Optional(
        CONF_UNPLUGGED_STATES,
        default=defaults.get(CONF_UNPLUGGED_STATES, DEFAULT_UNPLUGGED_STATES),
    )
    fields[states_marker] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )
    db_marker = (
        vol.Optional(CONF_DB_URL, default=defaults[CONF_DB_URL])
        if CONF_DB_URL in defaults
        else vol.Optional(CONF_DB_URL)
    )
    # De URL bevat het DB-wachtwoord: niet in platte tekst tonen.
    fields[db_marker] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    return vol.Schema(fields)


async def _async_validate(hass, user_input: dict[str, Any]) -> dict[str, str]:
    """Controleer de invoer; geeft een (lege) foutmap per veld terug."""
    errors: dict[str, str] = {}
    db_url = user_input.get(CONF_DB_URL)
    if db_url:
        try:
            await hass.async_add_executor_job(db.validate_url, db_url)
        except Exception as err:  # noqa: BLE001 - elke DB-fout is hier invoerfout
            _LOGGER.debug("DB-validatie mislukt: %s", type(err).__name__)
            errors[CONF_DB_URL] = "cannot_connect"
    return errors


class PeblarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow voor Peblar Slim Laden."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title="Peblar Slim Laden", data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return PeblarOptionsFlow()


class PeblarOptionsFlow(OptionsFlow):
    """Bewerk de gekoppelde entiteiten en db_url achteraf."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        defaults = user_input or {
            **self.config_entry.data,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init", data_schema=_build_schema(defaults), errors=errors
        )
