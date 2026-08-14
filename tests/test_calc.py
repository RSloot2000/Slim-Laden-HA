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
check("Snel: target vol", d.target_w == 16 * 3 * 230)
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
check("Hybride deadline: must_charge vol vermogen", d.must_charge_w == 16 * 3 * 230)

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

# 6) W/A-meting geldig zonder preclimate (binnen 200-240, settled).
d = compute(
    ChargeInputs(
        now=NOW, peb_status="charging", charge_power_now_w=16 * 1 * 225,
        current_amps=16, current_phase=1, seconds_since_amp_change=60,
        wpa_stored=230,
    )
)
check("W/A geldig zonder preclimate", d.wpa_meas_valid is True)

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

# 11) Forecast-bias schaalt de verwachte zon.
d = compute(
    ChargeInputs(
        now=NOW, laadmodus="Hybride", soc_raw=50, soc_target=100,
        dep_time="18:00:00", dep_date=NOW.date().strftime("%Y-%m-%d"),
        solar_detail_ok=True, solar_before_dep_kwh=10, zon_benut_factor=1.0,
        forecast_bias=0.5, grid_ok=True,
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
d = compute(ChargeInputs(solar_before_dep_kwh=40, **_hybride))
check("Hybride/veel zon: geen netvloer", d.base_floor_w == 0)
check("Hybride/veel zon: must_charge 0", d.must_charge_w == 0)
check("Hybride/veel zon: laadpauze", d.solar_pause is True)
check("Hybride/veel zon: niet laden", d.want_charge is False)

# 16) Zelfde situatie met te weinig zon: 's nachts doorladen op minimaal niveau.
d = compute(ChargeInputs(solar_before_dep_kwh=5, **_hybride))
check("Hybride/weinig zon: netvloer > 0", d.base_floor_w > 0)
check("Hybride/weinig zon: laden", d.want_charge is True)
check("Hybride/weinig zon: 1 fase", d.desired_phase == 1)
check("Hybride/weinig zon: minimale ampère", d.amps_set == 6)
check("Hybride/weinig zon: geen laadpauze", d.solar_pause is False)

# 17) Overdag met overschot volgt Hybride gewoon de zon.
d = compute(
    ChargeInputs(
        solar_before_dep_kwh=40, charger_w=0, grid_w=-5000,
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

# 23) W/A-leren onderdrukt bij hoge SoC (auto begrenst dan zelf).
d = compute(
    ChargeInputs(
        now=NOW, peb_status="charging", charge_power_now_w=16 * 1 * 225,
        current_amps=16, current_phase=1, seconds_since_amp_change=60,
        soc_raw=95,
    )
)
check("Hoge SoC: W/A-meting ongeldig", d.wpa_meas_valid is False)

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
