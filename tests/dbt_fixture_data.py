"""The tiny generated dataset test_dbt_fixture.py builds with dbt (two weeks of BART origin-destination trips in Jan 2019
and Jan 2025 for three stations, the GTFS station list, and Bay Wheels trips for the same days), plus
build_fixture_warehouse(), which builds it once into a DuckDB file for the agent tests and adds a small synthetic
forecast (dbt doesn't build the forecast tables; the weekly ML job writes them)."""

import csv
import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "dbt" / "transitpulse"

STATIONS = [("EMBR", "Embarcadero", 37.7929, -122.3971), ("MONT", "Montgomery Street", 37.7894, -122.4011),
            ("POWL", "Powell Street", 37.7844, -122.4079)]  # fmt: skip


def _write_fixture(data_root: Path) -> None:
    codes = ", ".join(f"('{c}')" for c, *_ in STATIONS)
    data_root.mkdir(parents=True)
    con = duckdb.connect()
    od_dir = (data_root / "bart_od").as_posix()
    # every ordered pair of stations, hours 7, 8 and 17: 10 trips each in 2019, 5 in 2025
    con.execute(
        f"""copy (
            select d as trip_date, h as hour, o.code as origin, x.code as destination,
                case when year(d) = 2019 then 10 else 5 end as trips,
                dayofweek(d) + 1 as weekday, false as is_holiday, cast(null as varchar) as holiday,
                year(d) as year, month(d) as month
            from (select cast(range as date) as d from range(date '2019-01-07', date '2019-01-21', interval 1 day)
                  union all
                  select cast(range as date) from range(date '2025-01-06', date '2025-01-20', interval 1 day)) as days,
                 (values (7), (8), (17)) as hours(h),
                 (values {codes}) as o(code), (values {codes}) as x(code)
            where o.code != x.code
        ) to '{od_dir}' (format parquet, partition_by (year, month))"""
    )
    bikes_dir = (data_root / "baywheels_trips").as_posix()
    # 4 trips a day in 2019, 8 in 2025; one trip a day is dockless
    con.execute(
        f"""copy (
            select
                md5(cast(d as varchar) || '-' || cast(n as varchar)) as ride_id,
                cast(d as timestamp) + interval 8 hour + to_minutes(cast(n as integer)) as started_at,
                cast(d as timestamp) + interval 8 hour + to_minutes(cast(n as integer) + 12) as ended_at,
                720.0 as duration_sec,
                case when n = 0 then null else 'SF-1' end as start_station_id,
                case when n = 0 then null else 'Market St' end as start_station_name,
                'SF-2' as end_station_id, 'Mission St' as end_station_name,
                37.78 as start_lat, -122.41 as start_lng, 37.79 as end_lat, -122.40 as end_lng,
                case when year(d) = 2019 then 'unknown' when n % 2 = 0 then 'electric_bike' else 'classic_bike' end
                    as rideable_type,
                case when n % 4 = 0 then 'casual' else 'member' end as member_type,
                d as trip_date,
                strftime(d, '%Y%m') || '-baywheels-tripdata.csv.zip' as source_file,
                case when year(d) = 2019 then 'legacy' else 'lyft' end as schema_version,
                year(d) as year, month(d) as month
            from (select cast(range as date) as d from range(date '2019-01-07', date '2019-01-21', interval 1 day)
                  union all
                  select cast(range as date) from range(date '2025-01-06', date '2025-01-20', interval 1 day)) as days,
                 range(0, 8) as r(n)
            where n < case when year(d) = 2019 then 4 else 8 end
        ) to '{bikes_dir}' (format parquet, partition_by (year, month))"""
    )
    con.close()
    stations_dir = data_root / "bart_stations"
    stations_dir.mkdir(parents=True)
    with (stations_dir / "stations.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["station_code", "station_name", "lat", "lon", "feed_version", "observed_at"])
        for code, name, lat, lon in STATIONS:
            w.writerow([code, name, lat, lon, "72", "2026-10-08 00:00:00"])


def _dbt_build(tmp: Path, data_root: Path, db: Path) -> None:
    from dbt.cli.main import dbtRunner

    env = {
        "DBT_TARGET": "local",
        "TP_DATA_ROOT": data_root.as_posix(),
        "TP_DUCKDB_PATH": db.as_posix(),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        args = [
            "build",
            "--project-dir", str(PROJECT),
            "--profiles-dir", str(PROJECT),
            "--target-path", str(tmp / "target"),
            "--log-path", str(tmp / "logs"),
            "--no-partial-parse",
        ]  # fmt: skip
        res = dbtRunner().invoke(args)
        failures = [
            f"{r.node.unique_id}: {r.status} {r.message}"
            for r in (res.result or [])
            if str(r.status) not in ("success", "pass")
        ]
        assert res.success and not failures, failures or res.exception
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


FORECAST_SQL = """
create schema if not exists ml;
create table marts.forecast_station_daily as
select 'fc-fixture' as run_id, timestamp '2025-01-20 17:00:00+00' as generated_at, s.code as station_code,
    cast(date '2025-01-19' + to_days(cast(h as integer)) as date) as forecast_date, h as horizon_day,
    80.0 + h as p10, 90.0 + h as p50, 100.0 + h as p90, 75.0 + h as lower, 105.0 + h as upper
from range(1, 15) as r(h), (values ('EMBR'), ('MONT'), ('POWL')) as s(code);
create table ml.forecast_runs as
select 'fc-fixture' as run_id, timestamp '2025-01-20 17:00:00+00' as generated_at, date '2025-01-19' as data_through,
    date '2025-01-20' as forecast_start, 12.5 as mae_lgbm, 20.0 as mae_baseline, 0.71 as coverage_p10_p90,
    0.78 as coverage_calibrated;
"""


def build_fixture_warehouse(tmp: Path) -> Path:
    """Generate the fixture data under tmp, `dbt build` it into tmp/fixture.duckdb, add the synthetic forecast."""
    data_root = tmp / "parquet"
    _write_fixture(data_root)
    db = tmp / "fixture.duckdb"
    _dbt_build(tmp, data_root, db)
    con = duckdb.connect(str(db))
    try:
        con.execute(FORECAST_SQL)
    finally:
        con.close()
    return db
