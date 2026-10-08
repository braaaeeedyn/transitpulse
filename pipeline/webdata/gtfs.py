"""Read the parts of a BART GTFS zip the website needs."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

GTFS_URL = "https://www.bart.gov/dev/schedules/google_transit.zip"

# GTFS route_short_name prefix -> DESIGN.md line token. GTFS route_color is deliberately ignored (DESIGN.md §2).
LINE_TOKEN = {
    "Yellow": "yellow",
    "Orange": "orange",
    "Red": "red",
    "Green": "green",
    "Blue": "blue",
    "Grey": "beige",  # Oakland Airport connector
}


@dataclass
class Station:
    code: str
    name: str
    lon: float
    lat: float


@dataclass
class Trip:
    trip_id: str
    route_id: str
    service_id: str
    shape_id: str
    stops: list[tuple[str, int, int]] = field(default_factory=list)  # (station code, arr min, dep min)


@dataclass
class Service:
    service_id: str
    days: str  # "1111100" = Mon..Sun
    start: str  # YYYYMMDD
    end: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class Feed:
    version: str
    stations: dict[str, Station]
    routes: dict[str, str]  # rail route_id -> line token
    trips: list[Trip]
    shapes: dict[str, list[tuple[float, float]]]  # shape_id -> [(lon, lat)]
    services: dict[str, Service]


def _rows(z: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))


def _minutes(hms: str) -> int:
    h, m, s = (int(x) for x in hms.split(":"))
    if s:
        raise ValueError(f"expected whole-minute times, got {hms}")
    return h * 60 + m  # may exceed 24h for after-midnight service, which we keep


def read_feed(path: Path) -> Feed:
    with zipfile.ZipFile(path) as z:
        info = _rows(z, "feed_info.txt")
        version = info[0].get("feed_version", "") if info else ""

        stops = _rows(z, "stops.txt")
        stations = {
            s["stop_id"]: Station(s["stop_id"], s["stop_name"], float(s["stop_lon"]), float(s["stop_lat"]))
            for s in stops
            if s["location_type"] == "1"
        }
        platform_to_station = {s["stop_id"]: s["parent_station"] for s in stops if s["parent_station"]}

        routes = {}
        for r in _rows(z, "routes.txt"):
            if r["route_type"] != "1":  # rail only; drops the bus bridges
                continue
            prefix = r["route_short_name"].split("-")[0]
            routes[r["route_id"]] = LINE_TOKEN[prefix]

        trips = {
            t["trip_id"]: Trip(t["trip_id"], t["route_id"], t["service_id"], t["shape_id"])
            for t in _rows(z, "trips.txt")
            if t["route_id"] in routes
        }
        st_rows = sorted(
            (r for r in _rows(z, "stop_times.txt") if r["trip_id"] in trips),
            key=lambda r: (r["trip_id"], int(r["stop_sequence"])),
        )
        for r in st_rows:
            code = platform_to_station.get(r["stop_id"], r["stop_id"])
            arr, dep = _minutes(r["arrival_time"]), _minutes(r["departure_time"])
            stops = trips[r["trip_id"]].stops
            if stops and stops[-1][0] == code:
                # Two platforms of the same station back to back (e.g. SFO): one stop, first arrival to last departure.
                stops[-1] = (code, stops[-1][1], dep)
            else:
                stops.append((code, arr, dep))

        shape_pts: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
        used_shapes = {t.shape_id for t in trips.values()}
        for r in _rows(z, "shapes.txt"):
            if r["shape_id"] in used_shapes:
                shape_pts[r["shape_id"]].append(
                    (int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"]))
                )
        shapes = {k: [(lon, lat) for _, lon, lat in sorted(v)] for k, v in shape_pts.items()}

        used_services = {t.service_id for t in trips.values()}
        services = {}
        for c in _rows(z, "calendar.txt"):
            if c["service_id"] in used_services:
                days = "".join(
                    c[d]
                    for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
                )
                services[c["service_id"]] = Service(c["service_id"], days, c["start_date"], c["end_date"])
        for d in _rows(z, "calendar_dates.txt"):
            svc = services.get(d["service_id"])
            if svc:
                (svc.added if d["exception_type"] == "1" else svc.removed).append(d["date"])

    return Feed(version, stations, routes, list(trips.values()), shapes, services)
