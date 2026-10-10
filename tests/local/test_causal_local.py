"""The eBART study's inputs against the real local warehouse (data/transitpulse.duckdb), marker `localdata`:

    uv run --group dbt --group ml pytest -m localdata tests/local/test_causal_local.py

They fail, rather than skip, when the warehouse is missing. Read-only; no estimates are computed here.
"""

import datetime as dt
from pathlib import Path

import duckdb
import pytest

from analysis.causal import design, monthly, panel

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "transitpulse.duckdb"

pytestmark = pytest.mark.localdata


@pytest.fixture(scope="module")
def con():
    assert DB.exists(), f"{DB} not found: build it with tasks.py dbt"
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def test_causal_committed_week_csv_equals_a_fresh_build(tmp_path):
    assert DB.exists(), f"{DB} not found"
    fresh = tmp_path / "station_week.csv"
    panel.write(panel.build(DB), fresh)
    assert fresh.read_bytes() == panel.WEEK_CSV.read_bytes().replace(b"\r\n", b"\n")


def test_causal_first_day_with_100_new_station_entries_is_the_opening(con):
    d = design.load()
    marks = ", ".join("?" for _ in d.new)
    first = con.execute(
        f"""
        select min(trip_date) from (
            select trip_date, sum(entries) as e from marts.fct_station_daily
            where station_code in ({marks}) group by 1
        ) where e >= 100
        """,
        list(d.new),
    ).fetchone()[0]
    assert first == d.event_date == dt.date(2018, 5, 26)


def test_causal_monthly_crosscheck_agrees_with_daily():
    res = monthly.crosscheck(DB)
    assert res["median_abs_pct_diff"] <= 5.0, res["median_abs_pct_diff"]


def test_causal_new_station_trips_are_recorded_through_to_their_destination(con):
    """eBART riders transfer at Pittsburg/Bay Point but the OD data records one trip from ANTC/PCTR to the final
    station, so few new-station trips end at PITT and the corridor sum doesn't count a transfer twice."""
    d = design.load()
    marks = ", ".join("?" for _ in d.new)
    total, to_pitt = con.execute(
        f"""
        select sum(trips), sum(trips) filter (where destination_code = ?)
        from staging.stg_bart_od
        where origin_code in ({marks}) and trip_date between ? and ?
        """,
        [d.treated[0], *d.new, d.week_zero, d.last_week + dt.timedelta(days=6)],
    ).fetchone()
    assert total > 1_000_000
    assert to_pitt / total < 0.05
