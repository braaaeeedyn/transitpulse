"""Regression tests for dbt model bugs, on a tiny generated dataset built twice into one DuckDB file:

  build 1: December 2025 only (a full build, so fct_trips_hourly is created from scratch)
  build 2: the same files plus older days (2018-12-31, 2019-01-02..04, 2019-12-30..31), run incrementally

The second build is how a backfill looks in real life: an older year loaded after a newer one.
"""

import csv
import datetime as dt
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "dbt" / "transitpulse"
STATIONS = [("EMBR", "Embarcadero", 37.7929, -122.3971), ("MONT", "Montgomery Street", 37.7894, -122.4011),
            ("POWL", "Powell Street", 37.7844, -122.4079)]  # fmt: skip

FIRST_LOAD = [dt.date(2025, 12, 1) + dt.timedelta(days=i) for i in range(31)]
BACKFILL = [
    dt.date(2018, 12, 31),
    dt.date(2019, 1, 2),
    dt.date(2019, 1, 3),
    dt.date(2019, 1, 4),
    dt.date(2019, 12, 30),
    dt.date(2019, 12, 31),
]


def _write_days(data_root: Path, days: list[dt.date], batch: str) -> None:
    """One Parquet file per month and batch, in the hive layout Spark writes (year=YYYY/month=M)."""
    codes = ", ".join(f"('{c}')" for c, *_ in STATIONS)
    con = duckdb.connect()
    try:
        for year, month in sorted({(d.year, d.month) for d in days}):
            dates = ", ".join(f"(date '{d}')" for d in days if (d.year, d.month) == (year, month))
            od_dir = data_root / "bart_od" / f"year={year}" / f"month={month}"
            od_dir.mkdir(parents=True, exist_ok=True)
            # every ordered pair of stations, hours 7, 8 and 17; trips vary by day so averages are checkable
            con.execute(
                f"""copy (
                    select d as trip_date, h as hour, o.code as origin, x.code as destination,
                        day(d) + 1 as trips,
                        dayofweek(d) + 1 as weekday, false as is_holiday, cast(null as varchar) as holiday
                    from (values {dates}) as days(d), (values (7), (8), (17)) as hours(h),
                         (values {codes}) as o(code), (values {codes}) as x(code)
                    where o.code != x.code
                ) to '{(od_dir / f"{batch}.parquet").as_posix()}' (format parquet)"""
            )
            bikes_dir = data_root / "baywheels_trips" / f"year={year}" / f"month={month}"
            bikes_dir.mkdir(parents=True, exist_ok=True)
            con.execute(
                f"""copy (
                    select
                        md5(cast(d as varchar) || '-' || cast(n as varchar)) as ride_id,
                        cast(d as timestamp) + interval 8 hour + to_minutes(cast(n as integer)) as started_at,
                        cast(d as timestamp) + interval 8 hour + to_minutes(cast(n as integer) + 12) as ended_at,
                        720.0 as duration_sec,
                        'SF-1' as start_station_id, 'Market St' as start_station_name,
                        'SF-2' as end_station_id, 'Mission St' as end_station_name,
                        37.78 as start_lat, -122.41 as start_lng, 37.79 as end_lat, -122.40 as end_lng,
                        'classic_bike' as rideable_type, 'member' as member_type,
                        d as trip_date,
                        strftime(d, '%Y%m') || '-baywheels-tripdata.csv.zip' as source_file,
                        'lyft' as schema_version
                    from (values {dates}) as days(d), range(0, 2) as r(n)
                ) to '{(bikes_dir / f"{batch}.parquet").as_posix()}' (format parquet)"""
            )
    finally:
        con.close()


def _write_stations(data_root: Path) -> None:
    stations_dir = data_root / "bart_stations"
    stations_dir.mkdir(parents=True)
    with (stations_dir / "stations.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["station_code", "station_name", "lat", "lon", "feed_version", "observed_at"])
        for code, name, lat, lon in STATIONS:
            w.writerow([code, name, lat, lon, "72", "2026-10-08 00:00:00"])


def _dbt_build(tmp: Path) -> None:
    from dbt.cli.main import dbtRunner

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
    assert res.success, failures or res.exception
    assert not failures


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dbt_regressions")
    data_root = tmp / "parquet"
    db = tmp / "regressions.duckdb"
    mp = pytest.MonkeyPatch()
    mp.setenv("DBT_TARGET", "local")
    mp.setenv("TP_DATA_ROOT", data_root.as_posix())
    mp.setenv("TP_DUCKDB_PATH", db.as_posix())
    mp.setenv("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    try:
        _write_stations(data_root)
        _write_days(data_root, FIRST_LOAD, "batch1")
        _dbt_build(tmp)
        con = duckdb.connect(str(db))  # same config as dbt-duckdb's open in-process connection
        first = {
            r[0] for r in con.execute("select distinct trip_date from marts.fct_trips_hourly").fetchall()
        }
        con.close()
        assert first == set(FIRST_LOAD)

        _write_days(data_root, BACKFILL, "batch2")
        _dbt_build(tmp)  # fct_trips_hourly exists now, so this run is incremental
        con = duckdb.connect(str(db))  # same config as dbt-duckdb's open in-process connection
        yield con
        con.close()
    finally:
        mp.undo()


def test_incremental_fact_loads_backfilled_older_dates(warehouse):
    loaded = {
        r[0] for r in warehouse.execute("select distinct trip_date from marts.fct_trips_hourly").fetchall()
    }
    assert loaded == set(FIRST_LOAD) | set(BACKFILL)
    # the backfilled days carry their own trips (3 stations x 2 destinations x 3 hours x (day + 1))
    per_day = dict(
        warehouse.execute(
            "select trip_date, sum(entries) from marts.fct_station_daily group by 1 order by 1"
        ).fetchall()
    )
    for d in BACKFILL:
        assert per_day[d] == 18 * (d.day + 1), d
    # nothing was loaded twice
    (dupes,) = warehouse.execute(
        "select count(*) from (select trip_date, trip_hour, origin_code, destination_code from "
        "marts.fct_trips_hourly group by all having count(*) > 1)"
    ).fetchone()
    assert dupes == 0


def test_recovery_baseline_uses_iso_year_2019(warehouse):
    # ISO week 1 of 2019 is 2018-12-31 .. 2019-01-06; 2019-12-30/31 are ISO week 1 of 2020. Each station's
    # entries on day d are 2 destinations x 3 hours x (day(d) + 1) = 6 * (day + 1); the system's are 18 * (day + 1).
    week1 = [dt.date(2018, 12, 31), dt.date(2019, 1, 2), dt.date(2019, 1, 3), dt.date(2019, 1, 4)]
    station_base = sum(6 * (d.day + 1) for d in week1) / len(week1)  # 66
    system_base = sum(18 * (d.day + 1) for d in week1) / len(week1)  # 198

    # 2025-12-29..31 are ISO week 1 of 2026, so their baseline is ISO week 1 of 2019
    rows = warehouse.execute(
        "select trip_date, station_code, entries, baseline_entries, recovery_ratio from marts.mart_recovery "
        "where trip_date between date '2025-12-29' and date '2025-12-31' order by 1, 2"
    ).fetchall()
    assert len(rows) == 9
    for day, code, entries, baseline, ratio in rows:
        assert baseline == pytest.approx(station_base), (day, code)
        assert ratio == pytest.approx(entries / station_base), (day, code)

    # baseline-year days (ISO 2019) are not outputs; 2019-12-30 is (ISO 2020) and compares with ISO week 1 of 2019
    out = {r[0] for r in warehouse.execute("select distinct trip_date from marts.mart_recovery").fetchall()}
    assert not out & set(week1)
    assert dt.date(2019, 12, 30) in out

    kpis = dict(
        warehouse.execute(
            "select trip_date, recovery_ratio from marts.mart_kpis_daily where trip_date >= date '2025-12-29'"
        ).fetchall()
    )
    for d in (dt.date(2025, 12, 29), dt.date(2025, 12, 30), dt.date(2025, 12, 31)):
        assert kpis[d] == pytest.approx(18 * (d.day + 1) / system_base), d

    (iso_year,) = warehouse.execute(
        "select iso_year from marts.dim_date where date_day = date '2019-12-30'"
    ).fetchone()
    assert iso_year == 2020


def test_rolling_28d_average_ignores_gaps(warehouse):
    # the 28-day window is calendar days [d - 27, d]: Dec 1, 2025 has no loaded day in the 27 before it, so its
    # average is its own total, not one mixed with the 2019 days that happen to be the previous rows
    rows = {
        r[0]: (r[1], r[2])
        for r in warehouse.execute(
            "select trip_date, rolling_28d_avg_entries, rolling_28d_days from marts.mart_kpis_daily"
        ).fetchall()
    }
    assert rows[dt.date(2025, 12, 1)] == (pytest.approx(18 * 2), 1)
    # 2019-01-04: 2018-12-31 and 2019-01-02..04 are inside [2018-12-08, 2019-01-04]
    four = [32, 3, 4, 5]
    assert rows[dt.date(2019, 1, 4)] == (pytest.approx(sum(18 * n for n in four) / 4), 4)
    # 2025-12-28: Dec 1..28 is a full window
    assert rows[dt.date(2025, 12, 28)] == (pytest.approx(sum(18 * (n + 1) for n in range(1, 29)) / 28), 28)
