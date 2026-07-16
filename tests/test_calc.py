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
check("Hybride deadline: must_charge noodstop", d.must_charge_w == 999999)

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

print()
if FAILS:
    print(f"{len(FAILS)} test(s) gefaald:", ", ".join(FAILS))
    sys.exit(1)
print("Alle scenario's OK")
