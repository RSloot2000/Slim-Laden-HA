"""Smoke-/pariteitstest voor calc.compute zonder Home Assistant.

Laadt const.py + calc.py als synthetisch pakket (zodat de relatieve import
`from .const import ...` werkt) en controleert een paar kernscenario's.

Draai:  python tests/test_calc.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta

BASE = pathlib.Path(__file__).resolve().parent.parent / (
    "custom_components/peblar_slim_laden"
)


def _load_pkg():
    pkg = types.ModuleType("psl")
    pkg.__path__ = [str(BASE)]
    sys.modules["psl"] = pkg

    def load(name: str):
        spec = importlib.util.spec_from_file_location(f"psl.{name}", BASE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"psl.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    load("const")
    return load("calc")


calc = _load_pkg()
ChargeInputs = calc.ChargeInputs
compute = calc.compute

NOW = datetime(2026, 7, 16, 12, 0, 0)
FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# 1) Geen vertrektijd + Zon-modus: solar_only, geen must_charge.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Zon", soc_raw=50, soc_target=100,
        battery_capacity_kwh=50, grid_ok=True, charger_w=0, grid_w=-1000,
        pv_now_w=1500, dep_time="00:00:00",
    )
)
check("Zon: no_departure", d.no_departure)
check("Zon: solar_only", d.solar_only)
check("Zon: must_charge==0", d.must_charge_w == 0)
check("Zon: available_solar>0", d.available_solar_w > 0)

# 2) Snel-modus: forced_full, target = max A * 3 fase * 230.
d = compute(ChargeInputs(now=NOW, laadmodus="Snel", soc_raw=50, max_a=16))
check("Snel: forced_full", d.forced_full)
check("Snel: target vol", d.target_w == 15 * 3 * 230)
check("Snel: desired_phase 3", d.desired_phase == 3)

# 3) Hybride met deadline gepasseerd -> behind_schedule + noodstop.
past = NOW - timedelta(hours=1)
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=40, soc_target=100,
        battery_capacity_kwh=50, dep_time=past.strftime("%H:%M:%S"),
        dep_date=NOW.date().strftime("%Y-%m-%d"), grid_ok=True,
    )
)
check("Hybride deadline: behind_schedule", d.behind_schedule)
check("Hybride deadline: must_charge vol vermogen", d.must_charge_w == 15 * 3 * 230)

# 4) Preclimate: laden aanhouden ook al is de auto vol (soc==target).
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=100, soc_target=100,
        preclimate_active=True, peb_status="suspended", grid_ok=True,
        charge_now_on=False,
    )
)
check("Preclimate: want_charge", d.want_charge)
check("Preclimate: my_car_here", d.my_car_here)
check("Preclimate: target >= 3500", d.target_w >= 3500)

# 5) Preclimate onderdrukt W/A-leren.
d = compute(
    ChargeInputs(
        now=NOW, peb_status="charging", charge_power_now_w=3500,
        current_amps=15, current_phase=1, preclimate_active=True,
        seconds_since_amp_change=60,
    )
)
check("Preclimate: wpa_meas_valid False", d.wpa_meas_valid is False)

# 6) W/A-meting geldig zonder preclimate: setpoint 16 A levert 15 A.
d = compute(
    ChargeInputs(
        now=NOW, peb_status="charging", charge_power_now_w=15 * 1 * 230,
        current_amps=16, current_phase=1, seconds_since_amp_change=60,
        wpa_stored=230,
    )
)
check("W/A geldig zonder preclimate", d.wpa_meas_valid is True)
check("W/A gecorrigeerd voor ampère-offset", abs(d.wpa_meas - 230) < 0.1)

# 7) Ampère-deadband: geen wijziging zonder cooldown.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=50, soc_target=100,
        dep_time="18:00:00", dep_date=NOW.date().strftime("%Y-%m-%d"),
        grid_ok=True, current_amps=10, seconds_since_amp_change=5,
        wpa_stored=230,
    )
)
check("Deadband: amps blijft 10 zonder cooldown", d.amps_set == 10)

# 8) SoC-uitval tijdens actief laden: auto blijft "aanwezig" (kan stoppen/regelen).
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=None, peb_status="charging",
        grid_ok=True,
    )
)
check("SoC-uitval + charging: my_car_here", d.my_car_here is True)
check("SoC-uitval: kwh_needed 0", d.kwh_needed == 0)

# 9) SoC-uitval terwijl gepauzeerd: conservatief -> niet als aanwezig zien.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=None, peb_status="suspended",
        grid_ok=True,
    )
)
check("SoC-uitval + suspended: my_car_here False", d.my_car_here is False)

# 10) Geleerde kWh/% heeft voorrang op statische capaciteit.
d = compute(
    ChargeInputs(
        now=NOW, soc_raw=50, soc_target=100, kwh_per_pct=0.55,
        battery_capacity_kwh=50,
    )
)
check("kwh_per_pct toegepast", abs(d.kwh_needed - 27.5) < 0.01)

# 11) Forecast-bias schaalt de verwachte zon in de terugvalroute (zonder
#     half-uur-detail; met detail rekent de coordinator de bias al mee).
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=50, soc_target=100,
        dep_time="18:00:00", dep_date=NOW.date().strftime("%Y-%m-%d"),
        solar_detail_ok=False, fc_today_remaining=10, pv_now_w=4000,
        zon_benut_factor=1.0, forecast_bias=0.5, grid_ok=True,
    )
)
check("forecast_bias toegepast", abs(d.expected_solar_kwh - 5.0) < 0.01)

# 12) Per-fase geleerde W/A voedt real_w_per_a.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Zon", soc_raw=50, current_phase=1,
        wpa_1p=210, wpa_3p=225, grid_ok=True,
    )
)
check("per-fase W/A 1-fase toegepast", d.real_w_per_a == 210)
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Snel", soc_raw=50, current_phase=3,
        wpa_1p=210, wpa_3p=225,
    )
)
check("per-fase W/A 3-fase toegepast", d.real_w_per_a == 225)

# 13) Ramp-bias laat de ramp niet later, maar eerder/gelijk starten.
_base = dict(
    now=NOW, laadmodus="Hybride", soc_raw=20, soc_target=100,
    dep_time=(NOW + timedelta(hours=3)).strftime("%H:%M:%S"),
    dep_date=NOW.date().strftime("%Y-%m-%d"), battery_capacity_kwh=50,
    max_a=16, grid_ok=True,
)
d0 = compute(ChargeInputs(ramp_bias=0.0, **_base))
d1 = compute(ChargeInputs(ramp_bias=0.15, **_base))
check("ramp_bias verhoogt (of gelijk) ramp_factor", d1.ramp_factor >= d0.ramp_factor)

# 14) Zon + bewolking op 3 fasen met net-import -> direct terug naar 1 fase.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Zon", soc_raw=50, current_phase=3, grid_ok=True,
        charger_w=4140, charger_avg_w=4140, grid_w=700, grid_avg_w=700,
    )
)
check("Bewolking: terug naar 1 fase", d.desired_phase == 1 and d.phase_change_needed)

# 15) Hybride met vertrektijd morgen: de voorspelde zon dekt de behoefte ruim ->
#     laadpauze, geen netvloer.
TOMORROW = (NOW + timedelta(days=1)).date().strftime("%Y-%m-%d")
_hybride = dict(
    now=NOW, laadmodus="Hybride", soc_raw=50, soc_target=100,
    battery_capacity_kwh=50, dep_time="14:00:00", dep_date=TOMORROW,
    solar_detail_ok=True, zon_benut_factor=1.0, grid_ok=True,
)
d = compute(ChargeInputs(solar_surplus_before_dep_kwh=40, **_hybride))
check("Hybride/veel zon: geen netvloer", d.base_floor_w == 0)
check("Hybride/veel zon: must_charge 0", d.must_charge_w == 0)
check("Hybride/veel zon: laadpauze", d.solar_pause is True)
check("Hybride/veel zon: niet laden", d.want_charge is False)

# 16) Zelfde situatie met te weinig zon: 's nachts doorladen op minimaal niveau.
d = compute(ChargeInputs(solar_surplus_before_dep_kwh=5, **_hybride))
check("Hybride/weinig zon: netvloer > 0", d.base_floor_w > 0)
check("Hybride/weinig zon: laden", d.want_charge is True)
check("Hybride/weinig zon: 1 fase", d.desired_phase == 1)
check("Hybride/weinig zon: minimale ampère", d.amps_set == 6)
check("Hybride/weinig zon: geen laadpauze", d.solar_pause is False)

# 17) Overdag met overschot volgt Hybride gewoon de zon.
d = compute(
    ChargeInputs(
        solar_surplus_before_dep_kwh=40, charger_w=0, grid_w=-5000,
        charger_avg_w=0, grid_avg_w=-5000, **_hybride
    )
)
check("Hybride/overschot: laden", d.want_charge is True)
check("Hybride/overschot: target volgt zon", abs(d.target_w - 4950) < 1)

# 18) Hybride zonder vertrektijd gedraagt zich als Zon.
d = compute(
    ChargeInputs(now=NOW, laadmodus="Hybride", soc_raw=50, grid_ok=True)
)
check("Hybride zonder vertrek: solar_only", d.solar_only is True)

# 19) Zon zonder overschot: niet laden.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Zon", soc_raw=50, soc_target=100, grid_ok=True,
        charger_w=0, grid_w=200,
    )
)
check("Zon zonder overschot: available 0", d.available_solar_w == 0)
check("Zon zonder overschot: niet laden", d.want_charge is False)

# 20) Netmeter uitgevallen: geen aantoonbaar overschot (nooit op netimport laden).
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Zon", soc_raw=50, grid_ok=False, pv_now_w=3000,
    )
)
check("Geen netmeter: available 0", d.available_solar_w == 0)
check("Geen netmeter: niet laden", d.want_charge is False)

# 21) Andere auto aan de lader: alle slimme logica uit, vol vermogen.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Zon", other_car=True, peb_status="suspended",
        soc_raw=None, max_a=16,
    )
)
check("Andere auto: forced_full", d.forced_full is True)
check("Andere auto: car_here", d.car_here is True)
check("Andere auto: niet als eigen auto geteld", d.my_car_here is False)
check("Andere auto: 3 fasen", d.desired_phase == 3)
check("Andere auto: max ampère", d.amps_set == 16)

# 22) Onzinnige grenzen (min > max) leveren nog steeds een geldige ampèrewaarde.
d = compute(ChargeInputs(now=NOW, laadmodus="Snel", soc_raw=50, min_a=16, max_a=6))
check("min>max: ampère binnen 6..16", 6 <= d.amps_set <= 16)

# 23) Laagste werkpunt (setpoint 6 A -> 1188 W gemeten) is leerbaar; zonder de
#     ampère-offset gaf dat 198 W/A en viel de meting buiten het geldige bereik.
d = compute(
    ChargeInputs(
        now=NOW, peb_status="charging", charge_power_now_w=1188,
        current_amps=6, current_phase=1, seconds_since_amp_change=60,
        soc_raw=95,
    )
)
check("Laag werkpunt: W/A ~238", abs(d.wpa_meas - 237.6) < 0.5)
check("Laag werkpunt: meting geldig", d.wpa_meas_valid is True)

# 24) Vlak profiel: bij een correcte kwh_needed blijft de netvloer constant
#     terwijl de nacht vordert (geen aflopend profiel).
def _floor(uren_rest, kwh_rest):
    dep = NOW + timedelta(hours=uren_rest + 0.25)
    return compute(
        ChargeInputs(
            now=NOW, laadmodus="Hybride", soc_raw=100 - kwh_rest / 0.215,
            soc_target=100, kwh_per_pct=0.215, dep_time=dep.strftime("%H:%M:%S"),
            dep_date=dep.date().strftime("%Y-%m-%d"), grid_ok=True,
            solar_detail_ok=True, solar_surplus_before_dep_kwh=0.0,
        )
    ).base_floor_w


f_start, f_half = _floor(10.0, 13.0), _floor(5.0, 6.5)
# Tolerantie dekt de afronding van soc_now op 0,1 %.
check("Constante netvloer over de nacht", abs(f_start - f_half) < f_start * 0.01)

# 25) Doel-SoC gehaald: niet opnieuw starten op 1% terugval.
_klaar = dict(
    now=NOW, laadmodus="Hybride", soc_target=100, battery_capacity_kwh=50,
    dep_time="09:30:00", dep_date=NOW.date().strftime("%Y-%m-%d"), grid_ok=True,
)
d = compute(ChargeInputs(soc_raw=99, charge_now_on=False, **_klaar))
check("Doel gehaald: 1% terugval start niet", d.kwh_needed == 0)
d = compute(ChargeInputs(soc_raw=99, charge_now_on=True, **_klaar))
check("Tijdens laden telt elk procent wel", d.kwh_needed > 0)
d = compute(ChargeInputs(soc_raw=95, charge_now_on=False, **_klaar))
check("Grotere terugval start wel weer", d.kwh_needed > 0)

# 26) Schone start: alleen resetten bij loskoppelen, niet bij een laadstop.
_plug = dict(now=NOW, laadmodus="Hybride", soc_raw=99, soc_target=100, grid_ok=True)
d = compute(ChargeInputs(peb_status="suspended", plug_state="plugged",
                         prev_plug_state="plugged", **_plug))
check("Laadstop met kabel erin: geen reset", d.just_disconnected is False)
d = compute(ChargeInputs(peb_status="idle", plug_state="unplugged",
                         prev_plug_state="plugged", **_plug))
check("Losgekoppeld: reset", d.just_disconnected is True)
d = compute(ChargeInputs(peb_status="idle", plug_state="unplugged",
                         prev_plug_state="unplugged", **_plug))
check("Blijft losgekoppeld: eenmalig", d.just_disconnected is False)
d = compute(ChargeInputs(peb_status="unknown", plug_state="unknown",
                         prev_plug_state="plugged", **_plug))
check("Status onbekend: geen reset", d.just_disconnected is False)

# 27) Zonoverschot is al netto: de benutfactor mag er niet nog eens overheen.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=50, soc_target=100,
        battery_capacity_kwh=25, dep_time="18:00:00",
        dep_date=NOW.date().strftime("%Y-%m-%d"), grid_ok=True,
        solar_detail_ok=True, solar_surplus_before_dep_kwh=8.0,
        zon_benut_factor=0.6, forecast_bias=0.87,
    )
)
check("Netto overschot ongewijzigd overgenomen", abs(d.expected_solar_kwh - 8.0) < 0.01)

# 28) Zon-slots: huisverbruik eraf, deel-slots naar rato, P10 apart.
ForecastSlot = calc.ForecastSlot
surplus = calc.solar_surplus_before

T0 = NOW.replace(hour=10, minute=0)
slots = [ForecastSlot(start=T0 + timedelta(minutes=30 * i), kwh=1.0, kwh_p10=0.6)
         for i in range(4)]
r = surplus(slots, T0, T0 + timedelta(hours=2), 1.0, lambda t: None)
check("Slots zonder huisverbruik", abs(r.kwh - 4.0) < 0.001)
check("P10 apart geteld", abs(r.kwh_p10 - 2.4) < 0.001)
check("P10 beschikbaar", r.p10_ok is True)
check("Venster gedekt", r.covers_window is True)

r = surplus(slots, T0, T0 + timedelta(hours=2), 1.0, lambda t: 0.4)
check("Huisverbruik eraf", abs(r.kwh - (4 - 4 * 0.2)) < 0.001)

r = surplus(slots, T0 + timedelta(minutes=15), T0 + timedelta(minutes=45), 1.0,
            lambda t: None)
check("Deel-slots naar rato", abs(r.kwh - 1.0) < 0.001)

r = surplus(slots, T0, T0 + timedelta(hours=4), 1.0, lambda t: None)
check("Onvolledig venster gemeld", r.covers_window is False)

r = surplus([ForecastSlot(start=T0, kwh=0.2)], T0, T0 + timedelta(minutes=30), 1.0,
            lambda t: 1.0)
check("Overschot nooit negatief", r.kwh == 0.0)
check("Zonder P10 valt hij terug op P50", r.p10_ok is False)

# 29) Hoofdzekering: laadstroom direct terug, ongeacht cooldown.
_fuse = dict(
    now=NOW, laadmodus="Snel", soc_raw=50, soc_target=100, grid_ok=True,
    current_amps=16, max_net_a=25, seconds_since_amp_change=0,
    peb_status="charging", charge_now_on=True, plug_state="plugged",
    prev_plug_state="plugged",
)
d = compute(ChargeInputs(grid_max_phase_a=20.0, **_fuse))
check("Ruimte over: geen ingreep", d.mains_overload is False and d.amps_set == 16)
d = compute(ChargeInputs(grid_max_phase_a=27.0, **_fuse))
check("Overbelasting: amperage omlaag", d.mains_overload is True and d.amps_set == 13)
check("Headroom negatief gemeld", d.mains_headroom_a == -3.0)
d = compute(ChargeInputs(grid_max_phase_a=40.0, **_fuse))
check("Zware overbelasting: laden uit", d.set_charge_on is False)
d = compute(ChargeInputs(grid_max_phase_a=None, **_fuse))
check("Zonder fasedata: geen bewaking", d.mains_overload is False)

# 30) ETA op het huidige laadvermogen.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Snel", soc_raw=50, soc_target=100, kwh_per_pct=0.25,
        peb_status="charging", charge_now_on=True, grid_ok=True,
    )
)
uren = (d.eta_full - NOW).total_seconds() / 3600
check("ETA berekend", abs(uren - d.kwh_needed / (d.target_w / 1000)) < 0.01)
d = compute(ChargeInputs(now=NOW, laadmodus="Zon", soc_raw=50, grid_ok=True))
check("Geen laden: geen ETA", d.eta_full is None)

# 31) Temperatuurmodel voor kWh per procent SoC.
kpp = calc.kwh_per_pct_at
# Zomerfit: 0.245 bij 20 C, 0.305 bij 0 C  ->  helling -0.003
FIT = dict(slope=-0.003, intercept=0.305, t_min=-2.0, t_max=22.0)
v, used = kpp(base=0.26, temp=20.0, **FIT)
check("Model actief bij genoeg spreiding", used is True)
check("Warme nacht: lage waarde", abs(v - 0.245) < 0.001)
v, _ = kpp(base=0.26, temp=0.0, **FIT)
check("Koude nacht: hogere waarde", abs(v - 0.305) < 0.001)

v, used = kpp(base=0.26, temp=20.0, slope=-0.003, intercept=0.305,
              t_min=15.0, t_max=20.0)
check("Te weinig spreiding: gemiddelde", used is False and v == 0.26)

v, used = kpp(base=0.26, temp=5.0, slope=0.004, intercept=0.2,
              t_min=-5.0, t_max=25.0)
check("Onzinnige helling: gemiddelde", used is False and v == 0.26)

v, used = kpp(base=0.26, temp=-40.0, **FIT)
check("Extrapolatie begrensd", used is True and abs(v - (0.305 + -0.003 * -7.0)) < 1e-9)

v, used = kpp(base=0.26, temp=None, **FIT)
check("Geen temperatuur: gemiddelde", used is False and v == 0.26)

v, used = kpp(base=None, slope=None, intercept=None, t_min=None, t_max=None,
              temp=10.0)
check("Nog niets geleerd", used is False and v is None)

# 15) Deadline-modus blijft op 3 fasen ondanks net-import.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=20, soc_target=100,
        dep_time=(NOW + timedelta(hours=1)).strftime("%H:%M:%S"),
        dep_date=NOW.date().strftime("%Y-%m-%d"),
        current_phase=3, grid_ok=True, grid_w=700,
    )
)
check("Deadline: blijft op 3 fasen", d.desired_phase == 3)

print()
if FAILS:
    print(f"{len(FAILS)} test(s) gefaald:", ", ".join(FAILS))
    sys.exit(1)
print("Alle scenario's OK")
