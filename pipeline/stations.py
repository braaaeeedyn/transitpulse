"""Write the BART station list from GTFS as raw data for dbt (`raw.bart_stations`).

    uv run python -m pipeline.stations [--gtfs PATH] [--out data/parquet/bart_stations/stations.csv]

Each run is one observation of the station list; the dbt snapshot `snap_bart_stations` turns successive
observations into a slowly changing dimension (renames/openings tracked over time).
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path

from pipeline.webdata.build import CACHE, ROOT, _download
from pipeline.webdata.gtfs import GTFS_URL, read_feed

FIELDS = ["station_code", "station_name", "lat", "lon", "feed_version", "observed_at"]


def station_rows(gtfs: Path) -> list[dict]:
    feed = read_feed(gtfs)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return [
        {
            "station_code": s.code,
            "station_name": s.name,
            "lat": round(s.lat, 6),
            "lon": round(s.lon, 6),
            "feed_version": feed.version,
            "observed_at": now,
        }
        for s in sorted(feed.stations.values(), key=lambda s: s.code)
    ]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gtfs", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "parquet" / "bart_stations" / "stations.csv")
    args = ap.parse_args(argv)
    rows = station_rows(args.gtfs or _download(GTFS_URL, CACHE / "bart_gtfs.zip"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} stations to {args.out}")


if __name__ == "__main__":
    main()
