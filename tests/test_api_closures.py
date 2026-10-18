"""GET /api/closures (api/routes/data.py) against a small DuckDB warehouse built in tmp_path with the columns of the
three closure marts (mart_station_closures, mart_closure_destinations, mart_closure_scenarios)."""

import duckdb
import pytest
from fastapi.testclient import TestClient

from api import warehouse as warehouse_mod
from api.cache import cache
from api.main import app
from api.routes import data as data_routes
from api.settings import get_settings
from pipeline import webexport

# 13 stations ranked 1..13 by weekday trips (100 x rank). Listed: S01, S05, S10, S11 (group 1) and S02, S12, S13
# (group 2). System recovery 0.4321 -> 43%. The rows sit on the rule edges: rank 10 vs 11, recovery 43% vs 42%,
# 2.9 vs 3.0 miles (2.95 rounds up to 3.0), and a station with no baseline (null recovery).
CLOSURES_SQL = """
create schema marts;

create table marts.mart_kpis_daily as select date '2025-12-31' as trip_date;

create table marts.mart_station_closures as
select code as station_code, 'Station ' || code as station_name, grp as closure_group, seg as closure_segment,
    2025 as period_year, 40.0 * r as avg_weekday_entries, 60.0 * r as avg_weekday_exits,
    100.0 * r as avg_weekday_trips, r as rank_lowest, 13 as stations_ranked, r / 1000.0 as share_of_weekday_trips,
    rec as recovery_ratio, 0.4321 as system_recovery_ratio, chg as change_vs_prev_year,
    'OPEN' as nearest_open_code, 'Open Station' as nearest_open_name, miles as nearest_open_miles
from (values
    ('S13', 13, 2, 'Line B', 0.50, 5.0, 0.10),
    ('S01', 1, 1, 'Line A', 0.20, 1.0, -0.05),
    ('S02', 2, 2, 'Line B', 0.60, 4.0, 0.02),
    ('S03', 3, null, null, 0.40, 1.0, 0.0),
    ('S04', 4, null, null, 0.40, 1.0, 0.0),
    ('S05', 5, 1, null, 0.4349, 2.94, 0.0004),
    ('S06', 6, null, null, 0.40, 1.0, 0.0),
    ('S07', 7, null, null, 0.40, 1.0, 0.0),
    ('S08', 8, null, null, 0.40, 1.0, 0.0),
    ('S09', 9, null, null, 0.40, 1.0, 0.0),
    ('S10', 10, 1, null, 0.4251, 2.9, 0.01),
    ('S11', 11, 1, 'Line A', 0.4249, 3.0, 0.03),
    ('S12', 12, 2, 'Line B', null, 2.95, null)
) as t(code, r, grp, seg, rec, miles, chg);

create table marts.mart_closure_destinations as
select * from (values
    ('S01', 'EMBR', 'Embarcadero', 2025, 30.0, 0.30, 1),
    ('S01', 'MONT', 'Montgomery Street', 2025, 20.0, 0.20, 2),
    ('S13', 'POWL', 'Powell Street', 2025, 50.0, 0.25, 1)
) as t(origin_code, destination_code, destination_name, period_year, avg_weekday_trips, share_of_origin_trips,
       destination_rank);

create table marts.mart_closure_scenarios as
select * from (values
    ('first_10', 4, 2025, 1260.0, 10000.0, 0.126),
    ('all_15', 7, 2025, 2410.0, 10000.0, 0.241)
) as t(scenario, stations, period_year, avg_weekday_trips_touching, system_avg_weekday_trips,
       share_of_weekday_trips);
"""


def _reset() -> None:
    get_settings.cache_clear()
    warehouse_mod._make.cache_clear()
    cache.clear()


@pytest.fixture
def connect(tmp_path, monkeypatch):
    """Returns a function that builds a warehouse (`sql` after the fixture) and a TestClient reading it."""
    monkeypatch.delenv("TP_GCP_PROJECT", raising=False)

    def _connect(sql: str = "", *, fixture: bool = True) -> TestClient:
        path = tmp_path / f"wh{len(list(tmp_path.iterdir()))}.duckdb"
        con = duckdb.connect(str(path))
        con.execute((CLOSURES_SQL if fixture else "create schema marts;") + sql)
        con.close()
        monkeypatch.setenv("TP_WAREHOUSE", "duckdb")
        monkeypatch.setenv("TP_DUCKDB_PATH", str(path))
        _reset()
        return TestClient(app)

    yield _connect
    _reset()


def _by_code(doc: dict) -> dict:
    return {s["code"]: s for s in doc["stations"]}


def test_closures_from_duckdb(connect):
    res = connect().get("/api/closures")
    assert res.status_code == 200
    doc = res.json()
    assert doc["period_year"] == 2025
    assert doc["baseline_year"] == 2019
    assert doc["data_through"] == "2025-12-31"
    assert doc["source"] == "BART hourly origin-destination ridership reports."
    assert [r["id"] for r in doc["rules"]] == ["riders", "recovery", "distance", "growing"]
    assert all(r["text"] for r in doc["rules"])
    assert "3.0 miles" in doc["rules"][2]["text"] and "10" in doc["rules"][0]["text"]
    assert set(doc["verdicts"]) == {"strong", "mixed", "weak"}

    # only the listed stations, by group, then by weekday trips (fewest first)
    assert [s["code"] for s in doc["stations"]] == ["S01", "S05", "S10", "S11", "S02", "S12", "S13"]
    s01 = _by_code(doc)["S01"]
    assert s01 == {
        "code": "S01",
        "name": "Station S01",
        "group": 1,
        "segment": "Line A",
        "weekday_trips": 100,
        "weekday_entries": 40,
        "weekday_exits": 60,
        "rank_lowest": 1,
        "share_of_trips": pytest.approx(0.001),
        "recovery_pct": 20,
        "change_vs_prev_year": pytest.approx(-0.05),
        "nearest_open": {"code": "OPEN", "name": "Open Station", "miles": 1.0},
        "destinations": [
            {"code": "EMBR", "name": "Embarcadero", "share": pytest.approx(0.30)},
            {"code": "MONT", "name": "Montgomery Street", "share": pytest.approx(0.20)},
        ],
        "criteria": {"riders": False, "recovery": False, "distance": False, "growing": False},
        "points": 0,
        "verdict": "weak",
    }
    assert _by_code(doc)["S05"]["segment"] is None
    assert _by_code(doc)["S05"]["destinations"] == []
    assert _by_code(doc)["S12"]["change_vs_prev_year"] is None


def test_closures_rule_edges(connect):
    st = _by_code(connect().get("/api/closures").json())
    assert data_routes.CLOSURE_LOWEST_N == 10 and data_routes.CLOSURE_MILES == 3.0
    # rank 10 is among the 10 least used (not met); rank 11 is above them (met)
    assert st["S10"]["criteria"]["riders"] is False
    assert st["S11"]["criteria"]["riders"] is True
    # recovery: 42.51% -> 43 equals the system's 43 (met); 42.49% -> 42 is one below (not met); 43.49% -> 43 (met)
    assert (st["S10"]["recovery_pct"], st["S10"]["criteria"]["recovery"]) == (43, True)
    assert (st["S11"]["recovery_pct"], st["S11"]["criteria"]["recovery"]) == (42, False)
    assert (st["S05"]["recovery_pct"], st["S05"]["criteria"]["recovery"]) == (43, True)
    # no baseline: null recovery, never met
    assert (st["S12"]["recovery_pct"], st["S12"]["criteria"]["recovery"]) == (None, False)
    # distance on the miles sent (1 decimal, half up): 2.9 not met, 3.0 met, 2.95 -> 3.0 met, 2.94 -> 2.9 not met
    assert (st["S10"]["nearest_open"]["miles"], st["S10"]["criteria"]["distance"]) == (2.9, False)
    assert (st["S11"]["nearest_open"]["miles"], st["S11"]["criteria"]["distance"]) == (3.0, True)
    assert (st["S12"]["nearest_open"]["miles"], st["S12"]["criteria"]["distance"]) == (3.0, True)
    assert (st["S05"]["nearest_open"]["miles"], st["S05"]["criteria"]["distance"]) == (2.9, False)
    # growing on the change rounded to 0.1%: -5% no, +0.04% -> 0.0 no, +1% yes, no prior year no
    assert st["S01"]["criteria"]["growing"] is False
    assert st["S05"]["criteria"]["growing"] is False
    assert st["S10"]["criteria"]["growing"] is True
    assert st["S12"]["criteria"]["growing"] is False
    # points -> verdict
    for s in st.values():
        assert s["points"] == sum(s["criteria"].values())
        assert s["verdict"] == {4: "strong", 3: "strong", 2: "mixed"}.get(s["points"], "weak")
    assert {c: st[c]["verdict"] for c in st} == {
        "S01": "weak",  # 0 points
        "S05": "weak",  # recovery only
        "S10": "mixed",  # recovery + growing
        "S11": "strong",  # riders + distance + growing
        "S02": "strong",  # recovery + distance + growing
        "S12": "mixed",  # riders + distance
        "S13": "strong",  # all four
    }
    assert [data_routes.closure_verdict(p) for p in range(5)] == ["weak", "weak", "mixed", "strong", "strong"]
    assert data_routes.closure_criteria(11, None, 43, None) == {
        "riders": True,
        "recovery": False,
        "distance": False,
        "growing": False,
    }
    assert data_routes.closure_criteria(10, 43, None, 3.0)["recovery"] is False


def test_closures_system_block(connect):
    system = connect().get("/api/closures").json()["system"]
    assert system["stations"] == 13
    assert system["recovery_pct"] == 43
    assert system["share_first_10"] == pytest.approx(0.126)
    assert system["share_all_15"] == pytest.approx(0.241)
    # the 10 least used across every station, listed or not, fewest first
    assert [s["code"] for s in system["lowest_10"]] == [f"S{i:02d}" for i in range(1, 11)]
    assert {s["code"] for s in system["lowest_10"] if s["listed"]} == {"S01", "S02", "S05", "S10"}
    assert system["lowest_10"][0] == {"code": "S01", "name": "Station S01", "listed": True}
    # group 1 only: S02 is listed but in group 2, S11 is group 1 but ranked 11th
    assert system["first_10_in_lowest_10"] == 3


def test_closures_503_without_warehouse(monkeypatch):
    monkeypatch.delenv("TP_GCP_PROJECT", raising=False)
    monkeypatch.setenv("TP_WAREHOUSE", "none")
    _reset()
    try:
        res = TestClient(app).get("/api/closures")
        assert res.status_code == 503
        assert res.json()["detail"]["code"] == "warehouse_not_connected"
    finally:
        _reset()


def test_closures_404_before_the_marts_are_built(connect):
    # the marts don't exist yet (e.g. BigQuery before the VM's dbt build)
    res = connect(
        "create table marts.mart_kpis_daily as select date '2025-12-31' as trip_date;", fixture=False
    ).get("/api/closures")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "data_not_available"
    # the marts exist but no listed station has data (the CI fixture's case)
    res = connect("update marts.mart_station_closures set closure_group = null;").get("/api/closures")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "data_not_available"


def test_closures_cached(connect, monkeypatch):
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
    first = client.get("/api/closures").json()
    n = len(calls)
    assert n > 0
    assert client.get("/api/closures").json() == first
    assert len(calls) == n  # served from the cache


def test_closures_in_static_export_paths():
    assert "api/closures" in webexport._paths({"stations": [{"code": "EMBR"}]})
