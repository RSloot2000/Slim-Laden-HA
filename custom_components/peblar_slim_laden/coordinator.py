"""DataUpdateCoordinator (regellus) voor Peblar Slim Laden."""

from __future__ import annotations

import logging
import math
from collections import deque
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import db
from .calc import (
    ChargeDecision,
    ChargeInputs,
    ForecastSlot,
    SolarSurplus,
    clamp,
    compute,
    kwh_per_pct_at,
    parse_departure,
    solar_surplus_before,
)
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
    CONNECTED_STATES,
    CYCLE_LOG_MIN_INTERVAL,
    CYCLE_RETENTION_DAYS,
    DEBOUNCE_SECONDS,
    DEFAULT_SETTINGS,
    DEFAULT_STATE,
    DEFAULT_UNPLUGGED_STATES,
    DOMAIN,
    EMERGENCY_IMPORT_W,
    ERR_RESTART_MIN_MINUTEN,
    FAULT_CLEAR_STABIEL_MINUTEN,
    FORECAST_BIAS_MAX,
    FORECAST_BIAS_MIN,
    HIT_RATE_TARGET,
    HOUSE_LOAD_MAX_W,
    HOUSE_MEMORY_MAX_DAYS,
    HOUSE_MEMORY_MIN_DAYS,
    HOUSE_PROFILE_DAYS,
    HOUSE_PROFILE_HOURS,
    HW_MAX_A,
    HW_MIN_A,
    KWH_PER_PCT_MAX_FACTOR,
    KWH_PER_PCT_MIN_FACTOR,
    MAX_RESTART_POGINGEN,
    PLUG_IN,
    PLUG_OUT,
    PLUG_UNKNOWN,
    POWER_SAMPLE_MAXLEN,
    POWER_SAMPLE_WINDOW,
    RAMP_BIAS_MAX,
    RESTART_COOLDOWN_MIN_MINUTEN,
    SET_ACCU_CAPACITEIT_KWH,
    SET_ANDERE_AUTO,
    SET_DAGELIJKSE_VERTREKTIJD,
    SET_DEBUG,
    SET_DOEL_SOC,
    SET_FASEWISSEL_MIN_MINUTEN,
    SET_HUISVERBRUIK_DAGEN,
    SET_LAADLIMIET_OVERRIDE,
    SET_LAADMODUS,
    SET_MAX_A,
    SET_MAX_NET_A,
    SET_MIN_A,
    SET_PV_MARGE_WATT,
    SET_REGELEN_ACTIEF,
    SET_SLIM_LADEN_AAN,
    SET_VERTREKDATUM,
    SET_VERTREKTIJD,
    SET_ZON_BENUT_FACTOR,
    ST_ENERGY_START,
    ST_HOUSE_PROFILE,
    ST_LAST_AMP_CHANGE,
    ST_LAST_CHARGE_DEMAND,
    ST_LAST_CHARGE_SWITCH,
    ST_LAST_PHASE_CHANGE,
    ST_LAST_RESTART,
    ST_PV_DAY,
    ST_PV_DAY_MAX,
    ST_RESTART_ATTEMPTS,
    ST_SOC_START,
    ST_WPA_STORED,
    UPDATE_INTERVAL,
    WARN_RESTART_MIN_MINUTEN,
    WPA_MAX,
    WPA_MIN,
)
from .learn import learn_capacity

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = ("unknown", "unavailable", "", None)
_STORAGE_VERSION = 1


class PeblarCoordinator(DataUpdateCoordinator[ChargeDecision]):
    """Regelt slim laden: leest bronnen, rekent, stuurt de lader aan."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            # Throttle: bronwijzigingen mogen hooguit eens per cooldown een
            # regelcyclus starten. Anders stelt een 1 Hz P1-meter de lus
            # eindeloos uit (een resettende debounce vuurt dan nooit).
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=DEBOUNCE_SECONDS, immediate=False
            ),
        )
        self.entry = entry
        self.conf = {**entry.data, **entry.options}
        self._store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.state_data: dict = dict(DEFAULT_STATE)
        self._grid_samples: deque[tuple[datetime, float]] = deque(
            maxlen=POWER_SAMPLE_MAXLEN
        )
        self._charger_samples: deque[tuple[datetime, float]] = deque(
            maxlen=POWER_SAMPLE_MAXLEN
        )
        self._prev_status: str | None = None
        self._prev_plug_state: str | None = None
        self._seen_plug_values: set[str] = set()
        self._house_key: tuple[int, int] | None = None
        self._house_sum = 0.0
        self._house_n = 0
        self.house_now_w: float | None = None
        self.temp_model_active = False
        self._time_changed_flag = False
        self._stranded_notified = False
        self._last_cycle_log: datetime | None = None
        self._unsub_listeners: list = []
        self.db_status = "unknown"
        # Geleerde signalen uit de DB (Fase C-E); leeg tot de eerste uitlezing.
        self.learned: dict = {}

    # ------------------------------------------------------------------
    # Persistente opslag
    # ------------------------------------------------------------------
    async def async_load_store(self) -> None:
        """Laad settings + interne state uit de Store."""
        data = await self._store.async_load()
        if data:
            self.settings.update(data.get("settings", {}))
            self.state_data.update(data.get("state", {}))

    async def async_save_store(self) -> None:
        """Bewaar settings + interne state (direct)."""
        await self._store.async_save(
            {"settings": self.settings, "state": self.state_data}
        )

    @callback
    def _data_to_save(self) -> dict:
        return {"settings": self.settings, "state": self.state_data}

    @callback
    def _schedule_save(self) -> None:
        """Plan een uitgestelde save (voorkomt schrijven bij elke cyclus)."""
        self._store.async_delay_save(self._data_to_save, 30)

    def get_setting(self, key: str):
        return self.settings.get(key, DEFAULT_SETTINGS.get(key))

    async def async_set_setting(self, key: str, value) -> None:
        """Wijzig een instelling vanuit de UI, sla op en vraag een refresh aan."""
        self._apply_setting(key, value)
        await self.async_save_store()
        await self.async_request_refresh()

    @callback
    def _apply_setting(self, key: str, value) -> None:
        """Zet een instelling zonder opslag/refresh (voor gebruik in de regellus)."""
        self.settings[key] = value
        if key == SET_VERTREKTIJD:
            self._time_changed_flag = True

    def _get_state(self, key: str):
        return self.state_data.get(key, DEFAULT_STATE.get(key))

    def _set_state(self, key: str, value) -> None:
        self.state_data[key] = value

    # ------------------------------------------------------------------
    # Listeners / throttling
    # ------------------------------------------------------------------
    def setup_listeners(self) -> None:
        """Reageer op wijzigingen van de bronsensoren (gethrottled)."""
        entities = [
            self.conf.get(k)
            for k in (
                CONF_CHARGER_STATUS,
                CONF_CHARGER_POWER,
                CONF_GRID_POWER,
                CONF_PV_POWER,
                CONF_CAR_SOC,
                CONF_CAR_PLUG_STATUS,
                CONF_CHARGER_WARNINGS,
                CONF_CHARGER_FAULTS,
                CONF_PRECLIMATE_SWITCH,
            )
            if self.conf.get(k)
        ]
        if entities:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass, entities, self._on_source_change
                )
            )

    async def _on_source_change(self, event) -> None:
        """Bemonster vermogens bij elke bronwijziging en vraag een refresh aan."""
        self._sample_power(dt_util.now())
        await self.async_request_refresh()

    def shutdown(self) -> None:
        self._commit_house_hour()
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    # ------------------------------------------------------------------
    # Uitleeshelpers
    # ------------------------------------------------------------------
    def _num(self, conf_key: str, default: float | None = None) -> float | None:
        entity_id = self.conf.get(conf_key)
        if not entity_id:
            return default
        st = self.hass.states.get(entity_id)
        if st is None or st.state in _UNAVAILABLE:
            return default
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return default

    def _raw_available(self, conf_key: str) -> bool:
        """True als de gekoppelde entiteit een bruikbare state heeft."""
        entity_id = self.conf.get(conf_key)
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        return st is not None and st.state not in _UNAVAILABLE

    def _str(self, conf_key: str, default: str = "unknown") -> str:
        entity_id = self.conf.get(conf_key)
        if not entity_id:
            return default
        st = self.hass.states.get(entity_id)
        if st is None or st.state in _UNAVAILABLE:
            return default
        return st.state

    def _is_on(self, conf_key: str) -> bool:
        entity_id = self.conf.get(conf_key)
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        return st is not None and st.state == "on"

    def _secs_since(self, key: str, now: datetime) -> float:
        ts = self._get_state(key)
        if not ts:
            return 1e9
        try:
            dt = dt_util.parse_datetime(ts)
        except (TypeError, ValueError):
            return 1e9
        if dt is None:
            return 1e9
        return (now - dt).total_seconds()

    def _secs_state(self, conf_key: str, value: str, now: datetime) -> float:
        """Seconden dat een (binary_)sensor al op `value` staat (0 als anders)."""
        entity_id = self.conf.get(conf_key)
        if not entity_id:
            return 0.0
        st = self.hass.states.get(entity_id)
        if st is None or st.state != value:
            return 0.0
        return (now - st.last_changed).total_seconds()

    @callback
    def _sample_power(self, now: datetime) -> None:
        """Leg de actuele net-/laadvermogens vast voor het glijdend gemiddelde."""
        grid = self._num(CONF_GRID_POWER)
        if grid is not None:
            self._grid_samples.append((now, grid))
        charger = self._num(CONF_CHARGER_POWER)
        if charger is not None:
            self._charger_samples.append((now, charger))

    def _rolling_mean(self, samples: deque, now: datetime) -> float | None:
        cutoff = now - POWER_SAMPLE_WINDOW
        while samples and samples[0][0] < cutoff:
            samples.popleft()
        if not samples:
            return None
        return sum(v for _, v in samples) / len(samples)

    # ------------------------------------------------------------------
    # Huisverbruik: meten en per uur van de dag leren
    # ------------------------------------------------------------------
    @callback
    def _house_load_w(self) -> float | None:
        """Huisverbruik = PV-productie + netafname - laadvermogen."""
        grid = self._num(CONF_GRID_POWER)
        pv = self._num(CONF_PV_POWER)
        if grid is None or pv is None:
            return None
        charger = self._num(CONF_CHARGER_POWER, 0.0) or 0.0
        return clamp(pv + grid - charger, 0.0, HOUSE_LOAD_MAX_W)

    @callback
    def _track_house_profile(self, now: datetime) -> None:
        """Middel het huisverbruik per weekdag+klokuur en werk het profiel bij."""
        key = (now.weekday(), now.hour)
        if self._house_key is None:
            self._house_key = key
        elif key != self._house_key:
            self._commit_house_hour()
            self._house_key = key
        value = self._house_load_w()
        self.house_now_w = value
        if value is not None:
            self._house_sum += value
            self._house_n += 1

    @callback
    def _house_profile(self) -> list[list[float | None]]:
        """Het opgeslagen profiel als 7x24-matrix (leeg bij afwijkende vorm)."""
        stored = self._get_state(ST_HOUSE_PROFILE)
        if (
            isinstance(stored, list)
            and len(stored) == HOUSE_PROFILE_DAYS
            and all(
                isinstance(day, list) and len(day) == HOUSE_PROFILE_HOURS
                for day in stored
            )
        ):
            return [list(day) for day in stored]
        return [[None] * HOUSE_PROFILE_HOURS for _ in range(HOUSE_PROFILE_DAYS)]

    @callback
    def _house_alpha(self) -> float:
        """EMA-gewicht; elk vak krijgt eens per week een nieuwe meting."""
        days = clamp(
            float(self.get_setting(SET_HUISVERBRUIK_DAGEN)),
            HOUSE_MEMORY_MIN_DAYS,
            HOUSE_MEMORY_MAX_DAYS,
        )
        return 1 - math.exp(-HOUSE_PROFILE_DAYS / days)

    @callback
    def _commit_house_hour(self) -> None:
        """Verwerk het uurgemiddelde met een EMA in het opgeslagen profiel."""
        key, total, n = self._house_key, self._house_sum, self._house_n
        self._house_sum, self._house_n = 0.0, 0
        if key is None or n == 0:
            return
        weekday, hour = key
        mean = total / n
        profile = self._house_profile()
        old = profile[weekday][hour]
        alpha = self._house_alpha()
        profile[weekday][hour] = (
            mean if old is None else (1 - alpha) * float(old) + alpha * mean
        )
        self._set_state(ST_HOUSE_PROFILE, profile)
        self._schedule_save()

    @callback
    def _house_kw(self, weekday: int, hour: int) -> float | None:
        """Geleerd huisverbruik (kW) voor dit vak.

        Zolang een weekdag nog geen eigen meting heeft, telt het gemiddelde van
        datzelfde uur op de andere dagen; zo is het profiel meteen bruikbaar en
        specialiseert het per dag naarmate er data binnenkomt.
        """
        profile = self._house_profile()
        hour %= HOUSE_PROFILE_HOURS
        value = profile[weekday % HOUSE_PROFILE_DAYS][hour]
        if value is None:
            others = [d[hour] for d in profile if d[hour] is not None]
            if not others:
                return None
            value = sum(float(v) for v in others) / len(others)
        return float(value) / 1000

    @callback
    def learned_house_w(self) -> float | None:
        """Geleerd huisverbruik voor het huidige vak, in watt."""
        now = dt_util.now()
        kw = self._house_kw(now.weekday(), now.hour)
        return None if kw is None else kw * 1000

    @callback
    def _house_kw_at(self, moment: datetime) -> float | None:
        """Geleerd huisverbruik (kW) op dit moment, lokale tijd."""
        local = dt_util.as_local(moment)
        return self._house_kw(local.weekday(), local.hour)

    @callback
    def _forecast_slots(self) -> list[ForecastSlot]:
        """Lees de half-uur-slots uit de gekoppelde Solcast-sensoren."""
        slots: list[ForecastSlot] = []
        for key in (CONF_SOLCAST_TODAY, CONF_SOLCAST_TOMORROW):
            entity_id = self.conf.get(key)
            if not entity_id:
                continue
            st = self.hass.states.get(entity_id)
            if st is None:
                continue
            for item in st.attributes.get("detailedForecast") or ():
                start = dt_util.parse_datetime(str(item.get("period_start")))
                if start is None:
                    continue
                try:
                    kwh = float(item.get("pv_estimate") or 0)
                except (TypeError, ValueError):
                    continue
                raw_p10 = item.get("pv_estimate10")
                try:
                    p10 = None if raw_p10 is None else float(raw_p10)
                except (TypeError, ValueError):
                    p10 = None
                slots.append(ForecastSlot(start=start, kwh=kwh, kwh_p10=p10))
        return slots

    @callback
    def _grid_max_phase_a(self) -> float | None:
        """Hoogste fasestroom van de P1-meter; None als niet alle fasen er zijn."""
        values = []
        for key in (CONF_GRID_CURRENT_L1, CONF_GRID_CURRENT_L2, CONF_GRID_CURRENT_L3):
            if not self.conf.get(key):
                return None
            value = self._num(key)
            if value is None:
                return None
            values.append(abs(value))
        return max(values) if values else None

    @callback
    def _plug_state(self, peb_status: str) -> str:
        """Zit de kabel in de auto?

        De laadstatus van de auto-integratie is leidend zodra die beschikbaar is:
        die kent een expliciete losgekoppeld-status, terwijl de lader ook bij een
        beéindigde laadbeurt nog van alles kan melden. Elke andere waarde geldt
        als 'kabel zit erin', zodat een onbekende code nooit een reset uitlokt.
        """
        entity_id = self.conf.get(CONF_CAR_PLUG_STATUS)
        if entity_id:
            st = self.hass.states.get(entity_id)
            if st is not None and st.state not in _UNAVAILABLE:
                raw = str(
                    self.conf.get(CONF_UNPLUGGED_STATES) or DEFAULT_UNPLUGGED_STATES
                )
                unplugged = {s.strip().lower() for s in raw.split(",") if s.strip()}
                self._log_new_plug_value(st.state, peb_status)
                return PLUG_OUT if st.state.lower() in unplugged else PLUG_IN

        # Terugval zolang de auto-integratie niets levert.
        if peb_status in CONNECTED_STATES:
            return PLUG_IN
        if peb_status in _UNAVAILABLE:
            return PLUG_UNKNOWN
        return PLUG_OUT

    @callback
    def _log_new_plug_value(self, value: str, peb_status: str) -> None:
        """Log elke nieuwe statuswaarde met context, om de codes te herkennen."""
        if value in self._seen_plug_values:
            return
        self._seen_plug_values.add(value)
        _LOGGER.info(
            "peblar_slim_laden: nieuwe waarde voor laadstatus auto: %r "
            "(lader: %s, laadvermogen: %s W, SoC: %s)",
            value,
            peb_status,
            self._num(CONF_CHARGER_POWER),
            self._num(CONF_CAR_SOC),
        )

    # ------------------------------------------------------------------
    # Inputs bouwen
    # ------------------------------------------------------------------
    def _build_inputs(self, now: datetime) -> ChargeInputs:
        # Instelgrenzen consistent houden (min nooit boven max, altijd binnen HW).
        min_a = int(clamp(int(self.get_setting(SET_MIN_A)), HW_MIN_A, HW_MAX_A))
        max_a = int(clamp(int(self.get_setting(SET_MAX_A)), min_a, HW_MAX_A))

        # Vermogens (live + glijdend gemiddelde over POWER_SAMPLE_WINDOW).
        self._sample_power(now)
        grid_live = self._num(CONF_GRID_POWER)
        grid_ok = grid_live is not None
        charger_live = self._num(CONF_CHARGER_POWER)
        grid_avg = self._rolling_mean(self._grid_samples, now)
        charger_avg = self._rolling_mean(self._charger_samples, now)
        grid_w = grid_live if grid_live is not None else (grid_avg or 0.0)
        charger_w = charger_live if charger_live is not None else (charger_avg or 0.0)
        charge_power_now = charger_avg if charger_avg is not None else charger_w

        # Forecast: Solcast met forecast.solar-fallback.
        fc_today = self._num(CONF_SOLCAST_TODAY_REMAINING)
        if fc_today is None:
            fc_today = self._num(CONF_FC_TODAY_REMAINING, 0.0) or 0.0
        fc_tomorrow = self._num(CONF_SOLCAST_TOMORROW)
        if fc_tomorrow is None:
            fc_tomorrow = self._num(CONF_FC_TOMORROW, 0.0) or 0.0
        pv_now = self._num(CONF_SOLCAST_NOW_POWER)
        if pv_now is None:
            pv_now = self._num(CONF_FC_NOW_POWER, 0.0) or 0.0

        # Vertrek.
        dep_time = str(self.get_setting(SET_VERTREKTIJD) or "00:00:00")
        dep_date = self.get_setting(SET_VERTREKDATUM)

        # detailedForecast tot de deadline (zelfde parser als calc.compute).
        surplus = SolarSurplus()
        _, deadline = parse_departure(now, dep_time, dep_date)
        if deadline is not None:
            surplus = solar_surplus_before(
                self._forecast_slots(),
                now,
                deadline,
                float(self.learned.get("forecast_bias") or 1.0),
                self._house_kw_at,
            )

        # Fase / ampère toestand.
        current_phase = 1 if self._is_on(CONF_SINGLE_PHASE_SWITCH) else 3
        current_amps = int(self._num(CONF_CHARGE_LIMIT_NUMBER) or min_a)

        # Fase C-E: geleerde signalen + afgeleide ramp-bias uit de hit-rate.
        learned = self.learned
        ramp_bias = 0.0
        hit_rate = learned.get("hit_rate")
        if hit_rate is not None and hit_rate < HIT_RATE_TARGET:
            ramp_bias = clamp((HIT_RATE_TARGET - hit_rate) * 0.5, 0.0, RAMP_BIAS_MAX)

        peb_status = self._str(CONF_CHARGER_STATUS)
        inp = ChargeInputs(
            now=now,
            laadmodus=str(self.get_setting(SET_LAADMODUS)),
            slim_laden=bool(self.get_setting(SET_SLIM_LADEN_AAN)),
            other_car=bool(self.get_setting(SET_ANDERE_AUTO)),
            override_limit=bool(self.get_setting(SET_LAADLIMIET_OVERRIDE)),
            preclimate_active=self._is_on(CONF_PRECLIMATE_SWITCH),
            peb_status=peb_status,
            prev_peb_status=self._prev_status,
            plug_state=self._plug_state(peb_status),
            prev_plug_state=self._prev_plug_state,
            min_a=min_a,
            max_a=max_a,
            pv_marge_watt=float(self.get_setting(SET_PV_MARGE_WATT)),
            zon_benut_factor=float(self.get_setting(SET_ZON_BENUT_FACTOR)),
            fasewissel_min_minuten=int(self.get_setting(SET_FASEWISSEL_MIN_MINUTEN)),
            soc_raw=self._num(CONF_CAR_SOC),
            soc_target=int(self.get_setting(SET_DOEL_SOC)),
            battery_capacity_kwh=float(self.get_setting(SET_ACCU_CAPACITEIT_KWH)),
            dep_time=dep_time,
            dep_date=dep_date,
            daily_departure=bool(self.get_setting(SET_DAGELIJKSE_VERTREKTIJD)),
            time_changed=self._time_changed_flag,
            fc_today_remaining=fc_today,
            fc_tomorrow=fc_tomorrow,
            pv_now_w=pv_now,
            solar_detail_ok=surplus.covers_window,
            solar_surplus_before_dep_kwh=surplus.kwh,
            solar_surplus_p10_kwh=surplus.kwh_p10,
            solar_p10_ok=surplus.p10_ok,
            grid_w=grid_w,
            grid_ok=grid_ok,
            grid_avg_w=grid_avg if grid_avg is not None else grid_w,
            grid_max_phase_a=self._grid_max_phase_a(),
            max_net_a=int(self.get_setting(SET_MAX_NET_A)),
            charger_w=charger_w,
            charger_avg_w=charger_avg if charger_avg is not None else charger_w,
            charge_power_now_w=charge_power_now,
            current_phase=current_phase,
            current_amps=current_amps,
            charge_now_on=self._is_on(CONF_CHARGE_SWITCH),
            wpa_stored=float(self._get_state(ST_WPA_STORED)),
            seconds_since_amp_change=self._secs_since(ST_LAST_AMP_CHANGE, now),
            minutes_since_phase_change=self._secs_since(ST_LAST_PHASE_CHANGE, now) / 60,
            seconds_since_charge_switch=self._secs_since(ST_LAST_CHARGE_SWITCH, now),
            seconds_since_charge_demand=self._secs_since(ST_LAST_CHARGE_DEMAND, now),
            session_energy_kwh=self._num(CONF_SESSION_ENERGY, 0.0) or 0.0,
            forecast_bias=learned.get("forecast_bias") or 1.0,
            kwh_per_pct=learned.get("kwh_per_pct"),
            wpa_1p=learned.get("wpa_1p"),
            wpa_3p=learned.get("wpa_3p"),
            ramp_bias=ramp_bias,
        )
        return inp

    # ------------------------------------------------------------------
    # Hoofd-update
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> ChargeDecision:
        now = dt_util.now()
        inp = self._build_inputs(now)
        decision = compute(inp)
        # time_changed-vlag is nu verwerkt.
        self._time_changed_flag = False

        regelen = bool(self.get_setting(SET_REGELEN_ACTIEF))

        self._track_pv_daily(now)
        self._track_house_profile(now)
        await self._handle_capacity(inp, now)
        # W/A leren gebeurt altijd (pure observatie), ook in observe-only.
        if decision.update_wpa:
            self._set_state(ST_WPA_STORED, clamp(decision.wpa_new, WPA_MIN, WPA_MAX))
        await self._handle_faults(inp, now, regelen)
        await self._handle_departure(decision, now)
        if regelen and not decision.dep_reset_needed:
            await self._apply_control(inp, decision, now)

        self._prev_status = inp.peb_status
        self._prev_plug_state = inp.plug_state
        self._schedule_save()
        await self._log_cycle(decision)
        return decision

    # ------------------------------------------------------------------
    # Capaciteit leren (charging <-> suspended overgangen)
    # ------------------------------------------------------------------
    @callback
    def _track_pv_daily(self, now: datetime) -> None:
        """Houd de hoogste stand van de PV-dagteller bij.

        De omvormer valt na zonsondergang stil, dus de stand om 23:55 is niet
        betrouwbaar; het maximum van de dag wel.
        """
        today = now.date().isoformat()
        if self._get_state(ST_PV_DAY) != today:
            self._set_state(ST_PV_DAY, today)
            self._set_state(ST_PV_DAY_MAX, 0.0)
        value = self._num(CONF_PV_DAILY_ENERGY)
        if value is not None and value > float(self._get_state(ST_PV_DAY_MAX) or 0.0):
            self._set_state(ST_PV_DAY_MAX, value)
    async def _handle_capacity(self, inp: ChargeInputs, now: datetime) -> None:
        status = inp.peb_status
        prev = inp.prev_peb_status
        soc = inp.soc_raw
        energy = inp.session_energy_kwh

        if status == "charging" and prev != "charging":
            self._set_state(ST_SOC_START, soc)
            self._set_state(ST_ENERGY_START, energy)
            return

        if prev == "charging" and status != "charging":
            res = learn_capacity(
                soc_start=self._get_state(ST_SOC_START),
                soc_end=soc,
                energy_start=self._get_state(ST_ENERGY_START),
                energy_end=energy,
                old_capacity=float(self.get_setting(SET_ACCU_CAPACITEIT_KWH)),
                other_car=inp.other_car,
                preclimate_active=inp.preclimate_active,
            )
            if res.updated:
                self._apply_setting(
                    SET_ACCU_CAPACITEIT_KWH, round(res.updated_capacity, 2)
                )
                await self._notify(
                    "peblar_capaciteit",
                    "Accu-capaciteit bijgewerkt",
                    f"Nieuwe meting: {res.new_capacity:.2f} kWh. "
                    f"Gewogen resultaat: {res.updated_capacity:.2f} kWh. "
                    f"ΔSoC: {res.soc_delta:.0f}% | Geladen: {res.energy_session:.2f} kWh",
                )

    # ------------------------------------------------------------------
    # Storings- / herstartlogica
    # ------------------------------------------------------------------
    async def _handle_faults(
        self, inp: ChargeInputs, now: datetime, regelen: bool
    ) -> None:
        warn_active = self._is_on(CONF_CHARGER_WARNINGS)
        err_active = self._is_on(CONF_CHARGER_FAULTS)
        fault_active = warn_active or err_active
        warn_secs_on = self._secs_state(CONF_CHARGER_WARNINGS, "on", now)
        err_secs_on = self._secs_state(CONF_CHARGER_FAULTS, "on", now)
        warn_secs_off = self._secs_state(CONF_CHARGER_WARNINGS, "off", now)
        err_secs_off = self._secs_state(CONF_CHARGER_FAULTS, "off", now)
        attempts = int(self._get_state(ST_RESTART_ATTEMPTS))
        secs_since_restart = self._secs_since(ST_LAST_RESTART, now)
        debug = bool(self.get_setting(SET_DEBUG))

        fault_stable_clear = (
            not fault_active
            and warn_secs_off >= FAULT_CLEAR_STABIEL_MINUTEN * 60
            and err_secs_off >= FAULT_CLEAR_STABIEL_MINUTEN * 60
        )
        if fault_stable_clear and attempts > 0:
            self._set_state(ST_RESTART_ATTEMPTS, 0)
            self._stranded_notified = False
            await self._dismiss("peblar_lader_gestrand")

        # In observe-only mode niet herstarten en geen gestrand-status bijhouden.
        if not regelen:
            return

        restart_cooldown_ok = secs_since_restart >= RESTART_COOLDOWN_MIN_MINUTEN * 60
        fault_long_enough = (
            (warn_active and warn_secs_on >= WARN_RESTART_MIN_MINUTEN * 60)
            or (err_active and err_secs_on >= ERR_RESTART_MIN_MINUTEN * 60)
        )
        charger_stranded = fault_active and attempts >= MAX_RESTART_POGINGEN
        restart_needed = (
            restart_cooldown_ok and fault_long_enough and attempts < MAX_RESTART_POGINGEN
        )

        if charger_stranded:
            if self._is_on(CONF_CHARGE_SWITCH):
                await self._service("switch", "turn_off", CONF_CHARGE_SWITCH)
            if not self._stranded_notified:
                self._stranded_notified = True
                await self._notify(
                    "peblar_lader_gestrand",
                    "Peblar lader gestopt - storing blijft",
                    f"De lader is {MAX_RESTART_POGINGEN}x herstart maar de "
                    f"{'fout' if err_active else 'waarschuwing'} blijft. Laden gestopt "
                    "uit veiligheid; los de storing handmatig op.",
                )
            return

        if restart_needed:
            await self._service("button", "press", CONF_RESTART_BUTTON)
            self._set_state(ST_LAST_RESTART, now.isoformat())
            self._set_state(ST_RESTART_ATTEMPTS, attempts + 1)
            if debug:
                await self._notify(
                    "peblar_slim_laden_herstart",
                    "Peblar lader herstart",
                    f"Herstart poging {attempts + 1}/{MAX_RESTART_POGINGEN} na "
                    f"aanhoudende {'fout' if err_active else 'waarschuwing'}.",
                )

    # ------------------------------------------------------------------
    # Vertrekdatum-beheer
    # ------------------------------------------------------------------
    async def _handle_departure(self, d: ChargeDecision, now: datetime) -> None:
        if d.dep_reset_needed:
            self._apply_setting(SET_VERTREKTIJD, "00:00:00")
            self._time_changed_flag = False
            self._apply_setting(SET_VERTREKDATUM, now.strftime("%Y-%m-%d"))
        elif d.dep_date_needs_update and d.desired_dep_date:
            self._apply_setting(SET_VERTREKDATUM, d.desired_dep_date)

    # ------------------------------------------------------------------
    # Regelacties toepassen (achter observe-only gate)
    # ------------------------------------------------------------------
    async def _apply_control(
        self, inp: ChargeInputs, d: ChargeDecision, now: datetime
    ) -> None:
        min_a = inp.min_a

        # Auto losgekoppeld: lader terug naar 1 fase + minimale ampère, zodat de
        # volgende sessie schoon begint.
        if d.just_disconnected:
            await self._reset_to_idle(min_a)
            return

        if not d.car_here:
            return

        # Laadbehoefte-timestamp bijwerken.
        if d.want_charge_raw:
            self._set_state(ST_LAST_CHARGE_DEMAND, now.isoformat())

        # Laden aan/uit (calc bepaalde set_charge_on incl. cooldown).
        if d.set_charge_on is False:
            await self._service("switch", "turn_off", CONF_CHARGE_SWITCH)
            self._set_state(ST_LAST_CHARGE_SWITCH, now.isoformat())
            return
        if d.set_charge_on is True:
            await self._service("switch", "turn_on", CONF_CHARGE_SWITCH)
            self._set_state(ST_LAST_CHARGE_SWITCH, now.isoformat())

        # Niet verder regelen (ampère/fase) als we niet willen laden.
        if not d.want_charge:
            return

        # Eerst de ampères terug (calc zet die op min bij een fasewissel), daarna
        # pas schakelen: zo maakt de lader de wissel op het laagste vermogen.
        if d.phase_change_needed or d.amps_change_needed:
            await self._set_number(d.amps_set)
            self._set_state(ST_LAST_AMP_CHANGE, now.isoformat())
            if bool(self.get_setting(SET_DEBUG)):
                await self._notify(
                    "peblar_slim_laden",
                    "Peblar slim laden",
                    f"Modus {d.laadmodus} | fase {d.desired_phase} | {d.amps_set}A | "
                    f"target {d.target_w:.0f}W | zon {d.available_solar_w:.0f}W | "
                    f"vloer {d.base_floor_w:.0f}W | W/A {d.real_w_per_a:.0f} | "
                    f"resterend {d.time_left_display}",
                )

        if d.phase_change_needed:
            self._set_state(ST_LAST_PHASE_CHANGE, now.isoformat())
            if d.desired_phase == 1:
                await self._service("switch", "turn_on", CONF_SINGLE_PHASE_SWITCH)
            elif d.desired_phase == 3:
                await self._service("switch", "turn_off", CONF_SINGLE_PHASE_SWITCH)

    # ------------------------------------------------------------------
    # Service-/notificatiehelpers
    # ------------------------------------------------------------------
    async def _reset_to_idle(self, min_a: int) -> None:
        """Zet de lader terug op 1 fase en de minimale ampère."""
        await self._set_number(min_a)
        if not self._is_on(CONF_SINGLE_PHASE_SWITCH):
            await self._service("switch", "turn_on", CONF_SINGLE_PHASE_SWITCH)
        _LOGGER.debug("peblar_slim_laden: auto losgekoppeld, lader gereset")

    async def _service(self, domain: str, service: str, conf_key: str) -> None:
        entity_id = self.conf.get(conf_key)
        if not entity_id:
            return
        await self.hass.services.async_call(
            domain, service, {"entity_id": entity_id}, blocking=False
        )

    async def _set_number(self, value: float) -> None:
        entity_id = self.conf.get(CONF_CHARGE_LIMIT_NUMBER)
        if not entity_id:
            return
        # Idempotent: sla over als de laadlimiet al op deze waarde staat.
        st = self.hass.states.get(entity_id)
        if st is not None:
            try:
                if int(float(st.state)) == int(value):
                    return
            except (TypeError, ValueError):
                pass
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": int(value)},
            blocking=False,
        )

    async def _notify(self, notification_id: str, title: str, message: str) -> None:
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {"notification_id": notification_id, "title": title, "message": message},
            blocking=False,
        )

    async def _dismiss(self, notification_id: str) -> None:
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": notification_id},
            blocking=False,
        )

    # ------------------------------------------------------------------
    # DB-log
    # ------------------------------------------------------------------
    async def _log_cycle(self, d: ChargeDecision) -> None:
        db_url = self.conf.get(CONF_DB_URL)
        if not db_url:
            return
        now = dt_util.utcnow()
        if (
            self._last_cycle_log is not None
            and now - self._last_cycle_log < CYCLE_LOG_MIN_INTERVAL
        ):
            return
        self._last_cycle_log = now
        row = {
            "laadmodus": d.laadmodus,
            "peb_status": d.peb_status,
            "soc_now": d.soc_now,
            "soc_target": d.soc_target,
            "kwh_needed": d.kwh_needed,
            "hours_left": d.hours_left,
            "desired_phase": d.desired_phase,
            "current_phase": d.current_phase,
            "amps_set": d.amps_set,
            "charger_w": d.charger_w,
            "grid_w": d.grid_w,
            "pv_now_w": d.pv_now_w,
            "available_solar_w": d.available_solar_w,
            "base_floor_w": d.base_floor_w,
            "ramp_factor": d.ramp_factor,
            "urgentie": d.urgentie,
            "must_charge_w": d.must_charge_w,
            "target_w": d.target_w,
            "real_w_per_a": d.real_w_per_a,
            "wpa_meas": d.wpa_meas,
            "wpa_meas_valid": d.wpa_meas_valid,
            "expected_solar_kwh": d.expected_solar_kwh,
            "behind_schedule": d.behind_schedule,
            "session_energy_kwh": d.session_energy_kwh,
            "outside_temp": self._num(CONF_OUTSIDE_TEMP),
        }
        try:
            await self.hass.async_add_executor_job(db.insert_cycle, db_url, row)
            self.db_status = "ok"
        except Exception as err:  # noqa: BLE001 - DB nooit fataal
            self.db_status = f"error: {type(err).__name__}"
            _LOGGER.warning("peblar_slim_laden: DB-insert mislukt: %s", err)

    async def async_process_sessions(self) -> None:
        db_url = self.conf.get(CONF_DB_URL)
        if not db_url:
            return
        try:
            n = await self.hass.async_add_executor_job(db.process_sessions, db_url)
            if n:
                _LOGGER.info("peblar_slim_laden: %s nieuwe laadsessie(s)", n)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("peblar_slim_laden: sessiedetectie mislukt: %s", err)

    async def async_prune_cycles(self, _now=None) -> None:
        """Ruim cyclusrijen op die buiten het leervenster vallen."""
        db_url = self.conf.get(CONF_DB_URL)
        if not db_url:
            return
        try:
            n = await self.hass.async_add_executor_job(
                db.prune_cycles, db_url, CYCLE_RETENTION_DAYS
            )
            if n:
                _LOGGER.info("peblar_slim_laden: %s oude cyclusrijen verwijderd", n)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("peblar_slim_laden: opschonen mislukt: %s", err)

    async def async_forecast_capture(
        self, forecast_kwh: float | None, actual_kwh: float | None
    ) -> None:
        db_url = self.conf.get(CONF_DB_URL)
        if not db_url:
            return
        day = dt_util.now().date().isoformat()
        try:
            await self.hass.async_add_executor_job(
                db.forecast_upsert, db_url, day, forecast_kwh, actual_kwh
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("peblar_slim_laden: forecast-capture mislukt: %s", err)

    async def async_capture_forecast_today(self) -> None:
        """Leg de dagvoorspelling vast (eerste schrijving per dag wint)."""
        fc = self._num(CONF_SOLCAST_TODAY)
        if fc is not None:
            await self.async_forecast_capture(fc, None)

    async def async_capture_actual_today(self) -> None:
        """Leg de werkelijke dagopbrengst vast."""
        if self._get_state(ST_PV_DAY) != dt_util.now().date().isoformat():
            return
        actual = float(self._get_state(ST_PV_DAY_MAX) or 0.0)
        if actual <= 0:
            _LOGGER.warning(
                "peblar_slim_laden: geen PV-dagopbrengst gezien vandaag; "
                "controleer of 'PV opbrengst vandaag' aan een dagteller in kWh "
                "hangt en niet aan een vermogenssensor"
            )
            return
        await self.async_forecast_capture(None, actual)

    @callback
    def planning_temp(self) -> float | None:
        """Temperatuur waarop de komende laadsessie naar verwachting plaatsvindt.

        Om 22:00 koelt het nog flink af, dus het gemiddelde van nu en het
        nachtminimum benadert de sessietemperatuur beter dan de huidige stand.
        """
        now_t = self._num(CONF_OUTSIDE_TEMP)
        if now_t is None:
            return None
        night_min = self._num(CONF_NIGHT_MIN_TEMP)
        return now_t if night_min is None else (now_t + night_min) / 2

    @callback
    def _kwh_per_pct(self, raw: dict) -> float | None:
        """Geleerde kWh per procent SoC, gecorrigeerd voor de temperatuur."""
        value, used_model = kwh_per_pct_at(
            raw.get("kwh_per_pct"),
            raw.get("kpp_slope"),
            raw.get("kpp_intercept"),
            raw.get("kpp_temp_min"),
            raw.get("kpp_temp_max"),
            self.planning_temp(),
        )
        self.temp_model_active = used_model
        return value

    async def async_refresh_learned(self, _now=None) -> None:
        """Lees geleerde signalen uit de DB en klem ze (Fase C-E)."""
        db_url = self.conf.get(CONF_DB_URL)
        if not db_url:
            return
        try:
            raw = await self.hass.async_add_executor_job(db.read_learned, db_url)
        except Exception as err:  # noqa: BLE001 - DB nooit fataal
            _LOGGER.warning("peblar_slim_laden: leren-uitlezen mislukt: %s", err)
            return

        learned: dict = {}
        fb = raw.get("forecast_bias")
        learned["forecast_bias"] = (
            clamp(fb, FORECAST_BIAS_MIN, FORECAST_BIAS_MAX) if fb else None
        )
        kp = self._kwh_per_pct(raw)
        # Relatief aan de ingestelde capaciteit klemmen: een uitschieter in de
        # sessiedata mag kwh_needed niet met een factor mis laten rekenen.
        cap_per_pct = float(self.get_setting(SET_ACCU_CAPACITEIT_KWH)) / 100
        if kp:
            clamped = clamp(
                kp,
                cap_per_pct * KWH_PER_PCT_MIN_FACTOR,
                cap_per_pct * KWH_PER_PCT_MAX_FACTOR,
            )
            if abs(clamped - kp) > 0.02:
                _LOGGER.warning(
                    "peblar_slim_laden: gemeten %.3f kWh/%% wijkt sterk af van de "
                    "ingestelde accu-capaciteit (%.1f kWh -> %.3f kWh/%%) en is "
                    "geklemd op %.3f. Controleer de accu-capaciteit.",
                    kp,
                    cap_per_pct * 100,
                    cap_per_pct,
                    clamped,
                )
            learned["kwh_per_pct"] = clamped
        else:
            learned["kwh_per_pct"] = None
        for key in ("wpa_1p", "wpa_3p"):
            val = raw.get(key)
            learned[key] = clamp(val, WPA_MIN, WPA_MAX) if val else None
        hr = raw.get("hit_rate")
        learned["hit_rate"] = clamp(hr, 0.0, 1.0) if hr is not None else None
        self.learned = learned
        _LOGGER.debug("peblar_slim_laden: geleerde waarden bijgewerkt: %s", learned)

    async def async_close_db(self) -> None:
        """Sluit de hergebruikte DB-verbinding (bij unload)."""
        if self.conf.get(CONF_DB_URL):
            await self.hass.async_add_executor_job(db.close_connection)

    async def async_ensure_schema(self) -> None:
        """Vul kolommen aan die nieuwere versies nodig hebben."""
        db_url = self.conf.get(CONF_DB_URL)
        if not db_url:
            return
        try:
            await self.hass.async_add_executor_job(db.ensure_schema, db_url)
        except Exception as err:  # noqa: BLE001 - DB nooit fataal
            _LOGGER.warning("peblar_slim_laden: schemacontrole mislukt: %s", err)
