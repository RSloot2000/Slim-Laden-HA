"""Constants for the Peblar Slim Laden integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "peblar_slim_laden"

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
CONF_CAR_PLUG_STATUS = "car_plug_status"
CONF_PRECLIMATE_SWITCH = "preclimate_switch"
CONF_GRID_POWER = "grid_power"
CONF_GRID_CURRENT_L1 = "grid_current_l1"
CONF_GRID_CURRENT_L2 = "grid_current_l2"
CONF_GRID_CURRENT_L3 = "grid_current_l3"
CONF_PV_POWER = "pv_power"
CONF_PV_DAILY_ENERGY = "pv_daily_energy"
CONF_OUTSIDE_TEMP = "outside_temp"          # actuele buitentemperatuur
CONF_NIGHT_MIN_TEMP = "night_min_temp"      # minimum voor de komende nacht

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

# Statussen van CONF_CAR_PLUG_STATUS die "stekker eruit" betekenen (kommagescheiden,
# hoofdletterongevoelig). De laadstatus van de auto-integratie is betrouwbaarder
# dan die van de lader, die 'suspended' blijft melden zolang de kabel erin zit.
# Mercedes (mbapi2020) chargingstatus: 0 opladen, 1 opladen beéindigd,
# 2 oplaadpauze, 3 LOSGEKOPPELD, 4 fout, 5 langzaam, 6 snel, 7 ontladen,
# 8 niet aan het opladen, 12 verbonden, 13 AC, 14 DC, 16 onbekend.
CONF_UNPLUGGED_STATES = "unplugged_states"
DEFAULT_UNPLUGGED_STATES = "3"

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
    CONF_CAR_PLUG_STATUS,
    CONF_OUTSIDE_TEMP,
    CONF_NIGHT_MIN_TEMP,
    CONF_GRID_CURRENT_L1,
    CONF_GRID_CURRENT_L2,
    CONF_GRID_CURRENT_L3,
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
# Aandeel van de voorspelde PV-opbrengst dat als overschot voor de auto
# beschikbaar komt (de rest gaat naar het huisverbruik). Dit is iets anders dan
# de geleerde forecast_bias, die de voorspelling zelf corrigeert.
SET_ZON_BENUT_FACTOR = "zon_benut_factor"
SET_HUISVERBRUIK_DAGEN = "huisverbruik_geheugen_dagen"
SET_MAX_NET_A = "max_netstroom_a"
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
    # Energie aan de laadpaal voor 100% SoC: bruikbare accu (~21,5 kWh op een
    # C300e) gedeeld door het laadrendement. kwh_needed stuurt de netvloer aan
    # en wordt dus aan de netzijde gemeten, niet aan de accuzijde.
    SET_ACCU_CAPACITEIT_KWH: 25.0,
    SET_PV_MARGE_WATT: 50.0,
    SET_MIN_A: 6,
    SET_MAX_A: 16,
    SET_ZON_BENUT_FACTOR: 0.6,
    SET_HUISVERBRUIK_DAGEN: 28,
    SET_MAX_NET_A: 25,
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
ST_PV_DAY = "pv_daily_day"                        # dag waarop ST_PV_DAY_MAX hoort
ST_PV_DAY_MAX = "pv_daily_max"
ST_HOUSE_PROFILE = "house_profile"                # 24 uurgemiddelden huisverbruik (W)

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
    ST_PV_DAY: None,
    ST_PV_DAY_MAX: 0.0,
    ST_HOUSE_PROFILE: None,
}

# ---------------------------------------------------------------------------
# Regelparameters (vaste constanten uit de oorspronkelijke automation).
# ---------------------------------------------------------------------------
GRACE_HOURS = 0.25
# Harde grenzen van de lader zelf (onafhankelijk van het aantal fasen).
HW_MIN_A = 6
HW_MAX_A = 16
NOMINAL_W_PER_A = 230             # nominaal W per ampère per fase (230 V)
# De lader trekt structureel één ampère minder dan het setpoint dat naar de
# laadlimiet wordt geschreven. Zonder deze correctie lijkt W/A stroomafhankelijk
# (198 bij setpoint 6 A, 223 bij 15 A) en kloppen de fase- en zondrempels niet.
AMP_OFFSET_A = 1
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
CHARGING_ACTIVE_W = 500
PRECLIMATE_POWER_W = 3500.0       # zelfbegrenzing auto bij vol + preclimate
# Deel van de voorspelde zon waarop de nachtplanning durft te rekenen. Alleen
# nog gebruikt als Solcast geen P10-band levert; met P10 is de onzekerheid al
# in de voorspelling zelf verwerkt.
SOLAR_TRUST_FACTOR = 0.8

# Hoofdzekering: onder deze marge van de zekeringwaarde wordt de laadstroom
# direct teruggenomen, buiten alle cooldowns om.
MAINS_MARGIN_A = 1.0
MAINS_MIN_A = 10
MAINS_MAX_A = 80

# Zodra de doel-SoC gehaald is moet de SoC minstens zoveel procent terugvallen
# voordat er opnieuw geladen wordt; anders gaat de laadschakelaar aan/uit
# knipperen op 1% ruis rond het doel.
SOC_RESTART_DEADBAND = 2.0

# Waarden die "geen vertrektijd/-datum ingesteld" betekenen.
NO_VALUE_STRINGS: tuple = ("", "unknown", "unavailable", None)
NO_DEPARTURE_TIME: str = "00:00:00"

# Laderstatussen waarbij de auto aangesloten is. Alles daarbuiten (en niet
# 'unknown'/'unavailable') betekent losgekoppeld.
CONNECTED_STATES: tuple = ("charging", "suspended")

# Stekkerstatus: bij voorkeur uit de auto-integratie, anders afgeleid uit de lader.
PLUG_UNKNOWN = "unknown"
PLUG_IN = "plugged"
PLUG_OUT = "unplugged"

# Huisverbruik-profiel: per weekdag 24 uurgemiddelden in W. Weekend en doordeweeks
# verschillen te veel voor één profiel. Elk vak krijgt eens per week een meting,
# die met een EMA wordt verwerkt; de tijdconstante volgt uit de ingestelde
# leerperiode, zodat het profiel seizoensdrift netjes volgt.
HOUSE_PROFILE_HOURS = 24
HOUSE_PROFILE_DAYS = 7
HOUSE_MEMORY_MIN_DAYS = 7
HOUSE_MEMORY_MAX_DAYS = 120
HOUSE_LOAD_MAX_W = 15000.0

# Storing/herstart
WARN_RESTART_MIN_MINUTEN = 20
ERR_RESTART_MIN_MINUTEN = 5
RESTART_COOLDOWN_MIN_MINUTEN = 15
MAX_RESTART_POGINGEN = 3
FAULT_CLEAR_STABIEL_MINUTEN = 10

# Coordinator
UPDATE_INTERVAL = timedelta(seconds=60)
# Minimale tijd tussen twee regelcycli die door bronwijzigingen worden getriggerd.
# Dit is een throttle (geen resettende debounce): een snel updatende P1-meter mag
# de regellus niet eindeloos uitstellen.
DEBOUNCE_SECONDS = 10
# Venster waarover grid-/laadvermogen gemiddeld wordt voor de fasekeuze.
POWER_SAMPLE_WINDOW = timedelta(minutes=2)
POWER_SAMPLE_MAXLEN = 240
# Minimale tijd tussen twee rijen in peb_charge_cycle. De regellus draait vaker
# dan dit; voor de leerlaag is een rij per minuut ruim voldoende.
CYCLE_LOG_MIN_INTERVAL = timedelta(seconds=60)
# De leerqueries kijken maximaal 60 dagen terug; alles daarvoor mag weg.
CYCLE_RETENTION_DAYS = 90

# Leerlaag (Fase C-E): periodieke DB-uitlezing + clamps op geleerde waarden.
LEARN_REFRESH_INTERVAL = timedelta(minutes=30)
FORECAST_BIAS_MIN = 0.5
FORECAST_BIAS_MAX = 1.5
# De geleerde kWh per 1% SoC wordt geklemd rond de ingestelde accu-capaciteit.
# Absolute grenzen laten een foute sessiemeting ongemerkt een factor 2 te hoog
# doorwerken in kwh_needed, wat de hele nachtplanning scheeftrekt. De marge
# boven 1.0 dekt het laadverlies (netzijde meten, accuzijde rekenen).
KWH_PER_PCT_MIN_FACTOR = 0.90
KWH_PER_PCT_MAX_FACTOR = 1.40

# Temperatuurmodel voor kwh_per_pct. In de kou daalt het laadrendement en draait
# de accuconditionering mee, waardoor er meer kWh aan de paal nodig is per procent
# SoC. Zolang er te weinig temperatuurspreiding is telt een recency-gewogen
# gemiddelde, dat het seizoen volgt; daarna neemt de regressie het over, die
# anticipeert in plaats van volgt.
KWH_PER_PCT_HALFLIFE_DAYS = 21
TEMP_MODEL_DAYS = 180
TEMP_MODEL_MIN_SESSIONS = 10
TEMP_MODEL_MIN_SPREAD_C = 8.0
# Fysisch plausibele helling (kWh per procent per graad); buiten dit bereik is
# de fit ruis en valt hij terug op het gemiddelde.
TEMP_SLOPE_MIN = -0.006
TEMP_SLOPE_MAX = 0.0
# Buiten het waargenomen temperatuurbereik niet verder dan dit extrapoleren.
TEMP_EXTRAPOLATE_C = 5.0
RAMP_BIAS_MAX = 0.15
HIT_RATE_TARGET = 0.8
# De SoC-sensor blijft in de praktijk op 99% steken bij een doel van 100%; zonder
# tolerantie telt elke geslaagde sessie als gemist en loopt de ramp_bias vol.
HIT_TARGET_TOLERANCE_PCT = 2.0

# Accu-capaciteit leren: absolute grenzen én een maximale sprong t.o.v. de
# huidige instelling. De span moet ruim genoeg zijn om een verkeerd ingestelde
# beginwaarde alsnog te kunnen corrigeren; de EMA dempt losse uitschieters al.
CAP_LEARN_ABS_MIN = 10.0
CAP_LEARN_ABS_MAX = 120.0
CAP_LEARN_REL_SPAN = 2.5

# ---------------------------------------------------------------------------
# TimescaleDB — kolommen van peb_charge_cycle (ts server-side).
# ---------------------------------------------------------------------------
CYCLE_COLS: list[str] = [
    "laadmodus", "peb_status", "soc_now", "soc_target", "kwh_needed",
    "hours_left", "desired_phase", "current_phase", "amps_set", "charger_w",
    "grid_w", "pv_now_w", "available_solar_w", "base_floor_w", "ramp_factor",
    "urgentie", "must_charge_w", "target_w", "real_w_per_a", "wpa_meas",
    "wpa_meas_valid", "expected_solar_kwh", "behind_schedule",
    "session_energy_kwh", "outside_temp",
]
