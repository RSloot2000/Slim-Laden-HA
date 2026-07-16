"""DataUpdateCoordinator (regellus) voor Peblar Slim Laden."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import db
from .calc import ChargeInputs, ChargeDecision, clamp, compute
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
    CONF_PV_POWER,
    CONF_RESTART_BUTTON,
    CONF_SESSION_ENERGY,
    CONF_SINGLE_PHASE_SWITCH,
    CONF_SOLCAST_NOW_POWER,
    CONF_SOLCAST_TODAY,
    CONF_SOLCAST_TODAY_REMAINING,
    CONF_SOLCAST_TOMORROW,
    DEBOUNCE_SECONDS,
    DEFAULT_SETTINGS,
    DEFAULT_STATE,
    DOMAIN,
    EMERGENCY_IMPORT_W,
    ERR_RESTART_MIN_MINUTEN,
    FAULT_CLEAR_STABIEL_MINUTEN,
    GRACE_HOURS,
    MAX_RESTART_POGINGEN,
    PHASE_SETTLE_S,
    RESTART_COOLDOWN_MIN_MINUTEN,
    SET_ACCU_CAPACITEIT_KWH,
    SET_ANDERE_AUTO,
    SET_DAGELIJKSE_VERTREKTIJD,
    SET_DEBUG,
    SET_DOEL_SOC,
    SET_FASEWISSEL_MIN_MINUTEN,
    SET_LAADLIMIET_OVERRIDE,
    SET_LAADMODUS,
    SET_MAX_A,
    SET_MIN_A,
    SET_PV_MARGE_WATT,
    SET_REGELEN_ACTIEF,
    SET_SLIM_LADEN_AAN,
    SET_VERTREKDATUM,
    SET_VERTREKTIJD,
    SET_ZON_BENUT_FACTOR,
    ST_ENERGY_START,
    ST_LAST_AMP_CHANGE,
    ST_LAST_CHARGE_DEMAND,
    ST_LAST_CHARGE_SWITCH,
    ST_LAST_PHASE_CHANGE,
    ST_LAST_RESTART,
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
_ROLLING_MAX_AGE = timedelta(minutes=2)


class PeblarCoordinator(DataUpdateCoordinator[ChargeDecision]):
    """Regelt slim laden: leest bronnen, rekent, stuurt de lader aan."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.conf = {**entry.data, **entry.options}
        self._store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.state_data: dict = dict(DEFAULT_STATE)
        self._grid_samples: deque[tuple[datetime, float]] = deque()
        self._charger_samples: deque[tuple[datetime, float]] = deque()
        self._prev_status: str | None = None
        self._time_changed_flag = False
        self._debounce_cancel = None
        self._unsub_listeners: list = []

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
        """Bewaar settings + interne state."""
        await self._store.async_save(
            {"settings": self.settings, "state": self.state_data}
        )

    def get_setting(self, key: str):
        return self.settings.get(key, DEFAULT_SETTINGS.get(key))

    async def async_set_setting(self, key: str, value) -> None:
        """Wijzig een instelling, sla op en trigger een (gedebouncede) refresh."""
        self.settings[key] = value
        if key == SET_VERTREKTIJD:
            self._time_changed_flag = True
        await self.async_save_store()
        self._schedule_refresh_debounced()

    def _get_state(self, key: str):
        return self.state_data.get(key, DEFAULT_STATE.get(key))

    def _set_state(self, key: str, value) -> None:
        self.state_data[key] = value

    # ------------------------------------------------------------------
    # Listeners / debounce
    # ------------------------------------------------------------------
    def setup_listeners(self) -> None:
        """Reageer op wijzigingen van de bronsensoren (gedebounced)."""
        entities = [
            self.conf.get(k)
            for k in (
                CONF_CHARGER_STATUS,
                CONF_CHARGER_POWER,
                CONF_GRID_POWER,
                CONF_PV_POWER,
                CONF_CAR_SOC,
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

    @callback
    def _on_source_change(self, event) -> None:
        self._schedule_refresh_debounced()

    @callback
    def _schedule_refresh_debounced(self) -> None:
        if self._debounce_cancel is not None:
            self._debounce_cancel()

        async def _fire(_now) -> None:
            self._debounce_cancel = None
            await self.async_request_refresh()

        self._debounce_cancel = async_call_later(self.hass, DEBOUNCE_SECONDS, _fire)

    def shutdown(self) -> None:
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        if self._debounce_cancel is not None:
            self._debounce_cancel()
            self._debounce_cancel = None

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

    def _rolling_mean(
        self, samples: deque, now: datetime, live: float | None
    ) -> float | None:
        if live is not None:
            samples.append((now, live))
        cutoff = now - _ROLLING_MAX_AGE
        while samples and samples[0][0] < cutoff:
            samples.popleft()
        if not samples:
            return None
        return sum(v for _, v in samples) / len(samples)

    def _solar_before_dep(self, now: datetime, deadline: datetime) -> tuple[float, bool]:
        """Som de half-uur-slots (Solcast detailedForecast) tot de deadline."""
        total = 0.0
        detail_ok = False
        for key in (CONF_SOLCAST_TODAY, CONF_SOLCAST_TOMORROW):
            entity_id = self.conf.get(key)
            if not entity_id:
                continue
            st = self.hass.states.get(entity_id)
            if st is None:
                continue
            fc = st.attributes.get("detailedForecast")
            if not fc:
                continue
            detail_ok = True
            for item in fc:
                ts = dt_util.parse_datetime(str(item.get("period_start")))
                if ts is None:
                    continue
                if ts + timedelta(minutes=30) > now and ts < deadline:
                    try:
                        total += float(item.get("pv_estimate") or 0)
                    except (TypeError, ValueError):
                        pass
        return round(total, 3), detail_ok

    # ------------------------------------------------------------------
    # Inputs bouwen
    # ------------------------------------------------------------------
    def _build_inputs(self, now: datetime) -> ChargeInputs:
        min_a = int(self.get_setting(SET_MIN_A))
        max_a = int(self.get_setting(SET_MAX_A))

        # Vermogens (live + rolling means).
        grid_live = self._num(CONF_GRID_POWER)
        grid_ok = grid_live is not None
        charger_live = self._num(CONF_CHARGER_POWER)
        grid_avg = self._rolling_mean(self._grid_samples, now, grid_live)
        charger_avg = self._rolling_mean(self._charger_samples, now, charger_live)
        grid_w = grid_live if grid_live is not None else (grid_avg or 0.0)
        charger_w = charger_live if charger_live is not None else (charger_avg or 0.0)
        charge_power_now = charger_avg if charger_avg is not None else charger_w

        # Forecast: Solcast met forecast.solar-fallback.
        fc_today = self._num(CONF_SOLCAST_TODAY_REMAINING)
        solar_ok = fc_today is not None
        if fc_today is None:
            fc_today = self._num(CONF_FC_TODAY_REMAINING, 0.0) or 0.0
        fc_tomorrow = self._num(CONF_SOLCAST_TOMORROW)
        if fc_tomorrow is None:
            fc_tomorrow = self._num(CONF_FC_TOMORROW, 0.0) or 0.0
        pv_now = self._num(CONF_SOLCAST_NOW_POWER)
        if pv_now is None:
            pv_now = self._num(CONF_FC_NOW_POWER, 0.0) or 0.0
        pv_prod = self._num(CONF_PV_POWER)
        if pv_prod is None:
            pv_prod = pv_now

        # Vertrek.
        dep_time = str(self.get_setting(SET_VERTREKTIJD) or "00:00:00")
        dep_date = self.get_setting(SET_VERTREKDATUM)
        no_departure = dep_time in ("00:00:00", "", "unknown", "unavailable", None)

        # detailedForecast tot deadline.
        solar_before = 0.0
        detail_ok = False
        if not no_departure and dep_date:
            try:
                day_offset = (
                    datetime.strptime(dep_date, "%Y-%m-%d").date() - now.date()
                ).days
                h, m, s = (int(x) for x in dep_time.split(":"))
                dep = now.replace(hour=h, minute=m, second=s, microsecond=0) + timedelta(
                    days=day_offset
                )
                deadline = dep - timedelta(hours=GRACE_HOURS)
                solar_before, detail_ok = self._solar_before_dep(now, deadline)
            except (ValueError, TypeError):
                solar_before, detail_ok = 0.0, False

        # Fase / ampère toestand.
        current_phase = 1 if self._is_on(CONF_SINGLE_PHASE_SWITCH) else 3
        current_amps = int(self._num(CONF_CHARGE_LIMIT_NUMBER, min_a) or min_a)

        inp = ChargeInputs(
            now=now,
            laadmodus=str(self.get_setting(SET_LAADMODUS)),
            slim_laden=bool(self.get_setting(SET_SLIM_LADEN_AAN)),
            other_car=bool(self.get_setting(SET_ANDERE_AUTO)),
            override_limit=bool(self.get_setting(SET_LAADLIMIET_OVERRIDE)),
            preclimate_active=self._is_on(CONF_PRECLIMATE_SWITCH),
            peb_status=self._str(CONF_CHARGER_STATUS),
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
            solar_ok=solar_ok,
            solar_detail_ok=detail_ok,
            solar_before_dep_kwh=solar_before,
            pv_production_w=pv_prod,
            grid_w=grid_w,
            grid_ok=grid_ok,
            grid_avg_w=grid_avg if grid_avg is not None else grid_w,
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

        await self._handle_capacity(inp, now)
        await self._handle_faults(inp, now, regelen)
        await self._handle_departure(decision, now, regelen)
        if regelen and not decision.dep_reset_needed:
            await self._apply_control(inp, decision, now)

        await self.async_save_store()
        await self._log_cycle(decision)
        return decision

    # ------------------------------------------------------------------
    # Capaciteit leren (charging <-> suspended overgangen)
    # ------------------------------------------------------------------
    async def _handle_capacity(self, inp: ChargeInputs, now: datetime) -> None:
        status = inp.peb_status
        prev = self._prev_status
        self._prev_status = status
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
                await self.async_set_setting(
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
            await self._dismiss("peblar_lader_gestrand")

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
            if regelen and self._is_on(CONF_CHARGE_SWITCH):
                await self._service("switch", "turn_off", CONF_CHARGE_SWITCH)
            await self._notify(
                "peblar_lader_gestrand",
                "Peblar lader gestopt - storing blijft",
                f"De lader is {MAX_RESTART_POGINGEN}x herstart maar de "
                f"{'fout' if err_active else 'waarschuwing'} blijft. Laden gestopt "
                "uit veiligheid; los de storing handmatig op.",
            )
            return

        if restart_needed:
            if regelen:
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
    async def _handle_departure(
        self, d: ChargeDecision, now: datetime, regelen: bool
    ) -> None:
        if d.dep_reset_needed:
            await self.async_set_setting(SET_VERTREKTIJD, "00:00:00")
            self._time_changed_flag = False
            await self.async_set_setting(SET_VERTREKDATUM, now.strftime("%Y-%m-%d"))
        elif d.dep_date_needs_update and d.desired_dep_date:
            await self.async_set_setting(SET_VERTREKDATUM, d.desired_dep_date)

    # ------------------------------------------------------------------
    # Regelacties toepassen (achter observe-only gate)
    # ------------------------------------------------------------------
    async def _apply_control(
        self, inp: ChargeInputs, d: ChargeDecision, now: datetime
    ) -> None:
        min_a = inp.min_a

        # Rust-stand: lader suspended en niet onze auto -> 1 fase + min A.
        if d.peb_status == "suspended" and not d.my_car_here and not inp.other_car:
            if not self._is_on(CONF_SINGLE_PHASE_SWITCH):
                await self._service("switch", "turn_on", CONF_SINGLE_PHASE_SWITCH)
            await self._set_number(clamp(min(min_a, 16), 6, 16))
            return

        if not d.my_car_here:
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

        # W/A leren (persisteer geklemde EMA).
        if d.update_wpa:
            self._set_state(ST_WPA_STORED, clamp(d.wpa_new, WPA_MIN, WPA_MAX))

        # Ampère / fase toepassen.
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
            await asyncio.sleep(PHASE_SETTLE_S)

    # ------------------------------------------------------------------
    # Service-/notificatiehelpers
    # ------------------------------------------------------------------
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

    db_status: str = "unknown"
