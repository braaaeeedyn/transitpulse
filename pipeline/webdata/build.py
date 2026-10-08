"""Build the static map data the website reads (web/data/*.json) from BART's GTFS feed.

    uv run python -m pipeline.webdata.build [--gtfs PATH] [--counties PATH] [--out web/data]

Outputs (all deterministic: same input -> byte-identical files):
  network.json   stations, lines and track edges in a 0-1000 viewBox
  schedule.json  service calendar + every rail trip, compressed into patterns and timing profiles
  land.json      Bay Area land polygons for the map background (see land.py)
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path

from pipeline.webdata import land as land_mod
from pipeline.webdata.geometry import Point, Projection, dist, round_pts, simplify
from pipeline.webdata.gtfs import GTFS_URL, Feed, read_feed

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"

# DESIGN.md §6: lane order on shared track.
LANE_ORDER = ["yellow", "red", "green", "blue", "orange", "beige"]

LINES = {
    "yellow": ("Yellow line", "Antioch – SFO / Millbrae"),
    "orange": ("Orange line", "Richmond – Berryessa"),
    "red": ("Red line", "Richmond – Millbrae / SFO"),
    "green": ("Green line", "Berryessa – Daly City"),
    "blue": ("Blue line", "Dublin/Pleasanton – Daly City"),
    "beige": ("Airport connector", "Coliseum – Oakland Airport"),
}

# DESIGN.md §6: labels shown when the map is narrower than 600 px.
HUBS = {"EMBR", "12TH", "MCAR", "BALB", "SFIA", "RICH", "ANTC", "BERY", "DUBL"}

SHORT_NAMES = {
    "SFIA": "SFO Airport",
    "OAKL": "Oakland Airport",
    "12TH": "12th St Oakland",
    "19TH": "19th St Oakland",
    "16TH": "16th St Mission",
    "24TH": "24th St Mission",
    "CIVC": "Civic Center",
    "MONT": "Montgomery St",
    "POWL": "Powell St",
    "PHIL": "Pleasant Hill",
    "NCON": "North Concord",
    "PITT": "Pittsburg/Bay Point",
    "WDUB": "West Dublin",
    "DUBL": "Dublin/Pleasanton",
    "WARM": "Warm Springs",
    "BERY": "Berryessa",
    "SSAN": "South SF",
    "DELN": "El Cerrito del Norte",
    "PLZA": "El Cerrito Plaza",
}

SIDES = {"E": (1.0, 0.0), "W": (-1.0, 0.0), "N": (0.0, -1.0), "S": (0.0, 1.0)}
SNAP_TOLERANCE = 25.0  # viewBox units: how close a shape vertex must be to count as "at" a station
SIMPLIFY_TOLERANCE = 0.6


def _station_index(shape: list[Point], target: Point, start: int) -> int:
    """First local minimum within SNAP_TOLERANCE, scanning forward from `start`.

    Scanning forward (instead of taking the global minimum) keeps patterns that double back over the same track
    (e.g. Millbrae <-> SFO) from snapping a station onto the wrong pass.
    """
    best_i, best_d = None, float("inf")
    for i in range(start, len(shape)):
        d = dist(shape[i], target)
        if d < best_d:
            best_i, best_d = i, d
        elif best_d < SNAP_TOLERANCE and d > best_d + SNAP_TOLERANCE:
            break
    if best_i is None:
        return start
    return best_i


def _label_side(pos: Point, neighbours: list[Point]) -> str:
    """Pick the side (E/W/N/S) whose direction is furthest from every incident track direction."""
    dirs = []
    for n in neighbours:
        d = dist(pos, n)
        if d > 0:
            dirs.append(((n[0] - pos[0]) / d, (n[1] - pos[1]) / d))
    if not dirs:
        return "E"
    best, best_score = "E", -math.inf
    for side, (sx, sy) in SIDES.items():
        score = min(1 - (sx * dx + sy * dy) for dx, dy in dirs)
        if score > best_score + 1e-9:
            best, best_score = side, score
    return best


def build_network_and_schedule(feed: Feed, overrides: dict) -> tuple[dict, dict, Projection]:
    used_codes = sorted({code for t in feed.trips for code, _, _ in t.stops})
    stations = {c: feed.stations[c] for c in used_codes}
    proj = Projection.fit([(s.lon, s.lat) for s in stations.values()])
    pos = {c: proj(s.lon, s.lat) for c, s in stations.items()}
    station_idx = {c: i for i, c in enumerate(used_codes)}

    shapes = {sid: [proj(lon, lat) for lon, lat in pts] for sid, pts in feed.shapes.items()}

    # --- patterns: unique (line, stop sequence) ---------------------------------------------------------
    edge_geom: dict[tuple[str, str], list[Point]] = {}
    edge_lines: dict[tuple[str, str], set[str]] = defaultdict(set)
    patterns: dict[tuple[str, tuple[str, ...]], str] = {}  # (line, stops) -> shape_id
    for t in sorted(feed.trips, key=lambda t: t.trip_id):
        line = feed.routes[t.route_id]
        key = (line, tuple(c for c, _, _ in t.stops))
        patterns.setdefault(key, t.shape_id)

    for (line, codes), shape_id in sorted(patterns.items()):
        shape = shapes.get(shape_id, [])
        cursor = 0
        idxs = []
        for c in codes:
            cursor = _station_index(shape, pos[c], cursor) if shape else 0
            idxs.append(cursor)
        for (a, ia), (b, ib) in itertools.pairwise(zip(codes, idxs, strict=True)):
            key = (a, b) if a < b else (b, a)
            edge_lines[key].add(line)
            if key in edge_geom:
                continue
            middle = shape[ia + 1 : ib] if shape and ib > ia else []
            pts = [pos[a], *middle, pos[b]]
            if a > b:
                pts.reverse()
            edge_geom[key] = simplify(pts, SIMPLIFY_TOLERANCE)

    edge_keys = sorted(edge_geom)
    edge_index = {k: i for i, k in enumerate(edge_keys)}
    edges = [
        {
            "a": station_idx[a],
            "b": station_idx[b],
            "lines": [ln for ln in LANE_ORDER if ln in edge_lines[(a, b)]],
            "pts": round_pts(edge_geom[(a, b)]),
        }
        for a, b in edge_keys
    ]

    # --- stations ------------------------------------------------------------------------------------
    neighbours: dict[str, list[Point]] = defaultdict(list)
    station_lines: dict[str, set[str]] = defaultdict(set)
    for (a, b), geom in edge_geom.items():
        neighbours[a].append(geom[1] if len(geom) > 1 else pos[b])
        neighbours[b].append(geom[-2] if len(geom) > 1 else pos[a])
        station_lines[a] |= edge_lines[(a, b)]
        station_lines[b] |= edge_lines[(a, b)]

    station_list = []
    for c in used_codes:
        x, y = pos[c]
        station_list.append(
            {
                "code": c,
                "name": stations[c].name,
                "short": SHORT_NAMES.get(c, stations[c].name),
                "x": round(x, 1),
                "y": round(y, 1),
                "lines": [ln for ln in LANE_ORDER if ln in station_lines[c]],
                "label": overrides.get(c, _label_side(pos[c], neighbours[c])),
                "hub": c in HUBS,
            }
        )

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    network = {
        "version": 1,
        "feed_version": feed.version,
        "viewbox": [0, 0, 1000, 1000],
        "bounds": [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
        "lane_order": LANE_ORDER,
        "lines": [{"id": ln, "name": LINES[ln][0], "desc": LINES[ln][1]} for ln in LANE_ORDER],
        "stations": station_list,
        "edges": edges,
    }

    # --- schedule ------------------------------------------------------------------------------------
    pattern_keys = sorted(patterns)
    pattern_index = {k: i for i, k in enumerate(pattern_keys)}
    pattern_list = []
    for line, codes in pattern_keys:
        hops = []
        for a, b in itertools.pairwise(codes):
            key = (a, b) if a < b else (b, a)
            hops.append([edge_index[key], 1 if a == key[0] else -1])
        pattern_list.append({"line": line, "stops": [station_idx[c] for c in codes], "hops": hops})

    service_ids = sorted(feed.services)
    service_index = {s: i for i, s in enumerate(service_ids)}
    profiles: dict[tuple[int, ...], int] = {}
    trips = []
    for t in feed.trips:
        line = feed.routes[t.route_id]
        t0 = t.stops[0][2]
        prof = tuple(v for _, arr, dep in t.stops for v in (arr - t0, dep - t0))
        if prof not in profiles:
            profiles[prof] = len(profiles)
        p_idx = pattern_index[(line, tuple(c for c, _, _ in t.stops))]
        trips.append([p_idx, service_index[t.service_id], profiles[prof], t0])
    trips.sort()

    # Re-number profiles in first-use order of the sorted trips so output is deterministic.
    order: dict[int, int] = {}
    for trip in trips:
        trip[2] = order.setdefault(trip[2], len(order))
    by_old = {v: k for k, v in profiles.items()}
    profile_list = [list(by_old[old]) for old, _ in sorted(order.items(), key=lambda kv: kv[1])]

    schedule = {
        "version": 1,
        "feed_version": feed.version,
        "timezone": "America/Los_Angeles",
        "time_unit": "minutes after service-day midnight (can exceed 1440)",
        "services": [
            {
                "id": s,
                "days": feed.services[s].days,
                "start": feed.services[s].start,
                "end": feed.services[s].end,
                "added": sorted(feed.services[s].added),
                "removed": sorted(feed.services[s].removed),
            }
            for s in service_ids
        ],
        "patterns": pattern_list,
        "profiles": profile_list,
        "trip_fields": ["pattern", "service", "profile", "start"],
        "trips": trips,
    }
    return network, schedule, proj


def _download(url: str, dest: Path) -> Path:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        print(f"downloading {url}")
        # bart.gov rejects Python's default User-Agent with 403
        req = urllib.request.Request(url, headers={"User-Agent": "TransitPulse/0.1"})
        with urllib.request.urlopen(req) as res:
            dest.write_bytes(res.read())
    return dest


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} KB)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gtfs", type=Path, help="path to a BART GTFS zip (default: download)")
    ap.add_argument("--counties", type=Path, help="path to cb_2023_us_county_500k.zip (default: download)")
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "data")
    ap.add_argument("--skip-land", action="store_true")
    args = ap.parse_args(argv)

    gtfs = args.gtfs or _download(GTFS_URL, CACHE / "bart_gtfs.zip")
    overrides = json.loads((Path(__file__).parent / "label_overrides.json").read_text(encoding="utf-8"))
    network, schedule, proj = build_network_and_schedule(read_feed(gtfs), overrides)

    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "network.json", network)
    write_json(args.out / "schedule.json", schedule)
    if not args.skip_land:
        counties = args.counties or _download(land_mod.COUNTIES_URL, CACHE / "cb_2023_us_county_500k.zip")
        write_json(args.out / "land.json", land_mod.build_land(counties, proj))


if __name__ == "__main__":
    main()
