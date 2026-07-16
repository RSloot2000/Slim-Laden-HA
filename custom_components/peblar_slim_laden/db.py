"""TimescaleDB-datapijplijn voor Peblar Slim Laden.

Bevat synchrone helpers die vanuit een executor-thread aangeroepen worden
(via `hass.async_add_executor_job`) zodat de HA event-loop niet blokkeert.
Alles is defensief: bij een onbereikbare DB blijft de regellus gewoon draaien.

Het schema (tabellen met `peb_`-prefix) bestaat al in de database `homeassistant`.
Deze module maakt geen tabellen aan; hij schrijft/leest alleen.
De Node-RED-tabellen (`laadsessie`, `tankbeurt`) worden nooit aangeraakt.
"""

from __future__ import annotations

import logging

import psycopg2

from .const import CYCLE_COLS

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 8


def insert_cycle(url: str, row: dict) -> None:
    """Schrijf één regelcyclus als rij naar peb_charge_cycle."""
    conn = psycopg2.connect(url, connect_timeout=_CONNECT_TIMEOUT)
    try:
        with conn, conn.cursor() as cur:
            cols = ",".join(CYCLE_COLS)
            ph = ",".join(["%s"] * len(CYCLE_COLS))
            vals = [row.get(c) for c in CYCLE_COLS]
            cur.execute(
                f"INSERT INTO peb_charge_cycle (ts,{cols}) VALUES (now(),{ph})",
                vals,
            )
    finally:
        conn.close()


_SESSION_SQL = """
WITH c AS (
    SELECT ts, soc_now, soc_target, session_energy_kwh, desired_phase,
           wpa_meas, wpa_meas_valid
    FROM peb_charge_cycle
    WHERE charger_w > 200
      AND ts > now() - interval '14 days'
),
flagged AS (
    SELECT *,
        CASE WHEN ts - LAG(ts) OVER w > interval '15 min'
                  OR LAG(ts) OVER w IS NULL
             THEN 1 ELSE 0 END AS new_grp,
        CASE WHEN desired_phase IS DISTINCT FROM LAG(desired_phase) OVER w
                  AND LAG(desired_phase) OVER w IS NOT NULL
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
  AND NOT EXISTS (
        SELECT 1 FROM peb_charge_session e WHERE e.start_ts = s.start_ts
  )
ON CONFLICT (start_ts) DO NOTHING;
"""


def process_sessions(url: str) -> int:
    """Detecteer voltooide laadsessies en schrijf ze naar peb_charge_session."""
    conn = psycopg2.connect(url, connect_timeout=_CONNECT_TIMEOUT)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(_SESSION_SQL)
            return cur.rowcount
    finally:
        conn.close()


def forecast_upsert(
    url: str, day: str, forecast_kwh: float | None, actual_kwh: float | None
) -> None:
    """Upsert forecast/actual voor een dag; bereken ratio zodra beide bekend zijn."""
    conn = psycopg2.connect(url, connect_timeout=_CONNECT_TIMEOUT)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO peb_forecast_accuracy "
                "(day, forecast_kwh, actual_kwh, ratio) "
                "VALUES (%s,%s,%s,NULL) "
                "ON CONFLICT (day) DO UPDATE SET "
                "  forecast_kwh = COALESCE(EXCLUDED.forecast_kwh, "
                "                          peb_forecast_accuracy.forecast_kwh), "
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
    finally:
        conn.close()


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
    conn = psycopg2.connect(url, connect_timeout=_CONNECT_TIMEOUT)
    try:
        with conn, conn.cursor() as cur:
            # Forecast-bias: gemiddelde actual/forecast-ratio (laatste 30 dagen).
            cur.execute(
                "SELECT AVG(ratio) FROM peb_forecast_accuracy "
                "WHERE ratio IS NOT NULL AND ratio BETWEEN 0.2 AND 3.0 "
                "AND day > (now()::date - 30)"
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                out["forecast_bias"] = float(row[0])

            # Geleerde kWh per 1% SoC uit voltooide sessies (incl. laadverlies).
            cur.execute(
                "SELECT AVG(energy_kwh / NULLIF(soc_end - soc_start, 0)) "
                "FROM peb_charge_session "
                "WHERE (soc_end - soc_start) >= 15 AND energy_kwh > 1 "
                "AND start_ts > now() - interval '60 days'"
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                out["kwh_per_pct"] = float(row[0])

            # Per-fase W/A uit geldige cyclus-metingen (laatste 30 dagen).
            cur.execute(
                "SELECT desired_phase, AVG(wpa_meas) FROM peb_charge_cycle "
                "WHERE wpa_meas_valid AND wpa_meas BETWEEN 150 AND 250 "
                "AND desired_phase IN (1, 3) "
                "AND ts > now() - interval '30 days' "
                "GROUP BY desired_phase"
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
                "AND start_ts > now() - interval '30 days'"
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                out["hit_rate"] = float(row[0])
    finally:
        conn.close()
    return out

