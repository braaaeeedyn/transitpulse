"""The station-closures marts, GET /api/closures and docs/STATION_CLOSURES.md on the real local warehouse, after

    DBT_TARGET=local uv run --group dbt dbt build --select bart_closure_candidates+ --project-dir dbt/transitpulse \
        --profiles-dir dbt/transitpulse

Marker `localdata` (not in the default run). The independent check recomputes the marts' numbers from the core
facts in Python, without the mart SQL."""

import csv
import math
import re
from collections import defaultdict
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "transitpulse.duckdb"
SEED = ROOT / "dbt" / "transitpulse" / "seeds" / "bart_closure_candidates.csv"
DOC = ROOT / "docs" / "STATION_CLOSURES.md"

pytestmark = pytest.mark.localdata

# as reported from BART staff's February 2026 presentation (.loop/research.md)
FIRST_10 = ["CAST", "NCON", "OAKL", "ORIN", "PCTR", "SBRN", "SHAY", "SSAN", "WARM", "WDUB"]
NEXT_5 = ["COLM", "MLBR", "DUBL", "PITT", "ANTC"]
EVIDENCE = ["avg_weekday_trips", "rank_lowest", "share_of_weekday_trips", "baseline_avg_weekday_trips",
            "recovery_ratio", "prev_year_avg_weekday_trips", "change_vs_prev_year", "nearest_open_code",
            "nearest_open_name", "nearest_open_miles"]  # fmt: skip


@pytest.fixture(scope="module")
def con():
    assert DB.exists(), f"{DB} not found: build it with tasks.py dbt"
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def _rows(con, sql, params=None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


@pytest.fixture
def api(monkeypatch):
    from api import warehouse
    from api.cache import cache
    from api.main import app
    from api.settings import get_settings

    def reset():
        get_settings.cache_clear()
        warehouse._make.cache_clear()
        cache.clear()

    monkeypatch.setenv("TP_WAREHOUSE", "duckdb")
    monkeypatch.setenv("TP_DUCKDB_PATH", str(DB))
    reset()
    yield TestClient(app)
    reset()


def test_closures_mart_has_the_15_stations(con):
    rows = _rows(con, "select * from marts.mart_station_closures")
    listed = {r["station_code"]: r for r in rows if r["closure_group"] is not None}
    assert {c: r["closure_group"] for c, r in listed.items()} == {
        **dict.fromkeys(FIRST_10, 1),
        **dict.fromkeys(NEXT_5, 2),
    }
    assert {r["period_year"] for r in rows} == {2025}
    for code, r in listed.items():
        missing = [c for c in EVIDENCE if r[c] is None]
        assert not missing, (code, missing)
    assert 48 <= len(rows) <= 52, len(rows)
    assert {r["stations_ranked"] for r in rows} == {len(rows)}
    assert sorted(r["rank_lowest"] for r in rows)[0] == 1
    # opened in 2020: no 2019 baseline
    by_code = {r["station_code"]: r for r in rows}
    assert by_code["MLPT"]["recovery_ratio"] is None and by_code["BERY"]["recovery_ratio"] is None
    # the nearest open station is never a listed one
    assert not {r["nearest_open_code"] for r in rows} & set(listed)
    dests = _rows(con, "select * from marts.mart_closure_destinations")
    assert {d["origin_code"] for d in dests} == set(listed)
    assert sorted(d["destination_rank"] for d in dests) == sorted([1, 2, 3] * 15)
    scenarios = {s["scenario"]: s for s in _rows(con, "select * from marts.mart_closure_scenarios")}
    assert set(scenarios) == {"first_10", "all_15"}
    assert (scenarios["first_10"]["stations"], scenarios["all_15"]["stations"]) == (10, 15)


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 3958.8 * math.asin(math.sqrt(a))


def test_closures_mart_matches_an_independent_computation(con):
    (last_day,) = con.execute("select max(trip_date) from marts.fct_station_daily").fetchone()
    year = last_day.year if (last_day.month, last_day.day) == (12, 31) else last_day.year - 1
    service = {
        d
        for (d,) in con.execute(
            "select date_day from marts.dim_date where is_service_weekday and year in (?, ?, 2019)",
            [year, year - 1],
        ).fetchall()
    }
    daily = con.execute(
        "select trip_date, station_code, entries, exits from marts.fct_station_daily "
        "where extract(year from trip_date) in (?, ?, 2019)",
        [year, year - 1],
    ).fetchall()
    trips = defaultdict(list)  # (station, year) -> [entries + exits per service weekday]
    system = defaultdict(lambda: defaultdict(int))  # year -> day -> entries
    for d, code, entries, exits in daily:
        if d in service:
            trips[code, d.year].append(entries + exits)
            system[d.year][d] += entries
    avg = {k: sum(v) / len(v) for k, v in trips.items()}
    sys_avg = {y: sum(days.values()) / len(days) for y, days in system.items()}
    codes = sorted(c for c, y in trips if y == year)
    ordered = sorted(codes, key=lambda c: avg[c, year])

    with SEED.open(encoding="utf-8") as f:
        seed = {r["station_code"]: int(r["closure_group"]) for r in csv.DictReader(f)}
    stations = {
        code: (lat, lon)
        for code, lat, lon in con.execute(
            "select station_code, lat, lon from marts.dim_station where is_current"
        ).fetchall()
    }

    mart = {r["station_code"]: r for r in _rows(con, "select * from marts.mart_station_closures")}
    assert set(mart) == set(codes)
    approx = lambda v: pytest.approx(v, rel=1e-9)  # noqa: E731
    for code in codes:
        r = mart[code]
        assert r["period_year"] == year
        assert r["avg_weekday_trips"] == approx(avg[code, year]), code
        assert r["rank_lowest"] == 1 + sum(avg[c, year] < avg[code, year] for c in codes), code
        assert r["share_of_weekday_trips"] == approx(avg[code, year] / sys_avg[year]), code
        base = avg.get((code, 2019)) if len(trips.get((code, 2019), [])) >= 200 else None
        assert (r["recovery_ratio"] is None) == (base is None), code
        if base is not None:
            assert r["recovery_ratio"] == approx(avg[code, year] / base), code
        assert r["system_recovery_ratio"] == approx(sys_avg[year] / sys_avg[2019])
        assert r["change_vs_prev_year"] == approx(avg[code, year] / avg[code, year - 1] - 1), code
        lat, lon = stations[code]
        nearest = min(
            (_haversine_miles(lat, lon, *stations[o]), o) for o in stations if o not in seed and o != code
        )
        assert r["nearest_open_code"] == nearest[1], code
        assert r["nearest_open_miles"] == pytest.approx(nearest[0], abs=1e-6), code
    assert ordered[0] == min(codes, key=lambda c: mart[c]["rank_lowest"])

    # top destination of each listed station: most service-weekday trips to another station in the period year
    pairs = con.execute(
        "select t.origin_code, t.destination_code, sum(t.trips) from marts.fct_trips_hourly as t "
        "inner join marts.dim_date as d on t.trip_date = d.date_day "
        "where d.is_service_weekday and d.year = ? group by 1, 2",
        [year],
    ).fetchall()
    first_10 = {c for c, g in seed.items() if g == 1}
    total = sum(n for _, _, n in pairs)
    touching_10 = sum(n for o, x, n in pairs if o in first_10 or x in first_10)
    touching_15 = sum(n for o, x, n in pairs if o in seed or x in seed)
    firsts = {
        r["origin_code"]: r
        for r in _rows(con, "select * from marts.mart_closure_destinations where destination_rank = 1")
    }
    assert set(firsts) == set(seed)
    for code in seed:
        out = {x: n for o, x, n in pairs if o == code and x != code}
        best = min(out, key=lambda x: (-out[x], x))
        assert firsts[code]["destination_code"] == best, code
        origin_total = sum(n for o, _, n in pairs if o == code)
        assert firsts[code]["share_of_origin_trips"] == approx(out[best] / origin_total), code
    scen = {
        s["scenario"]: s["share_of_weekday_trips"]
        for s in _rows(con, "select * from marts.mart_closure_scenarios")
    }
    assert scen["first_10"] == approx(touching_10 / total)
    assert scen["all_15"] == approx(touching_15 / total)


def test_closures_api_on_local_data(api):
    res = api.get("/api/closures")
    assert res.status_code == 200
    doc = res.json()
    stations = doc["stations"]
    assert len(stations) == 15
    assert [s["group"] for s in stations] == [1] * 10 + [2] * 5
    assert {s["code"] for s in stations} == set(FIRST_10 + NEXT_5)
    for s in stations:
        assert s["points"] == sum(s["criteria"].values()), s["code"]
        assert s["verdict"] == {4: "strong", 3: "strong", 2: "mixed"}.get(s["points"], "weak"), s["code"]
        assert s["criteria"]["riders"] == (s["rank_lowest"] > 10)
        assert s["criteria"]["distance"] == (s["nearest_open"]["miles"] >= 3.0)
        assert s["criteria"]["growing"] == (round(s["change_vs_prev_year"] * 100, 1) > 0)
        assert s["criteria"]["recovery"] == (
            s["recovery_pct"] is not None and s["recovery_pct"] >= doc["system"]["recovery_pct"]
        )
    assert doc["period_year"] == 2025
    assert len(doc["system"]["lowest_10"]) == 10


def _doc_verdicts() -> dict[str, str]:
    text = DOC.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.startswith("|")]
    for i, ln in enumerate(lines):
        head = [c.strip() for c in ln.strip("|").split("|")]
        if "Code" in head and "Verdict" in head:
            code_i, verdict_i = head.index("Code"), head.index("Verdict")
            out = {}
            for row in lines[i + 2 :]:
                cells = [c.strip() for c in row.strip("|").split("|")]
                if len(cells) != len(head):
                    break
                code = re.sub(r"[^A-Z0-9]", "", cells[code_i])
                verdict = re.search(r"strong|mixed|weak", cells[verdict_i])
                assert verdict, row
                out[code] = verdict.group(0)
            return out
    raise AssertionError("no results table with Code and Verdict columns")


def test_closures_doc_matches_local_data(api):
    stations = api.get("/api/closures").json()["stations"]
    assert _doc_verdicts() == {s["code"]: s["verdict"] for s in stations}


def _doc_table() -> list[dict[str, str]]:
    lines = [ln for ln in DOC.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    for i, ln in enumerate(lines):
        head = [c.strip() for c in ln.strip("|").split("|")]
        if "Code" in head and "Verdict" in head:
            rows = []
            for row in lines[i + 2 :]:
                cells = [c.strip() for c in row.strip("|").split("|")]
                if len(cells) != len(head):
                    break
                rows.append(dict(zip(head, cells, strict=True)))
            return rows
    raise AssertionError("no results table with Code and Verdict columns")


def _col(row: dict[str, str], prefix: str) -> str:
    (key,) = [k for k in row if k.startswith(prefix)]
    return row[key]


def test_closures_doc_table_matches_local_data(api):
    doc = api.get("/api/closures").json()
    stations = {s["code"]: s for s in doc["stations"]}
    rows = _doc_table()
    assert [re.sub(r"[^A-Z0-9]", "", r["Code"]) for r in rows] == list(stations)
    for r in rows:
        s = stations[re.sub(r"[^A-Z0-9]", "", r["Code"])]
        change = f"{s['change_vs_prev_year'] * 100:+.1f}%".replace("-", "\u2212")
        met = [rule.capitalize() for rule, ok in s["criteria"].items() if ok]
        expected = {
            "Group": str(s["group"]),
            "Weekday trips": f"{s['weekday_trips']:,}",
            "Rank": f"{s['rank_lowest']} of {doc['system']['stations']}",
            "% of 2019": f"{s['recovery_pct']}%",
            "Change vs": change,
            "Nearest station still open": f"{s['nearest_open']['name']}, {s['nearest_open']['miles']:.1f} mi",
            "Rules met": ", ".join(met) or "none",
        }
        for prefix, want in expected.items():
            assert _col(r, prefix) == want, (s["code"], prefix)


def test_closures_doc_sfo_assumption_matches_local_data(api, con):
    from api.routes.data import closure_criteria, closure_verdict

    doc = api.get("/api/closures").json()
    with SEED.open(encoding="utf-8") as f:
        seed = {r["station_code"] for r in csv.DictReader(f)}
    current = {
        code: (name, lat, lon)
        for code, name, lat, lon in con.execute(
            "select station_code, station_name, lat, lon from marts.dim_station where is_current"
        ).fetchall()
    }
    via_sfo = {s["code"]: s for s in doc["stations"] if s["nearest_open"]["code"] == "SFIA"}
    assert set(via_sfo) == {"SBRN", "MLBR"}
    section = DOC.read_text(encoding="utf-8").split("## The SFO assumption", 1)[1].split("\n## ", 1)[0]
    section = re.sub(r"\s+", " ", section)
    verdicts = {s["code"]: s["verdict"] for s in doc["stations"]}
    for code, s in via_sfo.items():
        _, lat, lon = current[code]
        miles, alt = min(
            (_haversine_miles(lat, lon, c_lat, c_lon), c)
            for c, (_, c_lat, c_lon) in current.items()
            if c not in seed and c != "SFIA"
        )
        miles = math.floor(miles * 10 + 0.5) / 10
        change = math.floor(s["change_vs_prev_year"] * 1000 + 0.5) / 10
        criteria = closure_criteria(
            s["rank_lowest"], s["recovery_pct"], doc["system"]["recovery_pct"], miles, change
        )
        verdicts[code] = closure_verdict(sum(criteria.values()))
        for needle in (s["name"], current[alt][0], f"{miles:.1f} mi", verdicts[code]):
            assert needle in section, (code, needle)
    counts = {v: list(verdicts.values()).count(v) for v in ("strong", "mixed", "weak")}
    assert f"strong {counts['strong']}, mixed {counts['mixed']}, weak {counts['weak']}" in section, counts
