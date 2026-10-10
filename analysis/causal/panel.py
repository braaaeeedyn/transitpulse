"""Build the weekly station panel for the eBART study from the local warehouse.

    uv run --group ml python -m analysis.causal.panel [--duckdb-path data/transitpulse.duckdb] [--out PATH]

Reads marts.fct_station_daily (read-only) over the pre-registered window and writes the committed
analysis/causal/data/station_week.csv: one row per station x ISO week (Monday start) with the number of days that
have data and the summed entries and exits. Every station is kept. The new stations (ANTC, PCTR) get a row for every
week of the window, with missing station-days counted as 0, so the corridor aggregate is defined before the opening.
"""

import argparse
import csv
from datetime import timedelta
from pathlib import Path

from analysis.causal import design

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "transitpulse.duckdb"
DATA = Path(__file__).with_name("data")
WEEK_CSV = DATA / "station_week.csv"
COLUMNS = ["station_code", "week_start", "days", "entries", "exits"]


def build(duckdb_path: Path = DEFAULT_DB) -> list[dict]:
    import duckdb

    d = design.load()
    end = d.last_week + timedelta(days=6)
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        rows = con.execute(
            """
            select station_code, cast(date_trunc('week', trip_date) as date) as week_start,
                   count(distinct trip_date) as days,
                   cast(sum(entries) as bigint) as entries, cast(sum(exits) as bigint) as exits
            from marts.fct_station_daily
            where trip_date between ? and ?
            group by 1, 2
            """,
            [d.first_week, end],
        ).fetchall()
    finally:
        con.close()
    out = {(s, w): {"days": n, "entries": e, "exits": x} for s, w, n, e, x in rows}
    weeks = [d.first_week + timedelta(days=7 * i) for i in range((d.last_week - d.first_week).days // 7 + 1)]
    for s in d.new:  # a missing station-day counts as 0 for the stations that open during the window
        for w in weeks:
            out.setdefault((s, w), {"days": 0, "entries": 0, "exits": 0})
    return [
        {"station_code": s, "week_start": w.isoformat(), **v}
        for (s, w), v in sorted(out.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    ]


def write(rows: list[dict], path: Path = WEEK_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duckdb-path", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=WEEK_CSV)
    args = ap.parse_args()
    rows = build(args.duckdb_path)
    write(rows, args.out)
    print(f"{len(rows)} rows, {len({r['station_code'] for r in rows})} stations -> {args.out}")


if __name__ == "__main__":
    main()
