"""F2: invariants of the committed map data (web/data/*.json) and the geometry helpers."""

import itertools
import json
from pathlib import Path

import pytest

from pipeline.webdata.build import LANE_ORDER, _label_side
from pipeline.webdata.geometry import Projection, simplify

DATA = Path(__file__).resolve().parents[1] / "web" / "data"


@pytest.fixture(scope="module")
def network():
    return json.loads((DATA / "network.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schedule():
    return json.loads((DATA / "schedule.json").read_text(encoding="utf-8"))


def test_every_station_inside_viewbox(network):
    for s in network["stations"]:
        assert 0 <= s["x"] <= 1000 and 0 <= s["y"] <= 1000, s["code"]


def test_edges_connect_distinct_stations_and_have_lines(network):
    n = len(network["stations"])
    for e in network["edges"]:
        assert e["a"] != e["b"]
        assert 0 <= e["a"] < n and 0 <= e["b"] < n
        assert e["lines"], e
        assert e["lines"] == [ln for ln in LANE_ORDER if ln in e["lines"]], (
            "lanes must follow DESIGN.md order"
        )
        assert len(e["pts"]) >= 2


def test_edge_geometry_starts_and_ends_at_its_stations(network):
    st = network["stations"]
    for e in network["edges"]:
        a, b = st[e["a"]], st[e["b"]]
        assert e["pts"][0] == [a["x"], a["y"]]
        assert e["pts"][-1] == [b["x"], b["y"]]


def test_every_line_has_track(network):
    on_track = {ln for e in network["edges"] for ln in e["lines"]}
    assert on_track == {ln["id"] for ln in network["lines"]}


def test_hub_labels_present(network):
    hubs = {s["code"] for s in network["stations"] if s["hub"]}
    assert hubs == {"EMBR", "12TH", "MCAR", "BALB", "SFIA", "RICH", "ANTC", "BERY", "DUBL"}


def test_pattern_hops_match_stops(network, schedule):
    edges = network["edges"]
    for p in schedule["patterns"]:
        assert len(p["hops"]) == len(p["stops"]) - 1
        for (edge_i, direction), (a, b) in zip(p["hops"], itertools.pairwise(p["stops"]), strict=True):
            e = edges[edge_i]
            assert (e["a"], e["b"]) == ((a, b) if direction == 1 else (b, a))
            assert p["line"] in e["lines"]


def test_trip_times_are_monotonic(schedule):
    for prof in schedule["profiles"]:
        assert prof[0] == 0 or prof[1] == 0, "profiles are relative to the first departure"
        assert all(x <= y for x, y in itertools.pairwise(prof)), prof


def test_trips_reference_valid_tables(schedule):
    for pattern, service, profile, start in schedule["trips"]:
        assert len(schedule["profiles"][profile]) == 2 * len(schedule["patterns"][pattern]["stops"])
        assert 0 <= service < len(schedule["services"])
        assert 0 <= start < 30 * 60


def test_data_is_small():
    total = sum(f.stat().st_size for f in DATA.glob("*.json"))
    assert total < 300 * 1024  # IMPLEMENTATION_PLAN F2 target


def test_projection_round_trip():
    proj = Projection.fit([(-122.5, 37.3), (-121.7, 38.1)])
    x, y = proj(-122.1, 37.8)
    lon, lat = proj.inverse(x, y)
    assert lon == pytest.approx(-122.1) and lat == pytest.approx(37.8)
    # north is up: higher latitude -> smaller y
    assert proj(-122.1, 38.0)[1] < proj(-122.1, 37.5)[1]


def test_simplify_keeps_endpoints_and_drops_collinear():
    pts = [(0, 0), (1, 0.01), (2, 0), (3, 5), (4, 0)]
    out = simplify(pts, 0.5)
    assert out[0] == (0, 0) and out[-1] == (4, 0)
    assert (1, 0.01) not in out and (3, 5) in out


def test_label_side_avoids_track():
    # track runs east-west through the station -> label goes north or south
    assert _label_side((0, 0), [(10, 0), (-10, 0)]) in {"N", "S"}
    # track runs north-south -> label goes east or west
    assert _label_side((0, 0), [(0, 10), (0, -10)]) in {"E", "W"}
