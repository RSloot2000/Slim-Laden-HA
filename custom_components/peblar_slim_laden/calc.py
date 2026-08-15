"""Pure regellogica voor Peblar Slim Laden.

Deze module heeft GEEN Home Assistant-afhankelijkheden zodat de logica los te
unit-testen is.

Kernprincipes:
- Amperewissels zijn naadloos (gratis) -> deadband + korte cooldown.
- Fasewissels en laadstops sluiten de sessie (duur) -> hysterese + min-verblijf.
- W/A != 230: empirisch geleerd uit de GEMIDDELDE-meting, nooit per-fase.
- Grid-vloer op de ACTUELE SoC (voorkomt inhaalpiek).
- Preclimate: laden aanhouden; auto zelfbegrenst ~3500W -> W/A-leren onderdrukken.

Laadstrategie per modus:
- Snel (of override / andere auto): altijd maximaal vermogen, 3 fasen.
- Zon: uitsluitend PV-overschot; geen overschot = niet laden.
- Hybride zonder vertrektijd: identiek aan Zon.
- Hybride met vertrektijd: volg het PV-overschot zolang dat er is. Wordt de zon
  te zwak, dan alleen doorladen voor zover de verwachte zon tot het vertrek het
  restant niet dekt (`base_floor_w`); dekt de zon het wel, dan pauzeert het laden
  ('s nachts) en ramt het bij zonsopkomst vanzelf weer op met het overschot.
  Nadert de deadline, dan neemt `ramp_factor` het over tot vol vermogen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .const import (
    AMP_OFFSET_A,
    AMP_SETTLE_S,
    CHARGE_SWITCH_MIN_MINUTEN,
    CHARGING_ACTIVE_W,
    EMERGENCY_IMPORT_W,
    GRACE_HOURS,
    HW_MAX_A,
    HW_MIN_A,
    MEAS_SETTLE_S,
    NO_DEPARTURE_TIME,
    NO_VALUE_STRINGS,
    NOMINAL_W_PER_A,
    PHASE_UP_BUFFER_W,
    PRECLIMATE_POWER_W,
    SOC_RESTART_DEADBAND,
    SOLAR_TRUST_FACTOR,
    STOP_GRACE_MINUTEN,
    WPA_EMA_ALPHA,
    WPA_VALID_MAX,
    WPA_VALID_MIN,
)


def clamp(value: float, low: float, high: float) -> float:
    """Klem value tussen low en high (high wint als high < low)."""
    return max(low, min(high, value))


def delivered_amps(setpoint_a: float) -> float:
    """Ampères die de lader werkelijk trekt bij dit setpoint."""
    return max(0.0, setpoint_a - AMP_OFFSET_A)


def power_at(setpoint_a: float, phase: int, w_per_a: float) -> float:
    """Vermogen dat dit setpoint oplevert."""
    return delivered_amps(setpoint_a) * phase * w_per_a


def setpoint_for(power_w: float, phase: int, w_per_a: float) -> int:
    """Setpoint dat het gevraagde vermogen benadert."""
    step = phase * w_per_a
    if step <= 0:
        return HW_MIN_A
    return int(round(power_w / step)) + AMP_OFFSET_A


def has_departure(dep_time: str | None) -> bool:
    """True als er een echte vertrektijd is ingesteld."""
    return dep_time not in NO_VALUE_STRINGS and dep_time != NO_DEPARTURE_TIME


def parse_departure(
    now: datetime, dep_time: str | None, dep_date: str | None
) -> tuple[datetime | None, datetime | None]:
    """Geef (vertrekmoment, deadline) terug; (None, None) zonder vertrektijd.

    De deadline is het vertrekmoment minus de grace-periode. De datum is
    optioneel: zonder datum wordt de tijd van vandaag gebruikt.
    """
    if not has_departure(dep_time):
        return None, None
    try:
        h, m, s = (int(x) for x in str(dep_time).split(":"))
        dep = now.replace(hour=h, minute=m, second=s, microsecond=0)
    except (ValueError, TypeError):
        return None, None
    if dep_date not in NO_VALUE_STRINGS:
        try:
            offset = (
                datetime.strptime(str(dep_date), "%Y-%m-%d").date() - now.date()
            ).days
            dep += timedelta(days=offset)
        except (ValueError, TypeError):
            pass
    return dep, dep - timedelta(hours=GRACE_HOURS)


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
    min_a: int = HW_MIN_A
    max_a: int = HW_MAX_A
    pv_marge_watt: float = 50.0
    zon_benut_factor: float = 0.6
    fasewissel_min_minuten: int = 10

    # SoC / accu
    soc_raw: float | None = None
    soc_target: int = 100
    battery_capacity_kwh: float = 50.0

    # Vertrek
    dep_time: str = NO_DEPARTURE_TIME    # HH:MM:SS ; 00:00:00 = geen
    dep_date: str | None = None          # YYYY-MM-DD (opgeslagen)
    daily_departure: bool = False
    time_changed: bool = False           # trigger kwam van vertrektijd-wijziging

    # Forecast
    fc_today_remaining: float = 0.0
    fc_tomorrow: float = 0.0
    pv_now_w: float = 0.0                 # Solcast huidig vermogen (of fallback)
    solar_ok: bool = False               # Solcast resterende-vandaag beschikbaar
    solar_detail_ok: bool = False        # detailedForecast dekt de hele periode
    solar_before_dep_kwh: float = 0.0    # som half-uur-slots tot deadline (coord.)

    # Vermogen
    grid_w: float = 0.0
    grid_ok: bool = False
    grid_avg_w: float = 0.0
    charger_w: float = 0.0
    charger_avg_w: float = 0.0
    charge_power_now_w: float = 0.0      # gemiddelde-sensor (of live)

    # Fase / ampère toestand
    current_phase: int = 3               # 1 of 3 (afgeleid uit fase-switch)
    current_amps: int = HW_MIN_A
    charge_now_on: bool = False          # laad-switch aan?
    wpa_stored: float = float(NOMINAL_W_PER_A)

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
    amps_set: int = HW_MIN_A
    charger_w: float = 0.0
    grid_w: float = 0.0
    pv_now_w: float = 0.0
    available_solar_w: float = 0.0
    base_floor_w: float = 0.0
    ramp_factor: float = 0.0
    urgentie: float = 0.0
    must_charge_w: float = 0.0
    target_w: float = 0.0
    real_w_per_a: float = float(NOMINAL_W_PER_A)
    wpa_meas: float = 0.0
    wpa_meas_valid: bool = False
    wpa_new: float = float(NOMINAL_W_PER_A)
    expected_solar_kwh: float = 0.0
    behind_schedule: bool = False
    session_energy_kwh: float = 0.0

    # Toestand
    forced_full: bool = False
    solar_only: bool = False
    no_departure: bool = True
    car_here: bool = False
    my_car_here: bool = False
    want_charge: bool = False
    want_charge_raw: bool = False
    within_stop_grace: bool = False
    preclimate_active: bool = False
    grid_ok: bool = False
    solar_pause: bool = False

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


def _today_at(now: datetime, hhmmss: str) -> datetime | None:
    """Datetime van vandaag op het opgegeven tijdstip (None bij onzin-invoer)."""
    try:
        h, m, s = (int(x) for x in str(hhmmss).split(":"))
        return now.replace(hour=h, minute=m, second=s, microsecond=0)
    except (ValueError, TypeError):
        return None


def compute(inp: ChargeInputs) -> ChargeDecision:  # noqa: C901 - regellus
    """Bereken de laadbeslissing voor één cyclus."""
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

    # Instelgrenzen consistent houden: min mag nooit boven max liggen.
    min_a = int(clamp(inp.min_a, HW_MIN_A, HW_MAX_A))
    max_a = int(clamp(inp.max_a, min_a, HW_MAX_A))

    # --- SoC ---
    soc_valid = (
        inp.soc_raw is not None
        and 0 <= inp.soc_raw <= 100
    )
    soc_now = round(inp.soc_raw, 1) if (soc_valid and inp.soc_raw is not None) else 0.0
    d.soc_valid = soc_valid
    d.soc_now = soc_now

    kwh_needed = 0.0
    soc_gap = (inp.soc_target - soc_now) if soc_valid else 0.0
    # Staat het laden uit, dan pas hervatten na een merkbare terugval: anders
    # start 1% ruis rond de doel-SoC het laden elke cooldown opnieuw.
    min_gap = 0.0 if inp.charge_now_on else SOC_RESTART_DEADBAND
    if soc_valid and soc_gap > 0 and soc_gap >= min_gap:
        if inp.kwh_per_pct is not None:
            # Geleerde kWh per procent (incl. laadverlies) heeft voorrang.
            kwh_needed = soc_gap * inp.kwh_per_pct
        else:
            kwh_needed = soc_gap / 100 * inp.battery_capacity_kwh
    d.kwh_needed = kwh_needed

    # --- Vertrektijd/datum ---
    no_departure = not has_departure(inp.dep_time)
    d.no_departure = no_departure
    dep_date_valid = inp.dep_date not in NO_VALUE_STRINGS

    time_passed_today = False
    if not no_departure:
        dep_today = _today_at(inp.now, inp.dep_time)
        time_passed_today = dep_today is not None and inp.now >= dep_today

    if no_departure:
        next_dep_date = ""
    else:
        next_dep_date = (
            inp.now.date() + timedelta(days=1 if time_passed_today else 0)
        ).strftime("%Y-%m-%d")

    dep_moment, deadline = parse_departure(inp.now, inp.dep_time, inp.dep_date)
    dep_moment_past = (
        dep_moment is not None and dep_date_valid and inp.now >= dep_moment
    )

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

    hours_left = 0.0
    if deadline is not None:
        hours_left = round((deadline - inp.now).total_seconds() / 3600, 3)
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
    if dep_moment is not None and dep_moment.date() > inp.now.date():
        h = dep_moment.hour + dep_moment.minute / 60
        if h >= 16:
            tomorrow_frac = 1.0
        elif h <= 7:
            tomorrow_frac = 0.0
        else:
            tomorrow_frac = round((h - 7) / 9, 2)

    if inp.solar_detail_ok and not no_departure:
        expected_solar_kwh = inp.solar_before_dep_kwh
    else:
        expected_solar_kwh = solar_today_capped_kwh + inp.fc_tomorrow * tomorrow_frac
    # forecast_bias corrigeert de voorspelling zelf (structureel te hoog/laag);
    # zon_benut_factor vertaalt opbrengst naar het deel dat als overschot voor de
    # auto overblijft (rest = huisverbruik). Twee verschillende correcties.
    expected_solar_kwh *= inp.forecast_bias * inp.zon_benut_factor
    d.expected_solar_kwh = expected_solar_kwh
    grid_deficit_kwh = max(0.0, kwh_needed - expected_solar_kwh)

    # --- Grid-vloer / ramp (op ACTUELE SoC) ---
    charger_max_w = delivered_amps(max_a) * 3 * NOMINAL_W_PER_A
    # Planningstekort: reken bewust op iets minder zon dan voorspeld. Is het
    # tekort 0, dan hoeft er niets van het net -> laadpauze tot de zon er is.
    planning_deficit_kwh = max(
        0.0, kwh_needed - expected_solar_kwh * SOLAR_TRUST_FACTOR
    )
    base_floor_w = (
        0.0 if (no_departure or hours_left <= 0)
        else planning_deficit_kwh / hours_left * 1000
    )
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
        else (charger_max_w if (deadline_passed or behind_schedule) else ramp_target_w)
    )
    d.must_charge_w = must_charge_w

    # --- Zonoverschot ---
    # Zonder betrouwbare netmeter weten we het huisverbruik niet; dan is er per
    # definitie geen aantoonbaar overschot (anders laden we op netimport).
    if inp.grid_ok:
        available_solar_w = max(
            0.0, inp.charger_w - inp.grid_w - inp.pv_marge_watt
        )
        available_solar_avg_w = max(
            0.0, inp.charger_avg_w - inp.grid_avg_w - inp.pv_marge_watt
        )
    else:
        available_solar_w = 0.0
        available_solar_avg_w = 0.0
    d.available_solar_w = available_solar_w

    # --- Modus / target ---
    forced_full = (
        inp.override_limit or not inp.slim_laden or inp.other_car
        or inp.laadmodus == "Snel"
    )
    solar_only = not forced_full and (
        inp.laadmodus == "Zon"
        or (inp.laadmodus == "Hybride" and no_departure)
    )
    d.forced_full = forced_full
    d.solar_only = solar_only

    target_w = (
        charger_max_w if forced_full
        else (available_solar_w if solar_only
              else max(must_charge_w, available_solar_w))
    )
    target_avg_w = (
        charger_max_w if forced_full
        else (available_solar_avg_w if solar_only
              else max(must_charge_w, available_solar_avg_w))
    )
    # Laadpauze: met vertrektijd, maar de verwachte zon dekt het restant en er is
    # nu geen overschot -> wachten tot de zon er weer is.
    d.solar_pause = (
        not forced_full and not solar_only and not no_departure
        and must_charge_w <= 0 and available_solar_w <= 0 and kwh_needed > 0
    )

    # --- Preclimate: laden aanhouden + genoeg vermogen (auto zelfbegrenst) ---
    # Geldt in alle niet-geforceerde modi (ook Zon/solar_only): anders trekt de
    # auto de ~3500W klimaatlast uit de eigen accu i.p.v. de lader.
    if inp.preclimate_active and not forced_full:
        target_w = max(target_w, PRECLIMATE_POWER_W)
        target_avg_w = max(target_avg_w, PRECLIMATE_POWER_W)
    d.target_w = target_w

    # --- Fasekeuze ---
    three_phase_min_w = delivered_amps(min_a) * 3 * NOMINAL_W_PER_A
    # Fase-omhoog conservatief op het gemiddelde + buffer: voorkomt opschakelen
    # naar 3 fasen bij korte zon-pieken.
    phase_up_signal_w = (
        target_avg_w if solar_only else max(must_charge_w, available_solar_avg_w)
    )
    # Fase-omlaag responsief: neem de LAAGSTE van instantaan en gemiddeld target,
    # zodat terugvallende zon (bewolking) direct wordt herkend en we niet op
    # 3 fasen blijven hangen terwijl er van het net geimporteerd wordt.
    # In deadline-modus blijft must_charge_w hoog -> geen terugschakeling.
    phase_down_signal_w = min(target_w, target_avg_w)
    if forced_full:
        desired_phase_raw = 3
    elif inp.current_phase == 1 and phase_up_signal_w >= three_phase_min_w + PHASE_UP_BUFFER_W:
        desired_phase_raw = 3
    elif inp.current_phase == 3 and phase_down_signal_w < three_phase_min_w:
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
    meas_amps = delivered_amps(inp.current_amps)
    if charging_active and meas_amps > 0:
        wpa_meas = inp.charge_power_now_w / (meas_amps * inp.current_phase)
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
    avail = target_w
    ideal = setpoint_for(avail, desired_phase, real_w_per_a)
    c = inp.current_amps
    amp_cooldown_ok = inp.seconds_since_amp_change >= AMP_SETTLE_S
    if forced_full:
        amps_raw = max_a
    elif d.phase_change_needed:
        amps_raw = min_a
    elif inp.grid_w > EMERGENCY_IMPORT_W and ideal < c:
        amps_raw = ideal
    elif (amp_cooldown_ok and ideal >= c + 1
            and avail >= power_at(c + 1, desired_phase, real_w_per_a) * 0.97):
        amps_raw = c + 1
    elif (amp_cooldown_ok and ideal <= c - 1
            and avail <= power_at(c - 1, desired_phase, real_w_per_a) * 1.03):
        amps_raw = c - 1
    else:
        amps_raw = c
    amps_clamped = int(clamp(amps_raw, min_a, max_a))
    d.amps_set = amps_clamped
    d.amps_change_needed = amps_clamped != inp.current_amps

    # --- Laden aan/uit ---
    min_charge_w = delivered_amps(min_a) * desired_phase * NOMINAL_W_PER_A
    charge_switch_min_s = CHARGE_SWITCH_MIN_MINUTEN * 60
    charge_switch_cooldown_ok = inp.seconds_since_charge_switch >= charge_switch_min_s
    d.charge_switch_cooldown_ok = charge_switch_cooldown_ok
    solar_start_w = min_charge_w * 1.10
    solar_stop_w = min_charge_w * 0.70
    solar_threshold_w = solar_stop_w if inp.charge_now_on else solar_start_w
    want_charge_raw = (
        forced_full
        or available_solar_w >= solar_threshold_w
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

    # Auto aangesloten. Wanneer de lader ACTIEF laadt is de auto aantoonbaar
    # aanwezig -> dan regelen we ook zonder geldige SoC (anders zou een SoC-uitval
    # het stoppen/regelen blokkeren en blijven we importeren). Bij 'suspended'
    # blijven we conservatief en eisen we wel een geldige SoC.
    connected = inp.peb_status in ("charging", "suspended")
    if inp.other_car:
        # Van een andere auto valt niets te meten; wel gewoon vol laden.
        car_here = connected
        my_car_here = False
    else:
        car_here = (
            inp.peb_status == "charging"
            or (connected and soc_valid)
            or (inp.preclimate_active and connected)
        )
        my_car_here = car_here
    d.car_here = car_here
    d.my_car_here = my_car_here

    # Bepaal de gewenste laadschakelaar-stand (None = niet wijzigen).
    if car_here:
        if not want_charge:
            if inp.charge_now_on and charge_switch_cooldown_ok:
                d.set_charge_on = False
        else:
            if not inp.charge_now_on and charge_switch_cooldown_ok:
                d.set_charge_on = True

    return d
