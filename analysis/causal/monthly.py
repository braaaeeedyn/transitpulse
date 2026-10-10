"""BART's monthly average-weekday entries per station, 2016-01..2020-02 (the eBART study's monthly robustness).

    uv run --group ml python -m analysis.causal.monthly                       # download (if missing), parse, write CSV
    uv run --group ml python -m analysis.causal.monthly --crosscheck --json   # compare with the daily OD warehouse

Source: https://www.bart.gov/sites/default/files/docs/ridership_YYYY.zip, one workbook per month. The "Weekday OD"
sheet ("Avg Weekday OD" from Feb 2018) is the average-weekday OD matrix: exit-station rows x entry-station columns,
2-letter station codes, an "Exits" total column and an "Entries" total row. Entries per station = the column sum,
which must equal the sheet's own "Entries" row to within 1. The layout is found by header text, not cell addresses.
Zips are cached in data/raw/bart_monthly/ (gitignored); the output, analysis/causal/data/station_month_weekday.csv,
is committed.
"""

import argparse
import ast
import calendar
import csv
import io
import json
import re
import statistics
import sys
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path

from analysis.causal import design

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "bart_monthly"
DEFAULT_DB = ROOT / "data" / "transitpulse.duckdb"
DATA = Path(__file__).with_name("data")
CODES_CSV = DATA / "station_codes_2letter.csv"
MONTH_CSV = DATA / "station_month_weekday.csv"
ZIP_URL = "https://www.bart.gov/sites/default/files/docs/ridership_{year}.zip"
COLUMNS = ["station_code", "month", "avg_weekday_entries"]
MONTHS = {calendar.month_name[i].lower(): i for i in range(1, 13)}


def user_agent() -> str:
    """pipeline.assets.ingest.USER_AGENT (bart.gov rejects Python's default with 403), read from the source so the
    `ml` group alone (no Dagster) can download."""
    src = (ROOT / "pipeline" / "assets" / "ingest.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "USER_AGENT" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("USER_AGENT not found in pipeline/assets/ingest.py")


def download(years, dest: Path = RAW) -> list[Path]:
    """Fetch ridership_YYYY.zip for each year unless it is already there."""
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for y in years:
        path = dest / f"ridership_{y}.zip"
        if not path.exists():
            req = urllib.request.Request(ZIP_URL.format(year=y), headers={"User-Agent": user_agent()})
            tmp = path.with_suffix(".zip.part")
            with urllib.request.urlopen(req, timeout=60) as res, tmp.open("wb") as f:
                while chunk := res.read(1 << 20):
                    f.write(chunk)
            tmp.replace(path)
        paths.append(path)
    return paths


def code_map(path: Path = CODES_CSV) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as f:
        return {r["code2"]: r["station_code"] for r in csv.DictReader(f)}


def _text(v) -> str:
    return str(v).strip() if v is not None else ""


def _month_from_name(name: str) -> str | None:
    stem = Path(name).stem
    if m := re.search(r"(\d{4})(\d{2})$", stem):
        return f"{m.group(1)}-{m.group(2)}"
    if m := re.search(r"([A-Za-z]+)(\d{4})$", stem):
        mon = MONTHS.get(m.group(1).lower())
        return f"{m.group(2)}-{mon:02d}" if mon else None
    return None


def parse_workbook(data: bytes, name: str = "") -> tuple[str, dict[str, float]]:
    """(YYYY-MM, {2-letter code: average weekday entries}) from one monthly workbook."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheets = [s for s in wb.sheetnames if "weekday" in s.lower() and "od" in s.lower()]
        if len(sheets) != 1:
            raise ValueError(f"{name}: expected one weekday OD sheet, found {wb.sheetnames}")
        rows = [list(r) for r in wb[sheets[0]].iter_rows(values_only=True)]
    finally:
        wb.close()
    # header row: the one with an "Exits" column; entry stations are the non-empty cells before it
    hi = next((i for i, r in enumerate(rows) if "Exits" in map(_text, r)), None)
    if hi is None:
        raise ValueError(f"{name}: no header row with an 'Exits' column")
    header = [_text(v) for v in rows[hi]]
    cols = {v: j for j, v in enumerate(header[: header.index("Exits")]) if v}
    # row labels: the column below the header holding the most station codes; its "Entries" cell is the totals row
    width = max(len(r) for r in rows)
    below = rows[hi + 1 :]
    lc = max(range(width), key=lambda j: sum(j < len(r) and _text(r[j]) in cols for r in below))
    ti = next(
        (i for i in range(hi + 1, len(rows)) if lc < len(rows[i]) and _text(rows[i][lc]) == "Entries"), None
    )
    if ti is None:
        raise ValueError(f"{name}: no 'Entries' totals row")
    body = [r for r in rows[hi + 1 : ti] if _text(r[lc]) in cols]
    if {_text(r[lc]) for r in body} != set(cols):
        raise ValueError(f"{name}: exit rows don't match the entry columns")
    month = None
    for r in rows[:hi]:
        for v in r:
            if isinstance(v, datetime | date):
                month = f"{v.year}-{v.month:02d}"
                break
        if month:
            break
    month = month or _month_from_name(name)
    if not month:
        raise ValueError(f"{name}: no month found")
    entries = {}
    for code, j in cols.items():
        total = sum(float(r[j] or 0) for r in body)
        sheet_total = float(rows[ti][j] or 0)
        if abs(total - sheet_total) > 1:
            raise ValueError(f"{name}: {code} column sums to {total:.2f}, sheet says {sheet_total:.2f}")
        entries[code] = total
    return month, entries


def parse_zip(path: Path) -> dict[str, dict[str, float]]:
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if n.lower().endswith(".xlsx") and not Path(n).name.startswith("~$"):
                month, entries = parse_workbook(z.read(n), n)
                if month in out:
                    raise ValueError(f"{path.name}: two workbooks for {month}")
                out[month] = entries
    return out


def build(raw: Path = RAW) -> list[dict]:
    d = design.load()
    years = range(int(d.first_month[:4]), int(d.last_month[:4]) + 1)
    codes = code_map()
    rows = []
    for path in download(years, raw):
        for month, entries in parse_zip(path).items():
            if not d.first_month <= month <= d.last_month:
                continue
            unknown = set(entries) - set(codes)
            if unknown:
                raise ValueError(f"{month}: unmapped station codes {sorted(unknown)}")
            rows += [
                {"station_code": codes[c], "month": month, "avg_weekday_entries": round(v, 4)}
                for c, v in entries.items()
            ]
    return sorted(rows, key=lambda r: (r["station_code"], r["month"]))


def write(rows: list[dict], path: Path = MONTH_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read(path: Path = MONTH_CSV) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{**r, "avg_weekday_entries": float(r["avg_weekday_entries"])} for r in csv.DictReader(f)]


def crosscheck(duckdb_path: Path = DEFAULT_DB, monthly_path: Path = MONTH_CSV) -> dict:
    """Monthly average-weekday entries vs the daily OD warehouse (non-holiday Mon-Fri means) over the months both
    cover. Per station: median and max |% diff| over months; overall: the median of the per-station medians over
    controls + treated, and the worst treated/corridor station."""
    import duckdb

    from ml.forecast.features import us_holidays

    d = design.load()
    monthly = {(r["station_code"], r["month"]): r["avg_weekday_entries"] for r in read(monthly_path)}
    ly, lm = map(int, d.last_month.split("-"))
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        daily = con.execute(
            """
            select station_code, trip_date, cast(entries as bigint)
            from marts.fct_station_daily
            where trip_date between ? and ? and isodow(trip_date) <= 5
            """,
            [date.fromisoformat(f"{d.first_month}-01"), date(ly, lm, calendar.monthrange(ly, lm)[1])],
        ).fetchall()
    finally:
        con.close()
    if not daily:
        raise RuntimeError("no daily rows in the warehouse for the monthly window")
    lo = min(t for _, t, _ in daily)
    hol = {h.date() for h in us_holidays(lo, date(lo.year + 3, 12, 31))}
    sums: dict[tuple[str, str], list[int]] = {}
    for s, t, e in daily:
        if t not in hol:
            sums.setdefault((s, f"{t.year}-{t.month:02d}"), []).append(e)
    diffs: dict[str, list[float]] = {}
    for (s, m), es in sums.items():
        avg = sum(es) / len(es)
        mon = monthly.get((s, m))
        if mon is None or avg < 100 or mon < 100 or m in d.transition_months:
            continue
        diffs.setdefault(s, []).append(100 * abs(mon - avg) / avg)
    per = {
        s: {
            "months": len(v),
            "median_abs_pct": round(statistics.median(v), 3),
            "max_abs_pct": round(max(v), 3),
        }
        for s, v in sorted(diffs.items())
    }
    core = [per[s]["median_abs_pct"] for s in d.controls + d.treated if s in per]
    corridor = {s: per[s] for s in d.corridor if s in per}
    return {
        "months": sorted({m for (_, m) in sums}),
        "stations": len(per),
        "median_abs_pct_diff": round(statistics.median(core), 3),
        "max_station_median_abs_pct_diff": round(max(core), 3),
        "corridor_max_median_abs_pct_diff": round(max(v["median_abs_pct"] for v in corridor.values()), 3),
        "corridor_over_10pct": sorted(s for s, v in corridor.items() if v["median_abs_pct"] > 10),
        "per_station": per,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--crosscheck", action="store_true", help="compare with the daily OD warehouse")
    ap.add_argument("--json", action="store_true", help="print the crosscheck as JSON")
    ap.add_argument("--duckdb-path", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    if args.crosscheck:
        try:
            res = crosscheck(args.duckdb_path)
        except Exception as e:  # offline / no warehouse: the metric is skipped, not failed
            res = {"skipped": f"{type(e).__name__}: {str(e)[:200]}"}
        if args.json:
            res = {k: v for k, v in res.items() if k != "months"} | (
                {"first_month": res["months"][0], "last_month": res["months"][-1]} if "months" in res else {}
            )
            print(json.dumps(res))
        else:
            for k, v in res.items():
                print(f"{k}: {v}")
        return
    rows = build()
    write(rows)
    print(
        f"{len(rows)} rows, {len({r['station_code'] for r in rows})} stations -> {MONTH_CSV}", file=sys.stderr
    )


if __name__ == "__main__":
    main()
