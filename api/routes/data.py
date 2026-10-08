"""Read-only data endpoints for the site (IMPLEMENTATION_PLAN §5).

They read the dbt marts from the configured warehouse (`TP_WAREHOUSE`: DuckDB locally, BigQuery in the cloud).
When no warehouse is connected they answer 503 with a machine-readable reason, which the site shows as an empty
state. Date windows are computed here in Python and passed as parameters, so the SQL is the same on both backends.
"""

import datetime as dt
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from api.cache import HOUR, cache
from api.warehouse import TableNotFound, Warehouse, get_warehouse

router = APIRouter(prefix="/api", tags=["data"])

NOT_CONNECTED = {"code": "warehouse_not_connected", "message": "Ridership data isn't connected yet."}
UNKNOWN_STATION = {"code": "unknown_station", "message": "No BART station has that code."}
NO_FORECAST = {"code": "forecast_not_available", "message": "There's no forecast for this station yet."}
NOT_AVAILABLE = {"code": "data_not_available", "message": "This data hasn't been loaded yet."}

STATION_CODE = re.compile(r"^[A-Z0-9]{4}$")
BASELINE_YEAR = 2019  # dbt var('baseline_year')
WINDOW_DAYS = 28
YEAR_DAYS = 364  # 52 weeks: compares the same weekdays
BART_SOURCE = "BART hourly origin-destination ridership reports."


def _warehouse() -> Warehouse:
    wh = get_warehouse()
    if wh is None:
        raise HTTPException(status_code=503, detail=NOT_CONNECTED)
    return wh


def _cached(wh: Warehouse, key: tuple, ttl: float, compute: Callable[[], Any]) -> Any:
    return cache.get_or_compute((wh.cache_key, *key), ttl, compute)


def _check_code(code: str) -> str:
    if not STATION_CODE.match(code):
        raise HTTPException(status_code=404, detail=UNKNOWN_STATION)
    return code


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def _station_name(wh: Warehouse, code: str) -> str | None:
    rows = wh.query(
        f"select station_name from {wh.table('dim_station')} where station_code = @code and is_current",
        {"code": code},
    )
    return rows[0]["station_name"] if rows else None


# --- KPI tiles ---------------------------------------------------------------------------------------


def _kpis(wh: Warehouse) -> dict:
    kpis = wh.table("mart_kpis_daily")
    top = wh.query(f"select max(trip_date) as data_through from {kpis}")
    if not top or top[0]["data_through"] is None:
        return {"data_through": None, "window": None, "tiles": [], "source": BART_SOURCE}
    end = _as_date(top[0]["data_through"])
    start = end - dt.timedelta(days=WINDOW_DAYS - 1)
    cols = (
        "trip_date, is_service_weekday, total_entries, recovery_ratio, peak_hour_share, busiest_station, "
        "busiest_station_share, entries_364_days_earlier"
    )
    window_sql = (
        f"select {cols} from {kpis} where trip_date >= @start and trip_date <= @end order by trip_date"
    )
    rows = wh.query(window_sql, {"start": start, "end": end})
    weekdays = [r for r in rows if r["is_service_weekday"]]

    # recovery: mean over the window's service weekdays; delta vs the same window 52 weeks earlier, if loaded
    recovery = _mean([r["recovery_ratio"] for r in weekdays])
    prev = wh.query(
        window_sql,
        {"start": start - dt.timedelta(days=YEAR_DAYS), "end": end - dt.timedelta(days=YEAR_DAYS)},
    )
    prev_weekdays = [r for r in prev if r["is_service_weekday"] and r["recovery_ratio"] is not None]
    prev_recovery = _mean([r["recovery_ratio"] for r in prev_weekdays])
    recovery_delta = (
        recovery - prev_recovery
        if recovery is not None and prev_recovery is not None and len(prev_weekdays) == len(weekdays)
        else None
    )

    # average daily entries; YoY only when every day in the window has its day 364 days earlier
    entries = _mean([r["total_entries"] for r in rows])
    priors = [r["entries_364_days_earlier"] for r in rows]
    yoy = (
        sum(r["total_entries"] for r in rows) / sum(priors) - 1
        if rows and all(p is not None for p in priors) and sum(priors) > 0
        else None
    )

    # peak-hour share on service weekdays; delta vs the same ISO weeks of 2019, in percentage points
    peak = _mean([r["peak_hour_share"] for r in weekdays])
    peak_delta = None
    if peak is not None and start.year != BASELINE_YEAR:
        dates = wh.table("dim_date")
        weeks = {
            r["iso_week"]
            for r in wh.query(
                f"select iso_week from {dates} where date_day >= @start and date_day <= @end",
                {"start": start, "end": end},
            )
        }
        base = wh.query(
            f"select d.iso_week, k.peak_hour_share from {kpis} as k inner join {dates} as d "
            "on k.trip_date = d.date_day where d.year = @year and d.is_service_weekday",
            {"year": BASELINE_YEAR},
        )
        base_peak = _mean([r["peak_hour_share"] for r in base if r["iso_week"] in weeks])
        peak_delta = peak - base_peak if base_peak is not None else None

    # busiest station: the one that was busiest on the most days, and its mean share on those days
    counts = Counter(r["busiest_station"] for r in rows if r["busiest_station"])
    busiest = counts.most_common(1)[0][0] if counts else None
    busiest_share = _mean([r["busiest_station_share"] for r in rows if r["busiest_station"] == busiest])
    busiest_name = (_station_name(wh, busiest) or busiest) if busiest else None

    window = f"the {WINDOW_DAYS} days to {end:%b} {end.day}, {end.year}"
    tiles = [
        {
            "id": "recovery",
            "label": f"Recovery vs {BASELINE_YEAR}",
            "value": recovery,
            "unit": "percent",
            "delta": recovery_delta,
            "delta_label": "vs a year earlier" if recovery_delta is not None else None,
            "definition": f"Service-weekday entries as a share of an average {BASELINE_YEAR} weekday in the same "
            f"week of the year, averaged over {window}.",
        },
        {
            "id": "entries",
            "label": "Average daily entries",
            "value": entries,
            "unit": "entries",
            "delta": yoy,
            "delta_label": "vs a year earlier" if yoy is not None else None,
            "definition": f"Trips started per day, averaged over {window}. The change compares the same 28 "
            "days 52 weeks earlier, so weekdays line up.",
        },
        {
            "id": "peak_share",
            "label": "Peak-hour share",
            "value": peak,
            "unit": "percent",
            "delta": peak_delta,
            "delta_label": f"vs {BASELINE_YEAR}" if peak_delta is not None else None,
            "definition": f"Share of a service weekday's entries made in its busiest hour, averaged over {window}, "
            f"compared with the same weeks of {BASELINE_YEAR}.",
        },
        {
            "id": "busiest_station",
            "label": "Busiest station",
            "value": busiest_name,
            "code": busiest,
            "unit": None,
            "delta": None,
            "delta_label": f"{busiest_share * 100:.1f}% of all entries"
            if busiest_share is not None
            else None,
            "definition": f"The station with the most entries on the most days in {window} "
            f"(busiest on {counts[busiest] if busiest else 0} of {len(rows)} days), and its average share of "
            "all entries on those days.",
        },
    ]
    return {
        "data_through": end,
        "window": {"start": start, "end": end, "days": len(rows)},
        "tiles": tiles,
        "source": BART_SOURCE,
    }


@router.get("/kpis")
def kpis() -> dict:
    wh = _warehouse()
    return _cached(wh, ("kpis",), HOUR, lambda: _kpis(wh))


# --- trends ------------------------------------------------------------------------------------------


def _ridership_trend(wh: Warehouse) -> dict:
    rows = wh.query(
        "select month_start, days, avg_daily_entries, avg_service_weekday_recovery "
        f"from {wh.table('mart_ridership_monthly')} order by month_start"
    )
    return {
        "data_through": _max_date_kpis(wh),
        "rows": rows,
        "source": BART_SOURCE,
    }


def _max_date_kpis(wh: Warehouse) -> dt.date | None:
    top = wh.query(f"select max(trip_date) as d from {wh.table('mart_kpis_daily')}")
    return _as_date(top[0]["d"]) if top and top[0]["d"] is not None else None


@router.get("/trends/ridership")
def ridership_trend() -> dict:
    wh = _warehouse()
    return _cached(wh, ("trends/ridership",), HOUR, lambda: _ridership_trend(wh))


def _bikes_vs_trains(wh: Warehouse) -> dict:
    try:
        rows = wh.query(
            "select month_start, bart_entries, bike_trips, bart_avg_daily_entries, bike_avg_daily_trips, "
            f"bart_index_2019, bike_index_2019, bikes_per_1000_bart_entries from {wh.table('mart_bikes_vs_trains')} order by month_start"
        )
    except TableNotFound as e:
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from e
    return {
        "rows": rows,
        "source": f"{BART_SOURCE} Lyft Bay Wheels trip data.",
    }


@router.get("/trends/bikes-vs-trains")
def bikes_vs_trains() -> dict:
    wh = _warehouse()
    return _cached(wh, ("trends/bikes-vs-trains",), HOUR, lambda: _bikes_vs_trains(wh))


# --- stations ----------------------------------------------------------------------------------------


def _station_summary(wh: Warehouse, code: str) -> dict:
    daily = wh.table("fct_station_daily")
    latest = wh.query(
        f"select trip_date, entries from {daily} where station_code = @code order by trip_date desc limit 1",
        {"code": code},
    )
    if not latest:
        raise HTTPException(status_code=404, detail=UNKNOWN_STATION)
    day = _as_date(latest[0]["trip_date"])
    recovery = wh.query(
        f"select recovery_ratio from {wh.table('mart_recovery')} where station_code = @code and trip_date = @day",
        {"code": code, "day": day},
    )
    weekday_entries = wh.query(
        f"select f.entries from {daily} as f inner join {wh.table('dim_date')} as d on f.trip_date = d.date_day "
        "where f.station_code = @code and d.is_service_weekday and f.trip_date >= @start and f.trip_date <= @end",
        {"code": code, "start": day - dt.timedelta(days=WINDOW_DAYS - 1), "end": day},
    )
    peak = wh.query(
        f"select peak_hour, peak_hour_share from {wh.table('mart_peak_load')} where station_code = @code",
        {"code": code},
    )
    return {
        "code": code,
        "name": _station_name(wh, code) or code,
        "data_through": day,
        "entries": latest[0]["entries"],
        "recovery_ratio": recovery[0]["recovery_ratio"] if recovery else None,
        "avg_weekday_entries_28d": _mean([r["entries"] for r in weekday_entries]),
        "peak_hour": peak[0]["peak_hour"] if peak else None,
        "peak_hour_share": peak[0]["peak_hour_share"] if peak else None,
    }


@router.get("/stations/{code}/summary")
def station_summary(code: str) -> dict:
    wh = _warehouse()
    _check_code(code)
    return _cached(wh, ("station", code), HOUR, lambda: _station_summary(wh, code))


# --- forecasts ---------------------------------------------------------------------------------------


def _forecast(wh: Warehouse, code: str) -> dict:
    try:
        rows = wh.query(
            "select run_id, generated_at, forecast_date, p10, p50, p90 "
            f"from {wh.table('forecast_station_daily')} where station_code = @code order by forecast_date",
            {"code": code},
        )
    except TableNotFound:
        rows = []
    daily = wh.table("fct_station_daily")
    if not rows:
        known = wh.query(
            f"select station_code from {daily} where station_code = @code limit 1", {"code": code}
        )
        raise HTTPException(status_code=404, detail=NO_FORECAST if known else UNKNOWN_STATION)

    through = _as_date(rows[0]["forecast_date"]) - dt.timedelta(days=1)
    actuals = wh.query(
        f"select trip_date, entries from {daily} "
        "where station_code = @code and trip_date >= @start and trip_date <= @end order by trip_date",
        {"code": code, "start": through - dt.timedelta(days=WINDOW_DAYS - 1), "end": through},
    )
    try:
        runs = wh.query(
            "select mae_lgbm, mae_baseline, mae_diff_lo, mae_diff_hi, coverage_p10_p90 "
            f"from {wh.table('forecast_runs', schema='ml')} where run_id = @run_id",
            {"run_id": rows[0]["run_id"]},
        )
    except TableNotFound:
        runs = []
    model = (
        {
            "mae": runs[0]["mae_lgbm"],
            "baseline_mae": runs[0]["mae_baseline"],
            "mae_diff_ci": [runs[0]["mae_diff_lo"], runs[0]["mae_diff_hi"]],
            "interval_coverage": runs[0]["coverage_p10_p90"],
        }
        if runs
        else None
    )
    return {
        "code": code,
        "name": _station_name(wh, code) or code,
        "data_through": through,
        "generated_at": rows[0]["generated_at"],
        "forecast": [
            {"date": _as_date(r["forecast_date"]), "p10": r["p10"], "p50": r["p50"], "p90": r["p90"]}
            for r in rows
        ],
        "actuals": [{"date": _as_date(r["trip_date"]), "entries": r["entries"]} for r in actuals],
        "model": model,
    }


@router.get("/forecast/{code}")
def forecast(code: str) -> dict:
    wh = _warehouse()
    _check_code(code)
    return _cached(wh, ("forecast", code), 6 * HOUR, lambda: _forecast(wh, code))
