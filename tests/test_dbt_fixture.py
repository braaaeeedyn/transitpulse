"""`dbt build` (DuckDB target) end to end on a tiny generated dataset, so the models and their tests run in CI
without the real data: two weeks of BART origin-destination trips in Jan 2019 and Jan 2025 for three stations,
the GTFS station list, and Bay Wheels trips for the same days."""

from pathlib import Path

import duckdb
import pytest
from dbt_fixture_data import _write_fixture

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "dbt" / "transitpulse"


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
