"""Read-only data endpoints for the site (IMPLEMENTATION_PLAN §5).

They read the dbt marts from the configured warehouse (`TP_WAREHOUSE`: DuckDB locally, BigQuery in the cloud).
When no warehouse is connected they answer 503 with a machine-readable reason, which the site shows as an empty
state. Date windows are computed here in Python and passed as parameters, so the SQL is the same on both backends.
"""

import datetime as dt
import math
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

    # peak-hour share on service weekdays; delta vs the same ISO weeks of ISO year 2019, in percentage points.
    # ISO weeks are matched as (iso_year, iso_week) pairs in Python, so 2019-12-30 (week 1 of 2020) is not a
    # baseline day and 2018-12-31 (week 1 of 2019) is.
    peak = _mean([r["peak_hour_share"] for r in weekdays])
    peak_delta = None
    if peak is not None and start.year != BASELINE_YEAR:
        weeks = {(start + dt.timedelta(days=i)).isocalendar().week for i in range((end - start).days + 1)}
        base = wh.query(
            f"select trip_date, peak_hour_share from {kpis} "
            "where trip_date >= @start and trip_date <= @end and is_service_weekday",
            {
                "start": dt.date.fromisocalendar(BASELINE_YEAR, 1, 1),
                "end": dt.date.fromisocalendar(BASELINE_YEAR + 1, 1, 1) - dt.timedelta(days=1),
            },
        )
        base_peak = _mean(
            [
                r["peak_hour_share"]
                for r in base
                if (iso := _as_date(r["trip_date"]).isocalendar()).year == BASELINE_YEAR and iso.week in weeks
            ]
        )
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


INTERVAL_NOMINAL = 0.8  # the raw band is the model's 10th-90th percentile


def _interval(run: dict, has_band: bool) -> dict:
    """How the published band was made and how often it held the actual value in back-testing.

    Reads either run-log schema: runs written before calibration existed have only `coverage_p10_p90`, and their
    forecast rows only p10/p90. A calibrated band is published only if it came closer to its nominal coverage than
    the raw quantiles did; otherwise the raw band is served."""
    raw_ci = [run.get("coverage_p10_p90_lo"), run.get("coverage_p10_p90_hi")]
    raw = {
        "method": "quantile (p10-p90)",
        "nominal": INTERVAL_NOMINAL,
        "coverage": run.get("coverage_p10_p90"),
        "coverage_ci": raw_ci if None not in raw_ci else None,
        "calibrated": False,
    }
    cal = run.get("coverage_calibrated")
    if not has_band or cal is None or not run.get("calib_folds"):
        return raw
    nominal = run.get("interval_nominal") or INTERVAL_NOMINAL
    if raw["coverage"] is not None and abs(cal - nominal) > abs(raw["coverage"] - nominal):
        return raw
    ci = [run.get("coverage_calibrated_lo"), run.get("coverage_calibrated_hi")]
    return {
        "method": run.get("interval_method") or "split-conformal",
        "nominal": nominal,
        "coverage": cal,
        "coverage_ci": ci if None not in ci else None,
        "calibrated": True,
    }


def _forecast(wh: Warehouse, code: str) -> dict:
    # `select *`: the published band columns (lower/upper) only exist in runs written since calibration
    try:
        rows = wh.query(
            f"select * from {wh.table('forecast_station_daily')} where station_code = @code order by forecast_date",
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
            f"select * from {wh.table('forecast_runs', schema='ml')} where run_id = @run_id",
            {"run_id": rows[0]["run_id"]},
        )
    except TableNotFound:
        runs = []
    has_band = all(r.get("lower") is not None and r.get("upper") is not None for r in rows)
    interval = _interval(runs[0], has_band) if runs else None
    calibrated = bool(interval and interval["calibrated"])
    run = runs[0] if runs else {}
    diff_ci = [run.get("mae_diff_lo"), run.get("mae_diff_hi")]
    # every run column is read with .get(): an older or partial run log still serves the forecast
    model = (
        {
            "mae": run.get("mae_lgbm"),
            "baseline_mae": run.get("mae_baseline"),
            "mae_diff_ci": diff_ci if None not in diff_ci else None,
            "interval_coverage": run.get("coverage_p10_p90"),
            "interval": interval,
        }
        if runs
        else None
    )
    return {
        "code": code,
        "name": _station_name(wh, code) or code,
        "data_through": through,
        "forecast_start": _as_date(rows[0]["forecast_date"]),
        "forecast_end": _as_date(rows[-1]["forecast_date"]),
        "generated_at": rows[0]["generated_at"],
        "forecast": [
            {
                "date": _as_date(r["forecast_date"]),
                "p10": r["p10"],
                "p50": r["p50"],
                "p90": r["p90"],
                # the band the site draws: calibrated when that's what is published, else the raw quantiles
                "lo": r["lower"] if calibrated else r["p10"],
                "hi": r["upper"] if calibrated else r["p90"],
            }
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


# --- station closures --------------------------------------------------------------------------------

# The "case to keep" rules (docs/STATION_CLOSURES.md). The first three were fixed in the build plan before the section
# was built; "growing" was added afterwards at the owner's request. Each met rule is a point for keeping the station;
# the page shows this text and never restates a threshold itself.
CLOSURE_LOWEST_N = 10  # BART staff's cut: "the 10 lowest-ridership stations"
CLOSURE_MILES = 3.0  # beyond a short bike ride or walk
CLOSURE_RULES = [
    {
        "id": "riders",
        "text": f"Busier than BART's {CLOSURE_LOWEST_N} least-used stations: its weekday trips (entries plus exits) "
        f"rank above the bottom {CLOSURE_LOWEST_N}.",
    },
    {
        "id": "recovery",
        "text": f"Recovering at least as well as BART overall: its weekday trips as a share of {BASELINE_YEAR} are at or "
        "above BART's systemwide share (whole percentages).",
    },
    {
        "id": "distance",
        "text": f"Hard to replace: the nearest station that stays open if every listed station closes is at least "
        f"{CLOSURE_MILES:.1f} miles away in a straight line.",
    },
    {
        "id": "growing",
        "text": "Riders coming back: its weekday trips in the latest year are up on the year before (to 0.1%).",
    },
]
CLOSURE_VERDICTS = {
    "strong": "Three or four rules met",
    "mixed": "Two rules met",
    "weak": "One rule or none met",
}


# rounded half up (round() goes to even): the rules compare the rounded numbers the page shows
def _pct(ratio: float | None) -> int | None:
    return None if ratio is None else math.floor(ratio * 100 + 0.5)


def _miles(miles: float | None) -> float | None:
    return None if miles is None else math.floor(miles * 10 + 0.5) / 10


def _change_pct(ratio: float | None) -> float | None:
    return None if ratio is None else math.floor(ratio * 1000 + 0.5) / 10


def closure_verdict(points: int) -> str:
    return "strong" if points >= 3 else "mixed" if points == 2 else "weak"


def closure_criteria(
    rank_lowest: int,
    recovery_pct: int | None,
    system_pct: int | None,
    miles: float | None,
    change_pct: float | None = None,
) -> dict:
    return {
        "riders": rank_lowest > CLOSURE_LOWEST_N,
        "recovery": recovery_pct is not None and system_pct is not None and recovery_pct >= system_pct,
        "distance": miles is not None and miles >= CLOSURE_MILES,
        "growing": change_pct is not None and change_pct > 0,
    }


def _closures(wh: Warehouse) -> dict:
    try:
        rows = wh.query(
            "select station_code, station_name, closure_group, closure_segment, period_year, avg_weekday_entries, "
            "avg_weekday_exits, avg_weekday_trips, rank_lowest, stations_ranked, share_of_weekday_trips, "
            "recovery_ratio, system_recovery_ratio, change_vs_prev_year, nearest_open_code, nearest_open_name, "
            f"nearest_open_miles from {wh.table('mart_station_closures')} order by rank_lowest, station_code"
        )
        dests = wh.query(
            "select origin_code, destination_code, destination_name, share_of_origin_trips "
            f"from {wh.table('mart_closure_destinations')} order by origin_code, destination_rank"
        )
        scenarios = wh.query(
            f"select scenario, share_of_weekday_trips from {wh.table('mart_closure_scenarios')}"
        )
        through = _max_date_kpis(wh)
    except TableNotFound as e:
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from e
    listed = [r for r in rows if r["closure_group"] is not None]
    if not listed:
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE)

    system_pct = _pct(rows[0]["system_recovery_ratio"])
    shares = {s["scenario"]: s["share_of_weekday_trips"] for s in scenarios}
    lowest = [r for r in rows if r["rank_lowest"] <= CLOSURE_LOWEST_N]
    by_origin: dict[str, list] = {}
    for d in dests:
        by_origin.setdefault(d["origin_code"], []).append(
            {
                "code": d["destination_code"],
                "name": d["destination_name"],
                "share": d["share_of_origin_trips"],
            }
        )

    stations = []
    for r in sorted(listed, key=lambda r: (r["closure_group"], r["avg_weekday_trips"], r["station_code"])):
        recovery_pct = _pct(r["recovery_ratio"])
        miles = _miles(r["nearest_open_miles"])
        criteria = closure_criteria(
            int(r["rank_lowest"]), recovery_pct, system_pct, miles, _change_pct(r["change_vs_prev_year"])
        )
        points = sum(criteria.values())
        stations.append(
            {
                "code": r["station_code"],
                "name": r["station_name"],
                "group": int(r["closure_group"]),
                "segment": r["closure_segment"],
                "weekday_trips": round(r["avg_weekday_trips"]),
                "weekday_entries": round(r["avg_weekday_entries"]),
                "weekday_exits": round(r["avg_weekday_exits"]),
                "rank_lowest": int(r["rank_lowest"]),
                "share_of_trips": r["share_of_weekday_trips"],
                "recovery_pct": recovery_pct,
                "change_vs_prev_year": r["change_vs_prev_year"],
                "nearest_open": {
                    "code": r["nearest_open_code"],
                    "name": r["nearest_open_name"],
                    "miles": miles,
                },
                "destinations": by_origin.get(r["station_code"], []),
                "criteria": criteria,
                "points": points,
                "verdict": closure_verdict(points),
            }
        )
    return {
        "period_year": int(listed[0]["period_year"]),
        "baseline_year": BASELINE_YEAR,
        "data_through": through,
        "system": {
            "stations": int(rows[0]["stations_ranked"]),
            "recovery_pct": system_pct,
            "share_first_10": shares.get("first_10"),
            "share_all_15": shares.get("all_15"),
            "lowest_10": [
                {
                    "code": r["station_code"],
                    "name": r["station_name"],
                    "listed": r["closure_group"] is not None,
                }
                for r in lowest
            ],
            "first_10_in_lowest_10": sum(r["closure_group"] == 1 for r in lowest),
        },
        "rules": CLOSURE_RULES,
        "verdicts": CLOSURE_VERDICTS,
        "stations": stations,
        "source": BART_SOURCE,
    }


@router.get("/closures")
def closures() -> dict:
    wh = _warehouse()
    return _cached(wh, ("closures",), HOUR, lambda: _closures(wh))
