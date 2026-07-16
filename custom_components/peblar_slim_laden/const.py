"""Constants for the Peblar Slim Laden integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "peblar_slim_laden"

PLATFORMS: list[str] = [
    "sensor",
    "number",
    "select",
    "switch",
    "time",
    "date",
]

# ---------------------------------------------------------------------------
# Config-flow keys: externe (device/integratie) entiteiten die de integratie
# consumeert of aanstuurt. Alle instel-helpers levert de integratie zelf.
# ---------------------------------------------------------------------------
# Lezen (sensoren/binary_sensors)
CONF_CHARGER_STATUS = "charger_status"
CONF_CHARGER_POWER = "charger_power"
CONF_SESSION_ENERGY = "session_energy"
CONF_CHARGER_WARNINGS = "charger_warnings"
CONF_CHARGER_FAULTS = "charger_faults"
CONF_CAR_SOC = "car_soc"
CONF_PRECLIMATE_SWITCH = "preclimate_switch"
CONF_GRID_POWER = "grid_power"
CONF_PV_POWER = "pv_power"
CONF_PV_DAILY_ENERGY = "pv_daily_energy"

# Solcast forecast
CONF_SOLCAST_TODAY_REMAINING = "solcast_today_remaining"
CONF_SOLCAST_TOMORROW = "solcast_tomorrow"
CONF_SOLCAST_NOW_POWER = "solcast_now_power"
CONF_SOLCAST_TODAY = "solcast_today"  # detailedForecast attribuut

# Fallback forecast (forecast.solar), optioneel
CONF_FC_TODAY_REMAINING = "fc_today_remaining"
CONF_FC_TOMORROW = "fc_tomorrow"
CONF_FC_NOW_POWER = "fc_now_power"

# Schrijven (actuatoren)
CONF_CHARGE_SWITCH = "charge_switch"
CONF_SINGLE_PHASE_SWITCH = "single_phase_switch"
CONF_CHARGE_LIMIT_NUMBER = "charge_limit_number"
CONF_RESTART_BUTTON = "restart_button"

# Database
CONF_DB_URL = "db_url"

# Verplichte externe entiteiten (config flow stap 1/2)
REQUIRED_ENTITY_KEYS: list[str] = [
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

# Optionele externe entiteiten
OPTIONAL_ENTITY_KEYS: list[str] = [
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

# ---------------------------------------------------------------------------
# Instel-entiteiten (settings) — sleutels in de persistente settings-store.
# ---------------------------------------------------------------------------
SET_LAADMODUS = "laadmodus"
SET_DOEL_SOC = "doel_soc"
SET_ACCU_CAPACITEIT_KWH = "accu_capaciteit_kwh"
SET_PV_MARGE_WATT = "pv_marge_watt"
SET_MIN_A = "laadvermogen_min_a"
SET_MAX_A = "laadvermogen_max_a"
SET_ZON_BENUT_FACTOR = "zon_benut_factor"
SET_FASEWISSEL_MIN_MINUTEN = "fasewissel_min_minuten"
SET_VERTREKTIJD = "vertrektijd"
SET_VERTREKDATUM = "vertrekdatum"
SET_DAGELIJKSE_VERTREKTIJD = "dagelijkse_vertrektijd"
SET_SLIM_LADEN_AAN = "slim_laden_aan"
SET_LAADLIMIET_OVERRIDE = "laadlimiet_override"
SET_ANDERE_AUTO = "andere_auto_aan_lader"
SET_DEBUG = "peblar_debug"
SET_REGELEN_ACTIEF = "regelen_actief"

# Modus-opties
LAADMODI = ["Snel", "Zon", "Hybride"]

# Defaults voor de instel-entiteiten
DEFAULT_SETTINGS: dict = {
    SET_LAADMODUS: "Hybride",
    SET_DOEL_SOC: 100,
    SET_ACCU_CAPACITEIT_KWH: 50.0,
    SET_PV_MARGE_WATT: 50.0,
    SET_MIN_A: 6,
    SET_MAX_A: 16,
    SET_ZON_BENUT_FACTOR: 0.6,
    SET_FASEWISSEL_MIN_MINUTEN: 10,
    SET_VERTREKTIJD: "00:00:00",
    SET_VERTREKDATUM: None,
    SET_DAGELIJKSE_VERTREKTIJD: False,
    SET_SLIM_LADEN_AAN: True,
    SET_LAADLIMIET_OVERRIDE: False,
    SET_ANDERE_AUTO: False,
    SET_DEBUG: False,
    SET_REGELEN_ACTIEF: False,  # observe-only tot de gebruiker het aanzet
}

# ---------------------------------------------------------------------------
# Interne persistente runtime-state (Store).
# ---------------------------------------------------------------------------
ST_WPA_STORED = "wpa_stored"
ST_RESTART_ATTEMPTS = "restart_attempts"
ST_LAST_PHASE_CHANGE = "last_phase_change"       # iso timestamp
ST_LAST_AMP_CHANGE = "last_amp_change"
ST_LAST_CHARGE_SWITCH = "last_charge_switch"
ST_LAST_CHARGE_DEMAND = "last_charge_demand"
ST_LAST_RESTART = "last_restart"
ST_SOC_START = "soc_start"                        # capaciteit-leren
ST_ENERGY_START = "energy_start"

DEFAULT_STATE: dict = {
    ST_WPA_STORED: 230.0,
    ST_RESTART_ATTEMPTS: 0,
    ST_LAST_PHASE_CHANGE: None,
    ST_LAST_AMP_CHANGE: None,
    ST_LAST_CHARGE_SWITCH: None,
    ST_LAST_CHARGE_DEMAND: None,
    ST_LAST_RESTART: None,
    ST_SOC_START: None,
    ST_ENERGY_START: None,
}

# ---------------------------------------------------------------------------
# Regelparameters (vaste constanten uit de oorspronkelijke automation).
# ---------------------------------------------------------------------------
GRACE_HOURS = 0.25
WPA_MIN = 150.0
WPA_MAX = 250.0
WPA_VALID_MIN = 200.0
WPA_VALID_MAX = 240.0
WPA_EMA_ALPHA = 0.3               # nieuw gewicht (0.7 oud + 0.3 nieuw)
MEAS_SETTLE_S = 15
AMP_SETTLE_S = 30
PHASE_UP_BUFFER_W = 150
EMERGENCY_IMPORT_W = 400
CHARGE_SWITCH_MIN_MINUTEN = 5
STOP_GRACE_MINUTEN = 3
PHASE_SETTLE_S = 3
CHARGING_ACTIVE_W = 500
PRECLIMATE_POWER_W = 3500         # zelfbegrenzing auto bij vol + preclimate

# Storing/herstart
WARN_RESTART_MIN_MINUTEN = 20
ERR_RESTART_MIN_MINUTEN = 5
RESTART_COOLDOWN_MIN_MINUTEN = 15
MAX_RESTART_POGINGEN = 3
FAULT_CLEAR_STABIEL_MINUTEN = 10

# Coordinator
UPDATE_INTERVAL = timedelta(minutes=2)
DEBOUNCE_SECONDS = 8

# Leerlaag (Fase C-E): periodieke DB-uitlezing + clamps op geleerde waarden.
LEARN_REFRESH_INTERVAL = timedelta(minutes=30)
FORECAST_BIAS_MIN = 0.5
FORECAST_BIAS_MAX = 1.5
KWH_PER_PCT_MIN = 0.2
KWH_PER_PCT_MAX = 1.2
RAMP_BIAS_MAX = 0.15
HIT_RATE_TARGET = 0.8

# ---------------------------------------------------------------------------
# TimescaleDB — kolommen van peb_charge_cycle (ts server-side).
# ---------------------------------------------------------------------------
CYCLE_COLS: list[str] = [
    "laadmodus", "peb_status", "soc_now", "soc_target", "kwh_needed",
    "hours_left", "desired_phase", "current_phase", "amps_set", "charger_w",
    "grid_w", "pv_now_w", "available_solar_w", "base_floor_w", "ramp_factor",
    "urgentie", "must_charge_w", "target_w", "real_w_per_a", "wpa_meas",
    "wpa_meas_valid", "expected_solar_kwh", "behind_schedule",
    "session_energy_kwh",
]

# Observability-sensoren (suffix -> databron in de decision/telemetrie).
SENSOR_NUM: list[str] = [
    "soc_now", "kwh_needed", "hours_left", "amps_set", "charger_w", "grid_w",
    "pv_now_w", "available_solar_w", "base_floor_w", "ramp_factor", "urgentie",
    "must_charge_w", "target_w", "real_w_per_a", "wpa_meas",
    "expected_solar_kwh", "desired_phase", "current_phase",
]
