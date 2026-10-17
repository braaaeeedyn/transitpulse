"""The questions the site suggests (the Ask panel's chips and the refusal's suggestions), each with a reviewed query.

A suggestion must always work, so these skip the LLM router and the SQL writer: the query still goes through the
guardrails, the dry run and the byte budget like any other, and the model still writes the answer sentence. Each
query is checked against the local warehouse by tests/local/test_suggested.py; web/index.html's chips must be keys
here (tests/test_agent_graph.py). The forecast suggestion needs no entry: it has its own fixed query.

"Last 12 months" (last_12_mo) is the 365 days up to the newest day in the data, so the answers move with each BART release
instead of naming a year that will go stale.
"""

import re

FORECAST_SUGGESTION = "What's the 14-day forecast for Embarcadero?"

SUGGESTED_SQL: dict[str, str] = {
    "Which stations grew most since 2022?": """
        WITH latest AS (SELECT MAX(trip_date) AS d FROM marts.fct_station_daily),
        y AS (
          SELECT f.station_code,
                 AVG(IF(EXTRACT(YEAR FROM f.trip_date) = 2022, f.entries, NULL)) AS avg_2022,
                 AVG(IF(f.trip_date > DATE_SUB(l.d, INTERVAL 365 DAY), f.entries, NULL)) AS avg_latest
          FROM marts.fct_station_daily AS f CROSS JOIN latest AS l
          WHERE f.trip_date >= DATE '2022-01-01'
          GROUP BY f.station_code
        )
        SELECT s.station_name AS station,
               ROUND(y.avg_2022) AS per_day_2022,
               ROUND(y.avg_latest) AS per_day_last_12_mo,
               ROUND(100 * (y.avg_latest / y.avg_2022 - 1), 1) AS growth_pct
        FROM y JOIN marts.dim_station AS s ON s.station_code = y.station_code AND s.is_current
        WHERE y.avg_2022 > 0
        ORDER BY growth_pct DESC
        LIMIT 5""",
    "Which stations had the most entries in 2025?": """
        SELECT s.station_name AS station, SUM(f.entries) AS entries_2025
        FROM marts.fct_station_daily AS f
        JOIN marts.dim_station AS s ON s.station_code = f.station_code AND s.is_current
        WHERE f.trip_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31'
        GROUP BY station
        ORDER BY entries_2025 DESC
        LIMIT 5""",
    "How close is ridership to 2019?": """
        WITH latest AS (SELECT MAX(trip_date) AS d FROM marts.mart_kpis_daily),
        a AS (
          SELECT AVG(IF(k.trip_date > DATE_SUB(l.d, INTERVAL 365 DAY), k.total_entries, NULL)) AS latest_avg,
                 AVG(IF(EXTRACT(YEAR FROM k.trip_date) = 2019, k.total_entries, NULL)) AS avg_2019,
                 MAX(l.d) AS data_through
          FROM marts.mart_kpis_daily AS k CROSS JOIN latest AS l
        )
        SELECT ROUND(latest_avg) AS per_day_last_12_mo, ROUND(avg_2019) AS per_day_2019,
               ROUND(100 * latest_avg / avg_2019, 1) AS pct_of_2019, data_through
        FROM a""",
    "How close is weekday ridership to 2019?": """
        WITH latest AS (SELECT MAX(trip_date) AS d FROM marts.mart_kpis_daily)
        SELECT ROUND(100 * AVG(k.recovery_ratio), 1) AS weekday_pct_of_2019,
               MIN(k.trip_date) AS from_date, MAX(k.trip_date) AS to_date
        FROM marts.mart_kpis_daily AS k CROSS JOIN latest AS l
        WHERE k.is_service_weekday AND k.trip_date > DATE_SUB(l.d, INTERVAL 365 DAY)""",
    "Bikes vs. trains in the latest month?": """
        SELECT month_start AS month,
               ROUND(bart_index_2019, 1) AS bart_pct_of_2019,
               ROUND(bike_index_2019, 1) AS bikes_pct_of_2019,
               ROUND(bart_avg_daily_entries) AS bart_per_day,
               ROUND(bike_avg_daily_trips) AS bikes_per_day
        FROM marts.mart_bikes_vs_trains
        WHERE bart_index_2019 IS NOT NULL AND bike_index_2019 IS NOT NULL
        ORDER BY month_start DESC
        LIMIT 1""",
    "Which station has the highest peak-hour share?": """
        SELECT s.station_name AS station, p.peak_hour,
               ROUND(100 * p.peak_hour_share, 1) AS peak_hour_pct
        FROM marts.mart_peak_load AS p
        JOIN marts.dim_station AS s ON s.station_code = p.station_code AND s.is_current
        ORDER BY p.peak_hour_share DESC
        LIMIT 5""",
}


def normalize(question: str) -> str:
    """Case, spacing and trailing punctuation don't matter: a chip's text and a typed copy of it match."""
    return re.sub(r"\s+", " ", question).strip().rstrip("?.! ").lower()


_BY_KEY = {normalize(q): sql for q, sql in SUGGESTED_SQL.items()}


def suggested_sql(question: str) -> str | None:
    return _BY_KEY.get(normalize(question))
