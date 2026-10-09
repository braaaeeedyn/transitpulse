"""Data endpoints (api/routes/data.py) against a small DuckDB warehouse built in tmp_path with the dbt mart columns,
plus the BigQuery backend with a fake client (no network)."""

import datetime as dt

import duckdb
import pytest
from fastapi.testclient import TestClient

from api import warehouse as warehouse_mod
from api.cache import TTLCache, cache
from api.main import app
from api.routes import data as data_routes
from api.settings import Settings, get_settings
from api.warehouse import BQ_MAX_BYTES_BILLED, BigQueryWarehouse, DuckDBWarehouse

# The fixture's "latest data" is Feb 2025, with Feb 2024 (for YoY) and Feb 2019 (the baseline) also loaded.
FIXTURE_SQL = """
create schema marts;
create schema ml;

create table marts.dim_station as
select * from (values
    ('sk1', 'EMBR', 'Embarcadero (old name)', false),
    ('sk2', 'EMBR', 'Embarcadero', true),
    ('sk3', 'POWL', 'Powell Street', true)
) as t(station_sk, station_code, station_name, is_current);

create table marts.dim_date as
select
    d as date_day,
    cast(extract(year from d) as bigint) as year,
    cast(extract(month from d) as bigint) as month,
    cast(strftime(d, '%V') as integer) as iso_week,
    dayofweek(d) not in (0, 6) as is_service_weekday
from (
    select cast(range as date) as d from range(date '2019-02-01', date '2019-03-01', interval 1 day)
    union all
    select cast(range as date) from range(date '2024-02-01', date '2024-03-02', interval 1 day)
    union all
    select cast(range as date) from range(date '2025-02-01', date '2025-03-01', interval 1 day)
);

create table marts.mart_kpis_daily as
select
    date_day as trip_date,
    dayofweek(date_day) + 1 as weekday,
    is_service_weekday,
    case year when 2025 then 1100 when 2024 then 1000 else 2000 end as total_entries,
    case when is_service_weekday then case year when 2025 then 0.5 when 2024 then 0.4 else 1.0 end end
        as recovery_ratio,
    case year when 2019 then 0.10 else 0.12 end as peak_hour_share,
    case when day(date_day) <= 20 then 'EMBR' else 'POWL' end as busiest_station,
    100 as busiest_station_entries,
    case when day(date_day) <= 20 then 0.08 else 0.07 end as busiest_station_share,
    null as rolling_28d_avg_entries,
    case year when 2025 then 1000 end as entries_364_days_earlier,
    case year when 2025 then 0.1 end as yoy_change
from marts.dim_date;

create table marts.mart_ridership_monthly as
select * from (values
    (date '2019-01-01', 31, 300000.0, 1.0),
    (date '2019-02-01', 28, 310000.0, 1.0),
    (date '2025-01-01', 31, 140000.0, 0.42),
    (date '2025-02-01', 28, 150000.0, 0.44)
) as t(month_start, days, avg_daily_entries, avg_service_weekday_recovery);

create table marts.fct_station_daily as
select date_day as trip_date, code as station_code,
    case when date_day = date '2025-02-28' and code = 'EMBR' then 6399 else 5000 end as entries,
    4000 as exits
from marts.dim_date, (values ('EMBR'), ('POWL')) as s(code)
where year = 2025;

create table marts.mart_recovery as
select trip_date, station_code, entries, 12000.0 as baseline_entries,
    case when station_code = 'EMBR' and trip_date = date '2025-02-28' then 0.52 else 0.4 end as recovery_ratio
from marts.fct_station_daily as f inner join marts.dim_date as d on f.trip_date = d.date_day
where d.is_service_weekday;

create table marts.mart_peak_load as
select * from (values ('EMBR', 17, 0.2, 9000.0, 1.0), ('POWL', 8, 0.15, 8000.0, 0.9))
    as t(station_code, peak_hour, peak_hour_share, avg_weekday_entries, busyness_percentile);

create table marts.mart_bikes_vs_trains as
select * from (values
    (date '2019-02-01', 9000000, 200000, 321428.6, 7142.9, 100.0, 100.0, 22.2),
    (date '2025-02-01', 4200000, 280000, 150000.0, 10000.0, 46.7, 140.0, 66.7)
) as t(month_start, bart_entries, bike_trips, bart_avg_daily_entries, bike_avg_daily_trips,
       bart_index_2019, bike_index_2019, bikes_per_1000_bart_entries);

create table marts.forecast_station_daily as
select 'run-1' as run_id, timestamp '2025-03-02 17:00:00' as generated_at, 'EMBR' as station_code,
    cast(date '2025-02-28' + to_days(cast(h as integer)) as date) as forecast_date, h as horizon_day,
    4000.0 + h as p10, 5000.0 + h as p50, 6000.0 + h as p90
from range(1, 15) as r(h);

create table ml.forecast_runs as
select 'run-1' as run_id, 410.5 as mae_lgbm, 520.25 as mae_baseline, 60.0 as mae_diff_lo, 160.0 as mae_diff_hi,
    0.62 as coverage_p10_p90;
"""


def _reset() -> None:
    get_settings.cache_clear()
    warehouse_mod._make.cache_clear()
    cache.clear()


def _build(path, *, forecasts: bool = True) -> None:
    con = duckdb.connect(str(path))
    con.execute(FIXTURE_SQL)
    if not forecasts:
        con.execute("drop table marts.forecast_station_daily; drop table ml.forecast_runs")
    con.close()


@pytest.fixture
def connect(tmp_path, monkeypatch):
    """Returns a function that builds a fixture warehouse and a TestClient reading it."""
    monkeypatch.delenv("TP_GCP_PROJECT", raising=False)

    def _connect(*, forecasts: bool = True) -> TestClient:
        path = tmp_path / ("wh.duckdb" if forecasts else "wh_noforecast.duckdb")
        _build(path, forecasts=forecasts)
        monkeypatch.setenv("TP_WAREHOUSE", "duckdb")
        monkeypatch.setenv("TP_DUCKDB_PATH", str(path))
        _reset()
        return TestClient(app)

    yield _connect
    _reset()


def test_endpoints_503_without_warehouse(monkeypatch):
    monkeypatch.delenv("TP_GCP_PROJECT", raising=False)
    monkeypatch.setenv("TP_WAREHOUSE", "none")
    _reset()
    try:
        client = TestClient(app)
        for path in [
            "/api/kpis",
            "/api/trends/ridership",
            "/api/trends/bikes-vs-trains",
            "/api/stations/EMBR/summary",
            "/api/stations/nope/summary",
            "/api/forecast/EMBR",
        ]:
            res = client.get(path)
            assert res.status_code == 503, path
            assert res.json()["detail"]["code"] == "warehouse_not_connected"
    finally:
        _reset()


def test_warehouse_setting_defaults():
    assert Settings(_env_file=None, warehouse=None, gcp_project=None).warehouse_kind == "none"
    assert Settings(_env_file=None, warehouse=None, gcp_project="p").warehouse_kind == "bigquery"
    assert Settings(_env_file=None, warehouse="duckdb", gcp_project="p").warehouse_kind == "duckdb"


def test_kpis_from_duckdb(connect):
    body = connect().get("/api/kpis").json()
    assert body["data_through"] == "2025-02-28"
    assert body["window"] == {"start": "2025-02-01", "end": "2025-02-28", "days": 28}
    tiles = {t["id"]: t for t in body["tiles"]}
    assert list(tiles) == ["recovery", "entries", "peak_share", "busiest_station"]
    assert tiles["recovery"]["value"] == pytest.approx(0.5)
    assert tiles["recovery"]["delta"] == pytest.approx(0.1)  # vs Feb 2024 (0.4)
    assert tiles["entries"]["value"] == pytest.approx(1100)
    assert tiles["entries"]["delta"] == pytest.approx(0.1)  # 1100 vs 1000
    assert tiles["peak_share"]["value"] == pytest.approx(0.12)
    assert tiles["peak_share"]["delta"] == pytest.approx(0.02)  # vs the same ISO weeks of 2019 (0.10)
    assert tiles["busiest_station"]["value"] == "Embarcadero"
    assert tiles["busiest_station"]["code"] == "EMBR"
    assert tiles["busiest_station"]["delta_label"] == "8.0% of all entries"
    for t in tiles.values():
        assert t["label"] and t["definition"]


ISO_WEEK_SQL = """
create schema marts;
create table marts.dim_station as select 'EMBR' as station_code, 'Embarcadero' as station_name, true as is_current;
create table marts.mart_kpis_daily as
select
    d as trip_date,
    dayofweek(d) not in (0, 6) as is_service_weekday,
    1000 as total_entries,
    0.5 as recovery_ratio,
    -- the baseline ISO year 2019 runs 2018-12-31 .. 2019-12-29; 2019-12-30/31 belong to ISO week 1 of 2020
    case when year(d) = 2025 then 0.12 when isoyear(d) = 2019 then 0.10 else 0.30 end as peak_hour_share,
    'EMBR' as busiest_station,
    0.08 as busiest_station_share,
    cast(null as bigint) as entries_364_days_earlier
from (
    select cast(range as date) as d from range(date '2018-12-24', date '2020-01-06', interval 1 day)
    union all
    select cast(range as date) from range(date '2025-12-04', date '2026-01-01', interval 1 day)
);
create table marts.dim_date as
select trip_date as date_day, year(trip_date) as year, cast(strftime(trip_date, '%V') as integer) as iso_week,
    isoyear(trip_date) as iso_year, is_service_weekday
from marts.mart_kpis_daily;
"""


def test_peak_share_delta_uses_iso_year_weeks(tmp_path, monkeypatch):
    # The window Dec 4-31, 2025 spans ISO weeks 49-52 of 2025 and week 1 of 2026. The baseline is the same ISO weeks
    # of ISO year 2019: Dec 2-29, 2019 and Dec 31, 2018 - Jan 4, 2019, not Dec 30-31, 2019 (calendar 2019, ISO 2020).
    path = tmp_path / "iso.duckdb"
    con = duckdb.connect(str(path))
    con.execute(ISO_WEEK_SQL)
    con.close()
    monkeypatch.delenv("TP_GCP_PROJECT", raising=False)
    monkeypatch.setenv("TP_WAREHOUSE", "duckdb")
    monkeypatch.setenv("TP_DUCKDB_PATH", str(path))
    _reset()
    try:
        body = TestClient(app).get("/api/kpis").json()
    finally:
        _reset()
    assert body["window"] == {"start": "2025-12-04", "end": "2025-12-31", "days": 28}
    tiles = {t["id"]: t for t in body["tiles"]}
    assert tiles["peak_share"]["value"] == pytest.approx(0.12)
    assert tiles["peak_share"]["delta"] == pytest.approx(0.02)  # baseline 0.10, no ISO-2020 day mixed in


def test_ridership_trend_from_duckdb(connect):
    body = connect().get("/api/trends/ridership").json()
    assert body["data_through"] == "2025-02-28"
    assert [r["month_start"] for r in body["rows"]] == [
        "2019-01-01",
        "2019-02-01",
        "2025-01-01",
        "2025-02-01",
    ]
    assert body["rows"][-1] == {
        "month_start": "2025-02-01",
        "days": 28,
        "avg_daily_entries": 150000.0,
        "avg_service_weekday_recovery": 0.44,
    }


def test_bikes_vs_trains_from_duckdb(connect):
    body = connect().get("/api/trends/bikes-vs-trains").json()
    assert len(body["rows"]) == 2
    assert body["rows"][1]["bike_index_2019"] == pytest.approx(140.0)
    assert body["rows"][1]["bart_avg_daily_entries"] == pytest.approx(150000.0)
    assert body["rows"][1]["bikes_per_1000_bart_entries"] == pytest.approx(66.7)
    assert "Bay Wheels" in body["source"]


def test_station_summary_from_duckdb(connect):
    body = connect().get("/api/stations/EMBR/summary").json()
    assert body["code"] == "EMBR"
    assert body["name"] == "Embarcadero"  # the current SCD2 version
    assert body["data_through"] == "2025-02-28"
    assert body["entries"] == 6399
    assert body["recovery_ratio"] == pytest.approx(0.52)
    # 20 service weekdays in Feb 2025: 19 × 5,000 + 6,399
    assert body["avg_weekday_entries_28d"] == pytest.approx((19 * 5000 + 6399) / 20)
    assert body["peak_hour"] == 17
    assert body["peak_hour_share"] == pytest.approx(0.2)


def test_unknown_station_is_404(connect):
    client = connect()
    for code in ["ZZZZ", "embr", "EMBRX", "EM'R"]:
        res = client.get(f"/api/stations/{code}/summary")
        assert res.status_code == 404, code
        assert res.json()["detail"]["code"] == "unknown_station"
    assert client.get("/api/forecast/ZZZZ").json()["detail"]["code"] == "unknown_station"


def test_forecast_from_duckdb(connect):
    body = connect().get("/api/forecast/EMBR").json()
    assert body["code"] == "EMBR"
    assert body["name"] == "Embarcadero"
    assert body["data_through"] == "2025-02-28"
    assert len(body["forecast"]) == 14
    assert body["forecast"][0] == {
        "date": "2025-03-01",
        "p10": 4001.0,
        "p50": 5001.0,
        "p90": 6001.0,
        "lo": 4001.0,
        "hi": 6001.0,
    }
    assert body["forecast"][-1]["date"] == "2025-03-14"
    assert (body["forecast_start"], body["forecast_end"]) == ("2025-03-01", "2025-03-14")
    assert len(body["actuals"]) == 28
    assert body["actuals"][-1] == {"date": "2025-02-28", "entries": 6399}
    assert body["model"] == {
        "mae": 410.5,
        "baseline_mae": 520.25,
        "mae_diff_ci": [60.0, 160.0],
        "interval_coverage": 0.62,
        "interval": {
            "method": "quantile (p10-p90)",
            "nominal": 0.8,
            "coverage": 0.62,
            "coverage_ci": None,
            "calibrated": False,
        },
    }
    assert body["generated_at"].startswith("2025-03-02T17:00")


# a run written since calibration: the forecast rows carry the published band, the run log how well it held
CALIBRATED_SQL = """
alter table marts.forecast_station_daily add column lower double;
alter table marts.forecast_station_daily add column upper double;
update marts.forecast_station_daily set lower = p10 - 500, upper = p90 + 700;
alter table ml.forecast_runs add column coverage_p10_p90_lo double;
alter table ml.forecast_runs add column coverage_p10_p90_hi double;
alter table ml.forecast_runs add column coverage_calibrated double;
alter table ml.forecast_runs add column coverage_calibrated_lo double;
alter table ml.forecast_runs add column coverage_calibrated_hi double;
alter table ml.forecast_runs add column interval_nominal double;
alter table ml.forecast_runs add column interval_method varchar;
alter table ml.forecast_runs add column calib_folds integer;
update ml.forecast_runs set coverage_p10_p90_lo = 0.6, coverage_p10_p90_hi = 0.64, coverage_calibrated = {cal},
    coverage_calibrated_lo = {cal} - 0.02, coverage_calibrated_hi = {cal} + 0.02, interval_nominal = 0.8,
    interval_method = 'split-conformal CQR, rolling 6 folds', calib_folds = 6;
"""


def _calibrate(path, cal: float) -> None:
    con = duckdb.connect(str(path))
    con.execute(CALIBRATED_SQL.format(cal=cal))
    con.close()


def test_forecast_reports_calibrated_interval(connect, tmp_path):
    client = connect()
    _calibrate(tmp_path / "wh.duckdb", 0.79)
    cache.clear()
    body = client.get("/api/forecast/EMBR").json()
    assert body["forecast"][0] == {
        "date": "2025-03-01",
        "p10": 4001.0,
        "p50": 5001.0,
        "p90": 6001.0,
        "lo": 3501.0,
        "hi": 6701.0,
    }
    assert body["model"]["interval_coverage"] == 0.62  # the raw p10-p90, as before
    interval = body["model"]["interval"]
    assert interval["calibrated"] is True
    assert interval["method"] == "split-conformal CQR, rolling 6 folds"
    assert interval["nominal"] == 0.8
    assert interval["coverage"] == pytest.approx(0.79)
    assert interval["coverage_ci"] == [pytest.approx(0.77), pytest.approx(0.81)]
    assert (body["forecast_start"], body["forecast_end"]) == ("2025-03-01", "2025-03-14")

    # a calibration that held the actual value less often than the raw band (vs 80%) isn't published
    con = duckdb.connect(str(tmp_path / "wh.duckdb"))
    con.execute("update ml.forecast_runs set coverage_calibrated = 0.99")
    con.close()
    cache.clear()
    body = client.get("/api/forecast/EMBR").json()
    assert body["model"]["interval"]["calibrated"] is False
    assert body["model"]["interval"]["coverage"] == 0.62
    assert body["model"]["interval"]["coverage_ci"] == [0.6, 0.64]
    assert (body["forecast"][0]["lo"], body["forecast"][0]["hi"]) == (4001.0, 6001.0)


def test_forecast_old_schema_falls_back_to_quantile_band(connect):
    # production keeps the pre-calibration tables until the weekly job runs the new code
    body = connect().get("/api/forecast/EMBR").json()
    assert all(f["lo"] == f["p10"] and f["hi"] == f["p90"] for f in body["forecast"])
    assert body["model"]["interval"] == {
        "method": "quantile (p10-p90)",
        "nominal": 0.8,
        "coverage": 0.62,
        "coverage_ci": None,
        "calibrated": False,
    }


def test_forecast_tolerates_missing_optional_run_columns(connect, tmp_path):
    client = connect()
    con = duckdb.connect(str(tmp_path / "wh.duckdb"))
    con.execute(
        "alter table ml.forecast_runs drop column mae_diff_lo; alter table ml.forecast_runs drop column mae_diff_hi"
    )
    con.close()
    cache.clear()
    res = client.get("/api/forecast/EMBR")
    assert res.status_code == 200
    model = res.json()["model"]
    assert model["mae_diff_ci"] is None
    assert (model["mae"], model["baseline_mae"], model["interval_coverage"]) == (410.5, 520.25, 0.62)


def test_forecast_missing_is_404(connect):
    res = connect().get("/api/forecast/POWL")  # a real station with no forecast rows
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "forecast_not_available"
    res = connect(forecasts=False).get("/api/forecast/EMBR")  # the forecast tables don't exist yet
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "forecast_not_available"


def test_cache_queries_warehouse_once(connect, monkeypatch):
    connect()
    real = warehouse_mod.get_warehouse()
    calls: list[str] = []

    class Counting:
        cache_key = real.cache_key

        def table(self, name, schema="marts"):
            return real.table(name, schema)

        def query(self, sql, params=None):
            calls.append(sql)
            return real.query(sql, params)

    monkeypatch.setattr(data_routes, "get_warehouse", lambda: Counting())
    client = TestClient(app)
    first = client.get("/api/kpis").json()
    n = len(calls)
    assert n > 0
    assert client.get("/api/kpis").json() == first
    assert len(calls) == n  # served from the cache
    client.get("/api/stations/EMBR/summary")
    m = len(calls)
    client.get("/api/stations/EMBR/summary")
    assert len(calls) == m

    # errors are not cached
    ttl = TTLCache()
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("warehouse hiccup")
        return 42

    with pytest.raises(RuntimeError):
        ttl.get_or_compute("k", 60, flaky)
    assert ttl.get_or_compute("k", 60, flaky) == 42
    assert ttl.get_or_compute("k", 60, flaky) == 42
    assert len(attempts) == 2


def test_bigquery_warehouse_uses_typed_params_and_byte_cap():
    from google.cloud import bigquery

    class FakeJob:
        def result(self):
            return [{"station_code": "EMBR", "entries": 6399}]

    class FakeClient:
        def __init__(self):
            self.calls = []

        def query(self, sql, job_config=None, location=None):
            self.calls.append((sql, job_config, location))
            return FakeJob()

    client = FakeClient()
    wh = BigQueryWarehouse("my-proj", client=client)
    assert wh.table("mart_kpis_daily") == "`my-proj.marts.mart_kpis_daily`"
    assert wh.table("forecast_runs", schema="ml") == "`my-proj.ml.forecast_runs`"

    rows = wh.query(
        "select * from t where c = @code and d = @day and n = @n and x = @x and b = @flag",
        {"code": "EMBR", "day": dt.date(2025, 12, 31), "n": 3, "x": 0.5, "flag": True},
    )
    assert rows == [{"station_code": "EMBR", "entries": 6399}]
    sql, config, location = client.calls[0]
    assert "@code" in sql  # BigQuery named parameters are passed through untouched
    assert location == "us-west1"
    assert isinstance(config, bigquery.QueryJobConfig)
    assert config.maximum_bytes_billed == BQ_MAX_BYTES_BILLED <= 100_000_000
    types = {p.name: (p.type_, p.value) for p in config.query_parameters}
    assert types == {
        "code": ("STRING", "EMBR"),
        "day": ("DATE", dt.date(2025, 12, 31)),
        "n": ("INT64", 3),
        "x": ("FLOAT64", 0.5),
        "flag": ("BOOL", True),
    }


def test_duckdb_warehouse_translates_named_params(tmp_path):
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema marts; create table marts.t as select 1 as a, 'x' as b")
    con.close()
    wh = DuckDBWarehouse(path)
    assert wh.query(f"select b from {wh.table('t')} where a = @a", {"a": 1}) == [{"b": "x"}]
