"""Pure regellogica voor Peblar Slim Laden.

Alle berekeningen uit de oorspronkelijke automation (`variables:`) zijn hier
omgezet naar pure Python. Deze module heeft GEEN Home Assistant-afhankelijkheden
zodat de logica los te unit-testen is en pariteit met de YAML te borgen valt.

Kernprincipes (uit het overdrachtsdocument):
- Amperewissels zijn naadloos (gratis) -> deadband + korte cooldown.
- Fasewissels en laadstops sluiten de sessie (duur) -> hysterese + min-verblijf.
- W/A != 230: empirisch geleerd uit de GEMIDDELDE-meting, nooit per-fase.
- Grid-vloer op de ACTUELE SoC (voorkomt inhaalpiek).
- Preclimate: laden aanhouden; auto zelfbegrenst ~3500W -> W/A-leren onderdrukken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .const import (
    AMP_SETTLE_S,
    CHARGE_SWITCH_MIN_MINUTEN,
    CHARGING_ACTIVE_W,
    EMERGENCY_IMPORT_W,
    GRACE_HOURS,
    MEAS_SETTLE_S,
    PHASE_UP_BUFFER_W,
    STOP_GRACE_MINUTEN,
    WPA_EMA_ALPHA,
    WPA_VALID_MAX,
    WPA_VALID_MIN,
)


def clamp(value: float, low: float, high: float) -> float:
    """Klem value tussen low en high."""
    return max(low, min(high, value))


@dataclass
class ChargeInputs:
    """Alle (reeds uitgelezen) inputs voor één regelcyclus."""

    now: datetime

    # Modus / vlaggen
    laadmodus: str = "Hybride"
    slim_laden: bool = True
    other_car: bool = False
    override_limit: bool = False
    preclimate_active: bool = False
    peb_status: str = "unknown"

    # Grenzen / instellingen
    min_a: int = 6
    max_a: int = 16
    pv_marge_watt: float = 50.0
    zon_benut_factor: float = 0.6
    fasewissel_min_minuten: int = 10

    # SoC / accu
    soc_raw: float | None = None
    soc_target: int = 100
    battery_capacity_kwh: float = 50.0

    # Vertrek
    dep_time: str = "00:00:00"           # HH:MM:SS ; 00:00:00 = geen
    dep_date: str | None = None          # YYYY-MM-DD (opgeslagen)
    daily_departure: bool = False
    time_changed: bool = False           # trigger kwam van vertrektijd-wijziging

    # Forecast
    fc_today_remaining: float = 0.0
    fc_tomorrow: float = 0.0
    pv_now_w: float = 0.0                 # Solcast huidig vermogen (of fallback)
    solar_ok: bool = False               # Solcast resterende-vandaag beschikbaar
    solar_detail_ok: bool = False        # detailedForecast beschikbaar
    solar_before_dep_kwh: float = 0.0    # som half-uur-slots tot deadline (coord.)
    pv_production_w: float = 0.0         # Hoymiles live (of pv_now)

    # Vermogen
    grid_w: float = 0.0
    grid_ok: bool = False
    grid_avg_w: float = 0.0
    charger_w: float = 0.0
    charger_avg_w: float = 0.0
    charge_power_now_w: float = 0.0      # gemiddelde-sensor (of live)

    # Fase / ampère toestand
    current_phase: int = 3               # 1 of 3 (afgeleid uit fase-switch)
    current_amps: int = 6
    charge_now_on: bool = False          # laad-switch aan?
    wpa_stored: float = 230.0

    # Cooldown-timers (seconden sinds ...)
    seconds_since_amp_change: float = 1e9
    minutes_since_phase_change: float = 1e9
    seconds_since_charge_switch: float = 1e9
    seconds_since_charge_demand: float = 1e9

    # Sessie-energie (telemetrie)
    session_energy_kwh: float = 0.0

    # Geleerde signalen uit de database (Fase C-E). None = nog geen data.
    forecast_bias: float = 1.0           # schaalt expected_solar_kwh
    kwh_per_pct: float | None = None     # geleerde kWh per 1% SoC (incl. verlies)
    wpa_1p: float | None = None          # geleerde W/A op 1 fase
    wpa_3p: float | None = None          # geleerde W/A op 3 fasen
    ramp_bias: float = 0.0               # vervroegt de ramp bij lage hit-rate


@dataclass
class ChargeDecision:
    """Resultaat van één regelcyclus: telemetrie + toe te passen acties."""

    # Telemetrie / observability
    laadmodus: str = "Hybride"
    peb_status: str = "unknown"
    soc_now: float = 0.0
    soc_valid: bool = False
    soc_target: int = 100
    kwh_needed: float = 0.0
    hours_left: float = 0.0
    time_left_display: str = ""
    desired_phase: int = 3
    current_phase: int = 3
    amps_set: int = 6
    charger_w: float = 0.0
    grid_w: float = 0.0
    pv_now_w: float = 0.0
    available_solar_w: float = 0.0
    base_floor_w: float = 0.0
    ramp_factor: float = 0.0
    urgentie: float = 0.0
    must_charge_w: float = 0.0
    target_w: float = 0.0
    real_w_per_a: float = 230.0
    wpa_meas: float = 0.0
    wpa_meas_valid: bool = False
    wpa_new: float = 230.0
    expected_solar_kwh: float = 0.0
    behind_schedule: bool = False
    session_energy_kwh: float = 0.0

    # Toestand
    forced_full: bool = False
    solar_only: bool = False
    no_departure: bool = True
    my_car_here: bool = False
    want_charge: bool = False
    want_charge_raw: bool = False
    within_stop_grace: bool = False
    preclimate_active: bool = False
    grid_ok: bool = False

    # Vertrekdatum-beheer
    dep_reset_needed: bool = False
    dep_date_needs_update: bool = False
    desired_dep_date: str = ""

    # Acties (door coordinator toe te passen)
    phase_change_needed: bool = False
    amps_change_needed: bool = False
    charge_switch_cooldown_ok: bool = False
    set_charge_on: bool | None = None    # None = geen wijziging
    update_wpa: bool = False


def _today_at(now: datetime, hhmmss: str) -> datetime:
    """Datetime van vandaag op het opgegeven tijdstip (HH:MM:SS)."""
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return now.replace(hour=h, minute=m, second=s, microsecond=0)


def compute(inp: ChargeInputs) -> ChargeDecision:  # noqa: C901 - port van YAML
    """Bereken de laadbeslissing voor één cyclus (pariteit met de automation)."""
    d = ChargeDecision()
    d.laadmodus = inp.laadmodus
    d.peb_status = inp.peb_status
    d.soc_target = inp.soc_target
    d.current_phase = inp.current_phase
    d.charger_w = inp.charger_w
    d.grid_w = inp.grid_w
    d.pv_now_w = inp.pv_now_w
    d.session_energy_kwh = inp.session_energy_kwh
    d.preclimate_active = inp.preclimate_active
    d.grid_ok = inp.grid_ok

    # --- SoC ---
    soc_valid = (
        inp.soc_raw is not None
        and 0 <= inp.soc_raw <= 100
    )
    soc_now = round(inp.soc_raw, 1) if (soc_valid and inp.soc_raw is not None) else 0.0
    d.soc_valid = soc_valid
    d.soc_now = soc_now

    kwh_needed = 0.0
    if soc_valid and inp.soc_target > soc_now:
        if inp.kwh_per_pct is not None:
            # Geleerde kWh per procent (incl. laadverlies) heeft voorrang.
            kwh_needed = (inp.soc_target - soc_now) * inp.kwh_per_pct
        else:
            kwh_needed = (inp.soc_target - soc_now) / 100 * inp.battery_capacity_kwh
    d.kwh_needed = kwh_needed

    # --- Vertrektijd/datum ---
    no_departure = inp.dep_time in ("00:00:00", "", "unknown", "unavailable", None)
    d.no_departure = no_departure
    dep_date_valid = inp.dep_date not in ("", "unknown", "unavailable", None)

    time_passed_today = False
    if not no_departure:
        time_passed_today = inp.now >= _today_at(inp.now, inp.dep_time)

    if no_departure:
        next_dep_date = ""
    else:
        next_dep_date = (
            inp.now.date() + timedelta(days=1 if time_passed_today else 0)
        ).strftime("%Y-%m-%d")

    dep_moment_past = False
    if not no_departure and dep_date_valid:
        try:
            dep_moment = datetime.strptime(
                f"{inp.dep_date} {inp.dep_time}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=inp.now.tzinfo)
            dep_moment_past = inp.now >= dep_moment
        except ValueError:
            dep_moment_past = False

    dep_reset_needed = (
        not no_departure and not inp.daily_departure
        and not inp.time_changed and dep_moment_past
    )
    dep_arm_needed = (
        not no_departure and inp.time_changed and inp.dep_date != next_dep_date
    )
    dep_roll_needed = (
        not no_departure and inp.daily_departure and dep_date_valid
        and inp.dep_date != next_dep_date
    )
    d.dep_reset_needed = dep_reset_needed
    d.desired_dep_date = next_dep_date
    d.dep_date_needs_update = (
        (dep_arm_needed or dep_roll_needed) and not dep_reset_needed
    )

    day_offset = 0
    if not no_departure and dep_date_valid and inp.dep_date is not None:
        try:
            day_offset = (
                datetime.strptime(inp.dep_date, "%Y-%m-%d").date() - inp.now.date()
            ).days
        except ValueError:
            day_offset = 0

    hours_left = 0.0
    if not no_departure:
        dep = _today_at(inp.now, inp.dep_time) + timedelta(days=day_offset)
        hours_left = round(
            (dep - timedelta(hours=GRACE_HOURS) - inp.now).total_seconds() / 3600, 3
        )
    d.hours_left = hours_left
    minutes_left = hours_left * 60
    d.time_left_display = (
        f"{round(minutes_left)} min" if hours_left < 1 else f"{round(hours_left, 2)} u"
    )
    deadline_passed = not no_departure and hours_left <= 0 and kwh_needed > 0

    # --- Zonprognose ---
    solar_today_capped_kwh = min(
        inp.fc_today_remaining, max(0.0, (inp.pv_now_w / 1000) * hours_left)
    )
    tomorrow_frac = 0.0
    if not no_departure:
        dep = _today_at(inp.now, inp.dep_time) + timedelta(days=day_offset)
        if dep.date() > inp.now.date():
            h = dep.hour + dep.minute / 60
            if h >= 16:
                tomorrow_frac = 1.0
            elif h <= 7:
                tomorrow_frac = 0.0
            else:
                tomorrow_frac = round((h - 7) / 9, 2)

    if inp.solar_detail_ok and not no_departure:
        expected_solar_kwh = inp.solar_before_dep_kwh * inp.zon_benut_factor
    else:
        expected_solar_kwh = (
            (solar_today_capped_kwh + inp.fc_tomorrow * tomorrow_frac)
            * inp.zon_benut_factor
        )
    # Geleerde forecast-bias corrigeert structurele over-/onderschatting.
    expected_solar_kwh *= inp.forecast_bias
    d.expected_solar_kwh = expected_solar_kwh
    grid_deficit_kwh = max(0.0, kwh_needed - expected_solar_kwh)

    pv_active = inp.pv_production_w > 100

    # --- Grid-vloer / ramp (op ACTUELE SoC) ---
    charger_max_w = inp.max_a * 3 * 225
    pure_floor_w = (
        0.0 if (no_departure or hours_left <= 0)
        else kwh_needed / hours_left * 1000
    )
    floor_from_solar_w = (
        0.0 if (no_departure or hours_left <= 0)
        else grid_deficit_kwh / hours_left * 1000
    )
    min_floor_w = pure_floor_w * 0.6
    base_floor_w = max(floor_from_solar_w, min_floor_w)
    d.base_floor_w = base_floor_w

    min_time_h = 0.0 if charger_max_w <= 0 else kwh_needed / charger_max_w * 1000
    urgentie = (
        0.0 if (no_departure or hours_left <= 0)
        else min_time_h / hours_left
    )
    d.urgentie = urgentie
    # ramp_bias vervroegt de ramp (start eerder dan urgentie 0.67) wanneer de
    # doel-SoC de laatste tijd vaak gemist werd.
    ramp_start = 0.67 - clamp(inp.ramp_bias, 0.0, 0.3)
    ramp_factor = clamp((urgentie - ramp_start) / 0.33, 0.0, 1.0)
    d.ramp_factor = ramp_factor
    ramp_target_w = base_floor_w + ramp_factor * (charger_max_w - base_floor_w)

    behind_schedule = (
        not no_departure and kwh_needed > 0
        and (deadline_passed or urgentie >= 1.0)
    )
    d.behind_schedule = behind_schedule
    must_charge_w = (
        0.0 if no_departure
        else (999999.0 if (deadline_passed or behind_schedule) else ramp_target_w)
    )
    d.must_charge_w = must_charge_w

    # --- Zonoverschot ---
    solar_for_car_w = inp.charger_w - inp.grid_w
    available_solar_w = max(
        0.0,
        (solar_for_car_w - inp.pv_marge_watt) if inp.grid_ok
        else (inp.pv_now_w - inp.pv_marge_watt),
    )
    d.available_solar_w = available_solar_w
    available_solar_avg_w = max(
        0.0,
        (inp.charger_avg_w - inp.grid_avg_w - inp.pv_marge_watt) if inp.grid_ok
        else (inp.pv_now_w - inp.pv_marge_watt),
    )

    # --- Modus / target ---
    forced_full = (
        inp.override_limit or not inp.slim_laden or inp.other_car
        or inp.laadmodus == "Snel"
    )
    solar_only = (
        inp.laadmodus == "Zon"
        or (inp.laadmodus == "Hybride" and no_departure)
    )
    d.forced_full = forced_full
    d.solar_only = solar_only

    target_w = (
        inp.max_a * 3 * 230 if forced_full
        else (available_solar_w if solar_only
              else max(must_charge_w, available_solar_w))
    )
    target_avg_w = (
        inp.max_a * 3 * 230 if forced_full
        else (available_solar_avg_w if solar_only
              else max(must_charge_w, available_solar_avg_w))
    )

    # --- Preclimate: laden aanhouden + genoeg vermogen (auto zelfbegrenst) ---
    # Geldt in alle niet-geforceerde modi (ook Zon/solar_only): anders trekt de
    # auto de ~3500W klimaatlast uit de eigen accu i.p.v. de lader.
    if inp.preclimate_active and not forced_full:
        target_w = max(target_w, 3500.0)
        target_avg_w = max(target_avg_w, 3500.0)
    d.target_w = target_w

    # --- Fasekeuze ---
    three_phase_min_w = inp.min_a * 3 * 230
    phase_up_signal_w = max(must_charge_w, available_solar_avg_w)
    if forced_full:
        desired_phase_raw = 3
    elif inp.current_phase == 1 and phase_up_signal_w >= three_phase_min_w + PHASE_UP_BUFFER_W:
        desired_phase_raw = 3
    elif inp.current_phase == 3 and target_avg_w < three_phase_min_w:
        desired_phase_raw = 1
    else:
        desired_phase_raw = inp.current_phase

    switch_allowed = inp.minutes_since_phase_change >= inp.fasewissel_min_minuten
    grid_import_now = inp.grid_w > EMERGENCY_IMPORT_W
    force_phase_down = (
        inp.current_phase == 3 and desired_phase_raw == 1 and grid_import_now
    )
    if (switch_allowed or forced_full or force_phase_down
            or desired_phase_raw == inp.current_phase):
        desired_phase = desired_phase_raw
    else:
        desired_phase = inp.current_phase
    d.desired_phase = desired_phase
    d.phase_change_needed = desired_phase != inp.current_phase

    # --- W/A meten & leren ---
    charging_active = (
        inp.peb_status == "charging" and inp.charge_power_now_w > CHARGING_ACTIVE_W
    )
    wpa_meas = 0.0
    if charging_active and inp.current_amps > 0:
        wpa_meas = inp.charge_power_now_w / (inp.current_amps * inp.current_phase)
    d.wpa_meas = wpa_meas
    wpa_meas_valid = (
        WPA_VALID_MIN <= wpa_meas <= WPA_VALID_MAX
        and inp.seconds_since_amp_change >= MEAS_SETTLE_S
        and not inp.preclimate_active  # klimaatlast vervuilt W/A niet
    )
    d.wpa_meas_valid = wpa_meas_valid
    wpa_new = round(
        (1 - WPA_EMA_ALPHA) * inp.wpa_stored + WPA_EMA_ALPHA * wpa_meas, 1
    )
    d.wpa_new = wpa_new
    # Per-fase geleerde W/A (uit de DB) heeft voorrang voor de amp-berekening;
    # anders de live EMA-waarde als fallback.
    learned_wpa = inp.wpa_3p if desired_phase == 3 else inp.wpa_1p
    real_w_per_a = learned_wpa if learned_wpa is not None else inp.wpa_stored
    d.real_w_per_a = real_w_per_a
    d.update_wpa = wpa_meas_valid and abs(wpa_new - inp.wpa_stored) >= 1

    # --- Ampèrekeuze (deadband) ---
    step = desired_phase * real_w_per_a
    avail = target_w
    ideal = round(avail / step) if step > 0 else inp.current_amps
    c = inp.current_amps
    amp_cooldown_ok = inp.seconds_since_amp_change >= AMP_SETTLE_S
    if forced_full:
        amps_raw = round(avail / step) if step > 0 else inp.max_a
    elif d.phase_change_needed:
        amps_raw = inp.min_a
    elif inp.grid_w > EMERGENCY_IMPORT_W and ideal < c:
        amps_raw = ideal
    elif amp_cooldown_ok and ideal >= c + 1 and avail >= (c + 1) * step * 0.97:
        amps_raw = c + 1
    elif amp_cooldown_ok and ideal <= c - 1 and avail <= (c - 1) * step * 1.03:
        amps_raw = c - 1
    else:
        amps_raw = c
    amps_helper = int(clamp(amps_raw, inp.min_a, inp.max_a))
    amps_clamped = int(clamp(amps_helper, 6, 16))
    d.amps_set = amps_clamped
    d.amps_change_needed = abs(amps_clamped - inp.current_amps) >= 1

    # --- Laden aan/uit ---
    min_charge_w = inp.min_a * desired_phase * 230
    charge_switch_min_s = CHARGE_SWITCH_MIN_MINUTEN * 60
    charge_switch_cooldown_ok = inp.seconds_since_charge_switch >= charge_switch_min_s
    d.charge_switch_cooldown_ok = charge_switch_cooldown_ok
    solar_start_w = min_charge_w * 1.10
    solar_stop_w = min_charge_w * 0.70
    solar_threshold_w = solar_stop_w if inp.charge_now_on else solar_start_w
    want_charge_raw = (
        forced_full
        or available_solar_w >= solar_threshold_w
        or (inp.laadmodus == "Hybride" and not no_departure and pv_active)
        or (not solar_only and must_charge_w > 0)
        or inp.preclimate_active  # laden aanhouden tijdens voorklimatisering
    )
    d.want_charge_raw = want_charge_raw
    within_stop_grace = (
        inp.seconds_since_charge_demand < STOP_GRACE_MINUTEN * 60
    )
    d.within_stop_grace = within_stop_grace
    want_charge = want_charge_raw or (inp.charge_now_on and within_stop_grace)
    d.want_charge = want_charge

    # Onze auto is aangesloten. Wanneer de lader ACTIEF laadt is de auto
    # aantoonbaar aanwezig -> dan regelen we ook zonder geldige SoC (anders zou
    # een SoC-uitval het stoppen/regelen blokkeren en blijven we importeren).
    # Bij 'suspended' blijven we conservatief en eisen we wel een geldige SoC.
    my_car_here = (
        not inp.other_car
        and (
            inp.peb_status == "charging"
            or (inp.peb_status == "suspended" and soc_valid)
            or (inp.preclimate_active and inp.peb_status in ("charging", "suspended"))
        )
    )
    d.my_car_here = my_car_here

    # Bepaal de gewenste laadschakelaar-stand (None = niet wijzigen).
    if my_car_here:
        if not want_charge:
            if inp.charge_now_on and charge_switch_cooldown_ok:
                d.set_charge_on = False
        else:
            if not inp.charge_now_on and charge_switch_cooldown_ok:
                d.set_charge_on = True

    return d
