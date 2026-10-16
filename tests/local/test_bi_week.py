"""The BI guide's check week (bi/README.md): its KPI values, recomputed from the local warehouse, appear in the guide
exactly as written. Marker `localdata` (needs data/transitpulse.duckdb)."""

import re
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "transitpulse.duckdb"
GUIDE = ROOT / "bi" / "README.md"

pytestmark = pytest.mark.localdata

WEEK = "from marts.mart_kpis_daily as k join marts.dim_date as d on d.date_day = k.trip_date where d.iso_year = ? and d.iso_week = ?"


def test_bi_check_week_values_match_the_warehouse():
    text = GUIDE.read_text(encoding="utf-8")
    m = re.search(r"Check week: \*\*ISO week (\d{4})-W(\d{2})\*\*", text)
    assert m, "bi/README.md must name the check week as 'Check week: **ISO week YYYY-Www**'"
    week = [int(m.group(1)), int(m.group(2))]
    assert DB.exists(), f"{DB} not found: build it with tasks.py dbt"
    con = duckdb.connect(str(DB), read_only=True)
    try:
        days, holidays, total, recovery, peak = con.execute(
            "select count(*), count(*) filter (where d.is_holiday), sum(k.total_entries), "
            "avg(k.recovery_ratio) filter (where k.is_service_weekday), "
            f"avg(k.peak_hour_share) filter (where k.is_service_weekday) {WEEK}",
            week,
        ).fetchone()
        busiest = con.execute(
            "select s.station_name, count(*) as days, avg(k.busiest_station_share) "
            f"{WEEK.replace(' where ', ' join marts.dim_station as s on s.station_code = k.busiest_station and s.is_current where ')} "
            "group by 1 order by days desc, 1",
            week,
        ).fetchall()
    finally:
        con.close()
    assert week[0] == 2025 and days == 7 and holidays == 0, "a full 2025 week with no holiday"
    name, n_days, share = busiest[0]
    assert len(busiest) == 1 or busiest[1][1] < n_days, "the busiest station must not be a tie"
    for value in (
        f"{total:,}",
        f"{recovery:.4f}",
        f"{peak:.4f}",
        name,
        f"{n_days} of 7 days",
        f"{share:.4f}",
    ):
        assert value in text, value
