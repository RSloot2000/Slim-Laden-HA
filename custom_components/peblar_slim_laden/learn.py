"""Leerlogica voor Peblar Slim Laden (accu-capaciteit + W/A).

De W/A-EMA zit in `calc.compute` (per cyclus). Deze module bevat de
accu-capaciteit-leerstap die de bestaande automation "Peblar accu-capaciteit
leren (sessie-zuiver)" vervangt: bij de overgang charging -> suspended wordt uit
soc_delta en de sessie-energie een nieuwe capaciteit afgeleid en met een EMA
(0.7 oud + 0.3 nieuw) bijgewerkt. Preclimate-sessies worden uitgesloten omdat
daar energie in gaat zonder echte SoC-winst.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CapacityResult:
    """Resultaat van een capaciteit-leerpoging."""

    updated: bool = False
    new_capacity: float = 0.0        # ruwe meting
    updated_capacity: float = 0.0    # gewogen (EMA) resultaat
    soc_delta: float = 0.0
    energy_session: float = 0.0


def learn_capacity(
    *,
    soc_start: float | None,
    soc_end: float | None,
    energy_start: float | None,
    energy_end: float | None,
    old_capacity: float,
    other_car: bool,
    preclimate_active: bool,
) -> CapacityResult:
    """Leid een nieuwe accu-capaciteit af (guardrails uit de originele automation).

    Guardrails:
    - geldige SoC nodig; geen andere auto; geen preclimate-sessie
    - soc_delta >= 10 %
    - energy_session > 1 kWh en <= soc_delta * 0.9 (plausibiliteit)
    - EMA alleen als 10 < meting < 40 kWh
    """
    res = CapacityResult()
    soc_valid = (
        soc_start is not None and soc_end is not None
        and 0 <= soc_start <= 100 and 0 <= soc_end <= 100
    )
    if not soc_valid or other_car or preclimate_active:
        return res
    if energy_start is None or energy_end is None:
        return res

    soc_delta = soc_end - soc_start
    energy_session = energy_end - energy_start
    res.soc_delta = soc_delta
    res.energy_session = energy_session

    if soc_delta < 10 or energy_session <= 1 or energy_session > (soc_delta * 0.9):
        return res

    new_capacity = energy_session / (soc_delta / 100)
    res.new_capacity = new_capacity

    if 10 < new_capacity < 40:
        res.updated_capacity = old_capacity * 0.7 + new_capacity * 0.3
        res.updated = True
    else:
        res.updated_capacity = old_capacity
    return res
