"""TimescaleDB-datapijplijn voor Peblar Slim Laden.

Bevat synchrone helpers die vanuit een executor-thread aangeroepen worden
(via `hass.async_add_executor_job`) zodat de HA event-loop niet blokkeert.
Alles is defensief: bij een onbereikbare DB blijft de regellus gewoon draaien.

Het schema (tabellen met `peb_`-prefix) bestaat al in de database `homeassistant`.
Deze module maakt geen tabellen aan; hij schrijft/leest alleen.
De Node-RED-tabellen (`laadsessie`, `tankbeurt`) worden nooit aangeraakt.

De verbinding wordt hergebruikt over aanroepen heen en achter een lock
geserialiseerd; bij een fout wordt hij weggegooid zodat de volgende aanroep
opnieuw verbindt.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2

from .const import CYCLE_COLS, WPA_LEARN_MAX_SOC, WPA_MAX, WPA_MIN

_CONNECT_TIMEOUT = 8
_APP_NAME = "peblar_slim_laden"

_lock = threading.Lock()
_conn = None
_conn_url: str | None = None


@contextmanager
def _cursor(url: str) -> Iterator:
    """Geef een cursor op een hergebruikte verbinding; commit/rollback via `with`."""
    global _conn, _conn_url
    with _lock:
        conn = _conn
        if conn is None or conn.closed or _conn_url != url:
            if conn is not None and not conn.closed:
                conn.close()
            conn = psycopg2.connect(
                url, connect_timeout=_CONNECT_TIMEOUT, application_name=_APP_NAME
            )
            _conn, _conn_url = conn, url
        try:
            with conn, conn.cursor() as cur:
                yield cur
        except Exception:
            _conn, _conn_url = None, None
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - sluiten mag de fout niet maskeren
                pass
            raise


def close_connection() -> None:
    """Sluit de hergebruikte verbinding (bij unload van de integratie)."""
    global _conn, _conn_url
    with _lock:
        if _conn is not None and not _conn.closed:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
        _conn, _conn_url = None, None


def validate_url(url: str) -> None:
    """Verbind en controleer of het schema aanwezig is (voor de config flow)."""
    conn = psycopg2.connect(
        url, connect_timeout=_CONNECT_TIMEOUT, application_name=_APP_NAME
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM peb_charge_cycle LIMIT 1")
    finally:
        conn.close()


def insert_cycle(url: str, row: dict) -> None:
    """Schrijf één regelcyclus als rij naar peb_charge_cycle."""
    cols = ",".join(CYCLE_COLS)
    ph = ",".join(["%s"] * len(CYCLE_COLS))
    vals = [row.get(c) for c in CYCLE_COLS]
    with _cursor(url) as cur:
        cur.execute(
            f"INSERT INTO peb_charge_cycle (ts,{cols}) VALUES (now(),{ph})",
            vals,
        )


# Alleen cycli sinds de laatst vastgelegde sessie bekijken; dat scheelt een
# volledige scan van 14 dagen bij elke ronde.
_SESSION_SQL = """
WITH bound AS (
    SELECT COALESCE(MAX(end_ts), now() - interval '14 days') AS since
    FROM peb_charge_session
),
c AS (
    SELECT ts, soc_now, soc_target, session_energy_kwh, current_phase,
           wpa_meas, wpa_meas_valid
    FROM peb_charge_cycle, bound
    WHERE charger_w > 200
      AND ts > bound.since
),
flagged AS (
    SELECT *,
        CASE WHEN ts - LAG(ts) OVER w > interval '15 min'
                  OR LAG(ts) OVER w IS NULL
             THEN 1 ELSE 0 END AS new_grp,
        CASE WHEN current_phase IS DISTINCT FROM LAG(current_phase) OVER w
                  AND LAG(current_phase) OVER w IS NOT NULL
                  AND ts - LAG(ts) OVER w <= interval '15 min'
             THEN 1 ELSE 0 END AS phase_chg,
        CASE WHEN ts - LAG(ts) OVER w BETWEEN interval '3 min' AND interval '15 min'
             THEN 1 ELSE 0 END AS stop_flag
    FROM c
    WINDOW w AS (ORDER BY ts)
),
grouped AS (
    SELECT *, SUM(new_grp) OVER (ORDER BY ts) AS grp FROM flagged
),
sessions AS (
    SELECT
        MIN(ts) AS start_ts,
        MAX(ts) AS end_ts,
        (array_agg(soc_now ORDER BY ts))[1] AS soc_start,
        (array_agg(soc_now ORDER BY ts DESC))[1] AS soc_end,
        (array_agg(soc_target ORDER BY ts DESC))[1] AS soc_target_end,
        MAX(session_energy_kwh) AS energy_kwh,
        AVG(wpa_meas) FILTER (WHERE wpa_meas_valid) AS avg_wpa,
        SUM(phase_chg) AS phase_changes,
        SUM(stop_flag) AS stops
    FROM grouped
    GROUP BY grp
)
INSERT INTO peb_charge_session
    (start_ts, end_ts, soc_start, soc_end, energy_kwh, avg_wpa,
     phase_changes, stops, hit_target)
SELECT start_ts, end_ts, soc_start, soc_end, energy_kwh, avg_wpa,
       phase_changes, stops,
       (soc_end >= soc_target_end) AS hit_target
FROM sessions s
WHERE s.end_ts < now() - interval '10 min'
  AND s.start_ts < s.end_ts
ON CONFLICT (start_ts) DO NOTHING;
"""


def process_sessions(url: str) -> int:
    """Detecteer voltooide laadsessies en schrijf ze naar peb_charge_session."""
    with _cursor(url) as cur:
        cur.execute(_SESSION_SQL)
        return cur.rowcount


def forecast_upsert(
    url: str, day: str, forecast_kwh: float | None, actual_kwh: float | None
) -> None:
    """Upsert forecast/actual voor een dag; bereken ratio zodra beide bekend zijn.

    De voorspelling van een dag wordt maar één keer vastgelegd (eerste schrijving
    wint), de werkelijke opbrengst mag wél overschreven worden.
    """
    with _cursor(url) as cur:
        cur.execute(
            "INSERT INTO peb_forecast_accuracy "
            "(day, forecast_kwh, actual_kwh, ratio) "
            "VALUES (%s,%s,%s,NULL) "
            "ON CONFLICT (day) DO UPDATE SET "
            "  forecast_kwh = COALESCE(peb_forecast_accuracy.forecast_kwh, "
            "                          EXCLUDED.forecast_kwh), "
            "  actual_kwh   = COALESCE(EXCLUDED.actual_kwh, "
            "                          peb_forecast_accuracy.actual_kwh) ",
            (day, forecast_kwh, actual_kwh),
        )
        cur.execute(
            "UPDATE peb_forecast_accuracy "
            "SET ratio = actual_kwh / NULLIF(forecast_kwh,0) "
            "WHERE day = %s AND forecast_kwh IS NOT NULL "
            "AND actual_kwh IS NOT NULL",
            (day,),
        )


def read_learned(url: str) -> dict:
    """Lees geleerde regelsignalen uit de DB (Fase C-E).

    Retourneert ruwe (ongeklemde) waarden; None waar te weinig data is.
    De aanroeper klemt en valt terug op veilige defaults.
    """
    out: dict = {
        "forecast_bias": None,
        "kwh_per_pct": None,
        "wpa_1p": None,
        "wpa_3p": None,
        "hit_rate": None,
    }
    with _cursor(url) as cur:
        # Forecast-bias: gemiddelde actual/forecast-ratio (laatste 30 dagen).
        cur.execute(
            "SELECT AVG(ratio) FROM peb_forecast_accuracy "
            "WHERE ratio IS NOT NULL AND ratio BETWEEN 0.2 AND 3.0 "
            "AND day > (now()::date - 30) "
            "HAVING count(*) >= 3"
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            out["forecast_bias"] = float(row[0])

        # Geleerde kWh per 1% SoC uit voltooide sessies (incl. laadverlies).
        cur.execute(
            "SELECT AVG(energy_kwh / NULLIF(soc_end - soc_start, 0)) "
            "FROM peb_charge_session "
            "WHERE (soc_end - soc_start) >= 15 AND energy_kwh > 1 "
            "AND start_ts > now() - interval '60 days' "
            "HAVING count(*) >= 4"
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            out["kwh_per_pct"] = float(row[0])

        # Per-fase W/A. De meting hoort bij de fase waarop op dat moment geladen
        # werd (current_phase), niet bij de gewenste fase; en niet bij een hoge
        # SoC, want dan begrenst de auto zelf.
        cur.execute(
            "SELECT current_phase, AVG(wpa_meas) FROM peb_charge_cycle "
            "WHERE wpa_meas_valid AND wpa_meas BETWEEN %s AND %s "
            "AND current_phase IN (1, 3) "
            "AND (soc_now IS NULL OR soc_now < %s) "
            "AND ts > now() - interval '30 days' "
            "GROUP BY current_phase HAVING count(*) >= 20",
            (WPA_MIN, WPA_MAX, WPA_LEARN_MAX_SOC),
        )
        for phase, avg in cur.fetchall():
            if avg is None:
                continue
            if int(phase) == 1:
                out["wpa_1p"] = float(avg)
            elif int(phase) == 3:
                out["wpa_3p"] = float(avg)

        # Hit-rate: aandeel sessies dat de doel-SoC haalde (laatste 30 dagen).
        cur.execute(
            "SELECT AVG(CASE WHEN hit_target THEN 1.0 ELSE 0.0 END) "
            "FROM peb_charge_session "
            "WHERE (soc_end - soc_start) >= 15 "
            "AND start_ts > now() - interval '30 days' "
            "HAVING count(*) >= 5"
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            out["hit_rate"] = float(row[0])
    return out

