"""`dbt build` (DuckDB target) end to end on a tiny generated dataset, so the models and their tests run in CI
without the real data: two weeks of BART origin-destination trips in Jan 2019 and Jan 2025 for three stations,
the GTFS station list, and Bay Wheels trips for the same days."""

import csv
from pathlib import Path

import duckdb
import pytest

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


def test_dbt_build_on_fixture(tmp_path, monkeypatch):
    from dbt.cli.main import dbtRunner

    data_root = tmp_path / "parquet"
    _write_fixture(data_root)
    db = tmp_path / "fixture.duckdb"
    monkeypatch.setenv("DBT_TARGET", "local")
    monkeypatch.setenv("TP_DATA_ROOT", data_root.as_posix())
    monkeypatch.setenv("TP_DUCKDB_PATH", db.as_posix())
    # dbt writes .user.yml next to the profiles; keep the project dir clean
    monkeypatch.setenv("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")

    args = [
        "build",
        "--project-dir", str(PROJECT),
        "--profiles-dir", str(PROJECT),
        "--target-path", str(tmp_path / "target"),
        "--log-path", str(tmp_path / "logs"),
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

    con = duckdb.connect(str(db))
    try:
        q = lambda sql: con.execute(sql).fetchall()  # noqa: E731

        # Bay Wheels daily fact: 14 days a year, 4 trips/day in 2019 and 8 in 2025, one dockless trip a day
        assert q(
            "select extract(year from trip_date), count(*), sum(trips), sum(dockless_trips), sum(ebike_trips), "
            "sum(unknown_type_trips) from marts.fct_bike_trips_daily group by 1 order by 1"
        ) == [(2019, 14, 56, 14, 0, 56), (2025, 14, 112, 14, 56, 0)]

        # bikes vs trains: BART 180 entries/day in 2019 vs 90 in 2025 (index 50); bikes 4 vs 8 a day (index 200)
        rows = q(
            "select month_start, bart_entries, bike_trips, bart_avg_daily_entries, bike_avg_daily_trips, "
            "bart_index_2019, bike_index_2019, bikes_per_1000_bart_entries "
            "from marts.mart_bikes_vs_trains order by month_start"
        )
        assert [str(r[0]) for r in rows] == ["2019-01-01", "2025-01-01"]
        assert rows[0][1:7] == (2520, 56, 180.0, 4.0, 100.0, 100.0)
        assert rows[1][1:7] == (1260, 112, 90.0, 8.0, 50.0, 200.0)
        assert rows[0][7] == pytest.approx(1000 * 56 / 2520)

        # the website's monthly series
        monthly = q(
            "select month_start, days, avg_daily_entries, avg_service_weekday_recovery "
            "from marts.mart_ridership_monthly order by month_start"
        )
        assert [(str(m), d, e) for m, d, e, _ in monthly] == [
            ("2019-01-01", 14, 180.0),
            ("2025-01-01", 14, 90.0),
        ]
        assert monthly[0][3] == pytest.approx(1.0)
        assert monthly[1][3] == pytest.approx(0.5)
    finally:
        con.close()
