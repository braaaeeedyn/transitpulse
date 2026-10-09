"""Checks on the real local warehouse (data/transitpulse.duckdb) after the pipeline has run:

    uv run python tasks.py baywheels && uv run python tasks.py dbt && uv run python tasks.py forecast
    uv run --group dbt --group ml pytest -m localdata tests/local

Excluded from the default test run (marker `localdata`). They fail, rather than skip, when the file or a table is
missing, so a green run means the data really is there.
"""

import datetime as dt
import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "transitpulse.duckdb"

pytestmark = pytest.mark.localdata


@pytest.fixture(scope="module")
def con():
    assert DB.exists(), f"{DB} not found: build it with tasks.py baywheels / dbt / forecast"
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def q(con, sql, params=None):
    return con.execute(sql, params or []).fetchall()


def test_baywheels_loaded_for_2019_and_2025(con):
    years = {
        y: (days, trips)
        for y, days, trips in q(
            con,
            "select extract(year from trip_date), count(*), sum(trips) from marts.fct_bike_trips_daily group by 1",
        )
    }
    for year in (2019, 2025):
        days, trips = years[year]
        assert days >= 360, (year, days)
        assert trips > 1_000_000, (year, trips)
    # cleaned rows reconcile with the pipeline's audit
    for year in (2019, 2025):
        audit = json.loads(
            (ROOT / "data" / "parquet" / "baywheels_audit" / f"year={year}" / "audit.json").read_text()
        )
        assert audit["rows_out"] == years[year][1]
        assert audit["rows_in"] == audit["rows_out"] + sum(audit["dropped"].values())
    schemas = dict(
        q(
            con,
            "select extract(year from trip_date), min(schema_version) from staging.stg_baywheels_trips group by 1",
        )
    )
    assert schemas == {2019: "legacy", 2025: "lyft"}


def test_bikes_vs_trains_mart_has_both_years(con):
    rows = q(
        con,
        "select extract(year from month_start) as y, count(*), count(bart_entries), count(bike_trips), "
        "min(bart_index_2019), max(bart_index_2019), min(bike_index_2019), max(bike_index_2019) "
        "from marts.mart_bikes_vs_trains group by 1 order by 1",
    )
    by_year = {r[0]: r[1:] for r in rows}
    assert by_year[2019][:3] == (12, 12, 12)
    assert by_year[2025][:3] == (12, 12, 12)
    assert by_year[2019][3] == pytest.approx(100) and by_year[2019][4] == pytest.approx(100)
    assert by_year[2019][5] == pytest.approx(100) and by_year[2019][6] == pytest.approx(100)
    assert 0 < by_year[2025][3] < 100  # BART is below 2019
    assert by_year[2025][6] > 0


def test_forecast_table_has_14_days_for_every_station(con):
    (through,) = q(con, "select max(trip_date) from marts.fct_station_daily")[0]
    active = {
        r[0]
        for r in q(con, "select station_code from marts.fct_station_daily where trip_date = ?", [through])
    }
    rows = q(
        con,
        "select station_code, count(*), min(forecast_date), max(forecast_date), count(distinct run_id), "
        "sum(case when 0 <= p10 and p10 <= p50 and p50 <= p90 then 0 else 1 end) "
        "from marts.forecast_station_daily group by 1",
    )
    assert {r[0] for r in rows} == active
    for code, n, first, last, runs, bad in rows:
        assert n == 14, code
        assert first == through + dt.timedelta(days=1) and last == through + dt.timedelta(days=14), code
        assert runs == 1 and bad == 0, code


def test_forecast_run_logged_with_cis(con):
    (run_id,) = q(con, "select distinct run_id from marts.forecast_station_daily")[0]
    cols = [
        "data_through",
        "folds",
        "horizon",
        "bootstrap_b",
        "mae_lgbm",
        "mae_lgbm_lo",
        "mae_lgbm_hi",
        "rmse_lgbm",
        "rmse_lgbm_lo",
        "rmse_lgbm_hi",
        "mae_baseline",
        "mae_baseline_lo",
        "mae_baseline_hi",
        "rmse_baseline",
        "rmse_baseline_lo",
        "rmse_baseline_hi",
        "mae_diff",
        "mae_diff_lo",
        "mae_diff_hi",
        "coverage_p10_p90",
        "fold_metrics_json",
    ]
    row = q(con, f"select {', '.join(cols)} from ml.forecast_runs where run_id = ?", [run_id])
    assert len(row) == 1, "the published forecast's run is missing from ml.forecast_runs"
    r = dict(zip(cols, row[0], strict=True))
    (through,) = q(con, "select max(trip_date) from marts.fct_station_daily")[0]
    assert r["data_through"] == through
    assert r["folds"] >= 6 and r["horizon"] == 14 and r["bootstrap_b"] >= 1000
    for m in ("mae_lgbm", "rmse_lgbm", "mae_baseline", "rmse_baseline", "mae_diff"):
        assert r[f"{m}_lo"] <= r[m] <= r[f"{m}_hi"], m
    assert r["mae_diff"] == pytest.approx(r["mae_baseline"] - r["mae_lgbm"])
    assert 0 <= r["coverage_p10_p90"] <= 1
    assert len(json.loads(r["fold_metrics_json"])) == r["folds"]


def test_local_facts_cover_2018_to_2025(con):
    # every year of BART Parquet on disk is in the facts (incremental runs used to skip backfilled years)
    on_disk = sorted(
        int(p.name.split("=")[1])
        for p in (ROOT / "data" / "parquet" / "bart_od").glob("year=*")
        if p.is_dir()
    )
    assert on_disk[0] <= 2018 and on_disk[-1] >= 2025, on_disk
    years = dict(
        q(
            con,
            "select extract(year from trip_date), count(distinct trip_date) from marts.fct_trips_hourly group by 1",
        )
    )
    for y in range(2018, 2026):
        assert years.get(y, 0) >= 360, (y, years.get(y))  # BART's 2020 file is missing 4 days
    staged = q(con, "select count(distinct trip_date) from staging.stg_bart_od")[0][0]
    (loaded,) = q(con, "select count(distinct trip_date) from marts.fct_trips_hourly")[0]
    assert loaded == staged
    daily_years = {
        r[0] for r in q(con, "select distinct extract(year from trip_date) from marts.fct_station_daily")
    }
    assert set(range(2018, 2026)) <= daily_years


def test_forecast_trained_on_full_history_with_calibration(con):
    (run_id,) = q(con, "select distinct run_id from marts.forecast_station_daily")[0]
    cols = ["train_start", "coverage_p10_p90", "coverage_calibrated", "coverage_calibrated_lo",
            "coverage_calibrated_hi", "calib_folds", "conformal_q", "interval_method"]  # fmt: skip
    row = q(con, f"select {', '.join(cols)} from ml.forecast_runs where run_id = ?", [run_id])
    assert len(row) == 1
    r = dict(zip(cols, row[0], strict=True))
    assert r["train_start"] <= dt.date(2024, 1, 31), r["train_start"]
    assert r["coverage_calibrated"] is not None and r["calib_folds"] >= 1 and r["conformal_q"] is not None
    assert r["coverage_calibrated_lo"] <= r["coverage_calibrated"] <= r["coverage_calibrated_hi"]
    (n, bad, missing) = q(
        con,
        "select count(*), sum(case when lower <= p50 and p50 <= upper and lower >= 0 then 0 else 1 end), "
        "count(*) - least(count(lower), count(upper)) from marts.forecast_station_daily",
    )[0]
    assert n > 0 and bad == 0 and missing == 0


def test_api_reads_local_warehouse(con, monkeypatch):
    from api import warehouse
    from api.cache import cache
    from api.main import app
    from api.settings import get_settings

    monkeypatch.setenv("TP_WAREHOUSE", "duckdb")
    monkeypatch.setenv("TP_DUCKDB_PATH", str(DB))
    get_settings.cache_clear()
    warehouse._make.cache_clear()
    cache.clear()
    try:
        client = TestClient(app)

        kpis = client.get("/api/kpis").json()
        (through,) = q(con, "select max(trip_date) from marts.mart_kpis_daily")[0]
        assert kpis["data_through"] == str(through)
        (avg_entries,) = q(
            con,
            "select avg(total_entries) from marts.mart_kpis_daily where trip_date > ? and trip_date <= ?",
            [through - dt.timedelta(days=28), through],
        )[0]
        tiles = {t["id"]: t for t in kpis["tiles"]}
        assert tiles["entries"]["value"] == pytest.approx(avg_entries)

        trend = client.get("/api/trends/ridership").json()
        monthly = q(con, "select month_start, avg_daily_entries from marts.mart_ridership_monthly order by 1")
        assert [(r["month_start"], r["avg_daily_entries"]) for r in trend["rows"]] == [
            (str(m), pytest.approx(v)) for m, v in monthly
        ]

        bikes = client.get("/api/trends/bikes-vs-trains").json()
        assert len(bikes["rows"]) == q(con, "select count(*) from marts.mart_bikes_vs_trains")[0][0]

        summary = client.get("/api/stations/EMBR/summary").json()
        (entries,) = q(
            con,
            "select entries from marts.fct_station_daily where station_code = 'EMBR' and trip_date = ?",
            [through],
        )[0]
        assert summary["entries"] == entries and summary["data_through"] == str(through)

        fc = client.get("/api/forecast/EMBR").json()
        table = q(
            con,
            "select forecast_date, p50 from marts.forecast_station_daily where station_code = 'EMBR' order by 1",
        )
        assert [(f["date"], f["p50"]) for f in fc["forecast"]] == [
            (str(d), pytest.approx(p)) for d, p in table
        ]
        assert fc["data_through"] == str(through)
        assert fc["model"]["mae"] > 0
    finally:
        get_settings.cache_clear()
        warehouse._make.cache_clear()
        cache.clear()
