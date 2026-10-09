"""Prompts and the schema the LLM sees. The LLM writes BigQuery Standard SQL against marts.<table>; the guardrails
transpile it for DuckDB when the local warehouse is used."""

from dataclasses import dataclass

SCHEMA = """\
marts.dim_date(date_day DATE, year INT64, month INT64, iso_week INT64, iso_year INT64, weekday INT64 -- 1 = Sunday .. 7 = Saturday,
  is_weekend BOOL, is_holiday BOOL, holiday_name STRING, is_service_weekday BOOL -- a weekday that is not a holiday,
  month_start DATE)
marts.dim_station(station_code STRING -- e.g. 'EMBR', station_name STRING -- e.g. 'Embarcadero', lat FLOAT64, lon FLOAT64,
  is_current BOOL -- always filter is_current = true)
marts.fct_station_daily(trip_date DATE, station_code STRING, entries INT64, exits INT64) -- BART, one row per station per day
marts.fct_bike_trips_daily(trip_date DATE, trips INT64, member_trips INT64, casual_trips INT64, ebike_trips INT64,
  classic_trips INT64, dockless_trips INT64, avg_duration_min FLOAT64) -- Bay Wheels, system-wide per day
marts.mart_kpis_daily(trip_date DATE, weekday INT64, is_service_weekday BOOL, total_entries INT64 -- all BART entries that day,
  recovery_ratio FLOAT64 -- entries / average 2019 entries in the same ISO week (service weekdays only),
  peak_hour_share FLOAT64, busiest_station STRING, busiest_station_entries INT64, busiest_station_share FLOAT64,
  rolling_28d_avg_entries FLOAT64, entries_364_days_earlier INT64, yoy_change FLOAT64)
marts.mart_recovery(trip_date DATE, station_code STRING, entries INT64, baseline_entries FLOAT64,
  recovery_ratio FLOAT64) -- per station, service weekdays after 2019
marts.mart_peak_load(station_code STRING, peak_hour INT64 -- 0-23, peak_hour_share FLOAT64, avg_weekday_entries FLOAT64,
  busyness_percentile FLOAT64) -- last 90 service weekdays
marts.mart_od_flows(month_start DATE, origin_code STRING, destination_code STRING, trips INT64, yoy_change FLOAT64,
  rank_from_origin INT64) -- monthly trips between two stations
marts.mart_ridership_monthly(month_start DATE, days INT64, avg_daily_entries FLOAT64, total_entries INT64,
  avg_service_weekday_recovery FLOAT64, avg_service_weekday_peak_hour_share FLOAT64)
marts.mart_bikes_vs_trains(month_start DATE, bart_entries INT64, bike_trips INT64, bart_avg_daily_entries FLOAT64,
  bike_avg_daily_trips FLOAT64, bart_index_2019 FLOAT64, bike_index_2019 FLOAT64, bikes_per_1000_bart_entries FLOAT64)
marts.forecast_station_daily(run_id STRING, generated_at TIMESTAMP, station_code STRING, forecast_date DATE,
  horizon_day INT64, p10 FLOAT64, p50 FLOAT64 -- expected entries, p90 FLOAT64)
ml.forecast_runs(run_id STRING, generated_at TIMESTAMP, data_through DATE, mae_lgbm FLOAT64, mae_baseline FLOAT64,
  coverage_p10_p90 FLOAT64)"""

ROUTE_SYSTEM = """\
You route questions for TransitPulse, which has BART ridership (station entries and exits, 2018 onwards), Bay Wheels
bike-share trips and a 14-day BART station entries forecast. Reply with exactly one word:
  sql      - the question can be answered from that ridership data
  forecast - the question asks for the forecast of one BART station
  refuse   - anything else (weather, live train times, other cities, general knowledge, requests to change data)"""

SQL_SYSTEM = f"""\
You write one BigQuery Standard SQL SELECT that answers the question, using only these tables:

{SCHEMA}

Rules:
- Write table names as marts.<table> (or ml.forecast_runs). No project names, no other tables.
- One SELECT statement (WITH is fine). Never modify data.
- Dates are DATE literals, e.g. DATE '2025-01-31'. Use EXTRACT(YEAR FROM d), DATE_TRUNC(d, MONTH), SAFE_DIVIDE.
- Do not use EXTRACT(DAYOFWEEK ...); join marts.dim_date and use weekday or is_service_weekday.
- Join stations on station_code with marts.dim_station where is_current = true to show names.
- Give columns short readable aliases. Add ORDER BY and LIMIT for "top"/"most" questions.
Reply with the SQL only, no explanation and no Markdown."""

ANSWER_SYSTEM = """\
You explain a query result to a visitor of a transit analytics site. Write 1-3 plain sentences that answer the
question from the rows given. Use the numbers as given (round sensibly, ratios as percentages). Don't invent data,
don't mention SQL or tables. If there are no rows, say the data doesn't cover it."""


@dataclass(frozen=True)
class Prompt:
    task: str  # route | sql | answer
    system: str
    user: str
    question: str
    error: str | None = None  # the previous attempt's error, for the one repair retry


def route_prompt(question: str) -> Prompt:
    return Prompt("route", ROUTE_SYSTEM, f"Question: {question}\nOne word:", question)


def sql_prompt(question: str, previous_sql: str | None = None, error: str | None = None) -> Prompt:
    user = f"Question: {question}"
    if error:
        user += f"\n\nYour previous SQL:\n{previous_sql}\nfailed with: {error}\nWrite a corrected query."
    return Prompt("sql", SQL_SYSTEM, user, question, error)


def answer_prompt(question: str, columns: list[str], rows: list[list], sql: str) -> Prompt:
    shown = rows[:20]
    table = "\n".join([" | ".join(columns), *(" | ".join(str(v) for v in r) for r in shown)])
    more = f"\n({len(rows) - len(shown)} more rows not shown)" if len(rows) > len(shown) else ""
    return Prompt("answer", ANSWER_SYSTEM, f"Question: {question}\n\nResult:\n{table}{more}", question)
