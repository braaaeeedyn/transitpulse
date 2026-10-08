"""Bay Wheels (Lyft) trip data: discover the monthly files, download them, and clean them into Parquet.

    uv run python -m pipeline.baywheels --years 2019 2025          # download + clean (local data/ layout)

Why DuckDB rather than Spark: a year is 2-5 M trips (~100-200 MB zipped), which is single-machine work. DuckDB runs
natively on Windows, in CI and on the ARM VM (no JVM, no Docker), and has an explicit-schema CSV reader with
reject tracking and partitioned Parquet output. Spark stays on the much larger BART origin-destination data.

Facts about the public bucket (https://s3.amazonaws.com/baywheels-data, checked 2026-10-08):
  * File names are irregular (`fordgobike`, `baywheels`, a `baywheeels` typo, `lyftbikes`; `.csv.zip` or `.zip`),
    some months are missing (2020-04, 2024-12), and 2017 is a single yearly file. So keys are discovered from the
    bucket listing by their `YYYYMM-` prefix, never built from a template.
  * Two schemas: the Ford GoBike "legacy" one (to ~2020-03) and the Lyft one (`ride_id`, `member_casual`, ...).
  * Zips carry a `__MACOSX/` resource-fork entry, which is skipped.
  * A monthly file can contain a few trips that started in the previous month; those are dropped
    (`outside_file_month`) so a trip is only ever counted from its own month's file.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUCKET_URL = "https://s3.amazonaws.com/baywheels-data"
USER_AGENT = "TransitPulse/0.1 (+https://github.com/braaaeeedyn/transitpulse)"
_S3 = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_MONTHLY_KEY = re.compile(r"^(\d{4})(\d{2})-[^/]+\.zip$")
_COLUMN = re.compile(r"^[a-z_]+$")

LEGACY_COLUMNS = {"start_time", "end_time", "start_station_latitude", "start_station_longitude", "user_type"}
LYFT_COLUMNS = {"ride_id", "started_at", "ended_at", "start_lat", "start_lng", "member_casual"}

# generous box around the service area (SF, East Bay, San Jose); anything outside is a GPS/test artefact
BAY_AREA = {"lat": (36.9, 38.4), "lng": (-123.0, -121.5)}
MAX_DURATION_SEC = 24 * 3600

DROP_REASONS = [
    "malformed_row",
    "bad_timestamp",
    "non_positive_duration",
    "over_24h",
    "missing_coordinates",
    "outside_bay_area",
    "outside_file_month",
    "duplicate",
]

# the cleaned schema, in order (year/month are Hive partition directories, not columns)
OUTPUT_COLUMNS = [
    "ride_id",
    "started_at",
    "ended_at",
    "duration_sec",
    "start_station_id",
    "start_station_name",
    "end_station_id",
    "end_station_name",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "rideable_type",
    "member_type",
    "trip_date",
    "source_file",
    "schema_version",
]


@dataclass(frozen=True)
class S3Object:
    key: str
    size: int
    etag: str


# --- discovery -----------------------------------------------------------------------------------


def parse_listing(xml: bytes) -> tuple[list[S3Object], str | None]:
    """Parse one S3 ListObjects (v1) page. Returns the objects and the marker for the next page (None if last)."""
    root = ET.fromstring(xml)
    objects = [
        S3Object(
            key=c.findtext(f"{_S3}Key", ""),
            size=int(c.findtext(f"{_S3}Size", "0")),
            etag=c.findtext(f"{_S3}ETag", "").strip('"'),
        )
        for c in root.iter(f"{_S3}Contents")
    ]
    truncated = root.findtext(f"{_S3}IsTruncated", "false").lower() == "true"
    return objects, (objects[-1].key if truncated and objects else None)


def monthly_files(objects: list[S3Object]) -> dict[tuple[int, int], S3Object]:
    """Map (year, month) to its zip. Keys without a `YYYYMM-` prefix (e.g. the yearly 2017 file) are ignored.
    If a month ever had two files, the larger one wins."""
    out: dict[tuple[int, int], S3Object] = {}
    for obj in objects:
        m = _MONTHLY_KEY.match(obj.key)
        if not m:
            continue
        ym = (int(m.group(1)), int(m.group(2)))
        if not 1 <= ym[1] <= 12:
            continue
        if ym not in out or obj.size > out[ym].size:
            out[ym] = obj
    return dict(sorted(out.items()))


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()


def list_bucket(url: str = BUCKET_URL, fetch=_get) -> list[S3Object]:
    objects: list[S3Object] = []
    marker: str | None = ""
    while marker is not None:
        page, marker = parse_listing(fetch(f"{url}?marker={urllib.parse.quote(marker)}" if marker else url))
        objects.extend(page)
    return objects


def download(obj: S3Object, dest_dir: Path, manifest: dict, url: str = BUCKET_URL) -> tuple[Path, bool]:
    """Download one zip unless the manifest says we already have this exact object (same ETag and size, file
    present). Records the sha256 of what was downloaded. Returns (path, downloaded)."""
    dest = dest_dir / obj.key
    seen = manifest.get(obj.key)
    if seen and seen["etag"] == obj.etag and seen["size"] == obj.size and dest.exists():
        return dest, False
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    req = urllib.request.Request(f"{url}/{urllib.parse.quote(obj.key)}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as res, tmp.open("wb") as f:
        while chunk := res.read(1 << 20):
            f.write(chunk)
            digest.update(chunk)
    tmp.replace(dest)
    manifest[obj.key] = {"etag": obj.etag, "size": obj.size, "sha256": digest.hexdigest()}
    return dest, True


# --- cleaning ------------------------------------------------------------------------------------


def detect_schema(header: list[str]) -> str:
    cols = {c.strip().lower() for c in header}
    if cols >= LYFT_COLUMNS:
        return "lyft"
    if cols >= LEGACY_COLUMNS:
        return "legacy"
    raise ValueError(f"unrecognised Bay Wheels CSV header: {header}")


def extract_csv(zip_path: Path, dest_dir: Path) -> Path:
    """Extract the trip CSV from a monthly zip (skipping __MACOSX entries) without trusting member paths."""
    with zipfile.ZipFile(zip_path) as z:
        members = [
            i
            for i in z.infolist()
            if not i.is_dir()
            and not i.filename.startswith("__MACOSX")
            and i.filename.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise ValueError(f"{zip_path.name}: expected one CSV, found {[m.filename for m in members]}")
        out = dest_dir / Path(members[0].filename).name  # basename only: no path traversal
        with z.open(members[0]) as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    return out


def _header(csv_path: Path) -> list[str]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(io.StringIO(f.readline())))
    return [h.strip().lower() for h in header]


def _blank(col: str) -> str:
    return f"nullif(nullif(trim({col}), ''), 'NULL')"


_NORMALIZE = {
    "legacy": f"""
        md5(concat_ws('|', start_time, end_time, coalesce(bike_id, ''), coalesce(start_station_id, ''),
                      coalesce(end_station_id, ''))) as ride_id,
        try_cast(start_time as timestamp) as started_at,
        try_cast(end_time as timestamp) as ended_at,
        {_blank("start_station_id")} as start_station_id,
        {_blank("start_station_name")} as start_station_name,
        {_blank("end_station_id")} as end_station_id,
        {_blank("end_station_name")} as end_station_name,
        try_cast(start_station_latitude as double) as start_lat,
        try_cast(start_station_longitude as double) as start_lng,
        try_cast(end_station_latitude as double) as end_lat,
        try_cast(end_station_longitude as double) as end_lng,
        'unknown' as rideable_type,
        case lower(trim(user_type)) when 'subscriber' then 'member' when 'customer' then 'casual' end
            as member_type""",
    "lyft": f"""
        coalesce({_blank("ride_id")},
                 md5(concat_ws('|', started_at, ended_at, coalesce(start_lat, ''), coalesce(start_lng, ''))))
            as ride_id,
        try_cast(started_at as timestamp) as started_at,
        try_cast(ended_at as timestamp) as ended_at,
        {_blank("start_station_id")} as start_station_id,
        {_blank("start_station_name")} as start_station_name,
        {_blank("end_station_id")} as end_station_id,
        {_blank("end_station_name")} as end_station_name,
        try_cast(start_lat as double) as start_lat,
        try_cast(start_lng as double) as start_lng,
        try_cast(end_lat as double) as end_lat,
        try_cast(end_lng as double) as end_lng,
        coalesce(lower({_blank("rideable_type")}), 'unknown') as rideable_type,
        case lower(trim(member_casual)) when 'member' then 'member' when 'casual' then 'casual' end
            as member_type""",
}


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def clean_csv(csv_path: Path, year: int, month: int, out_root: Path, source_file: str) -> dict:
    """Clean one month's CSV into out_root/year=YYYY/month=M/part-0.parquet (replacing that month only).
    Returns {"rows_in", "rows_out", "dropped": {reason: n}, "schema_version"}."""
    import duckdb

    header = _header(csv_path)
    schema = detect_schema(header)
    bad = [h for h in header if not _COLUMN.match(h)]
    if bad or len(set(header)) != len(header):
        raise ValueError(f"{source_file}: unexpected column names {header}")
    columns = "{" + ", ".join(f"'{h}': 'VARCHAR'" for h in header) + "}"
    lat, lng = BAY_AREA["lat"], BAY_AREA["lng"]
    inside = " and ".join(
        f"{c} between {lo} and {hi}"
        for c, (lo, hi) in [("start_lat", lat), ("end_lat", lat), ("start_lng", lng), ("end_lng", lng)]
    )

    con = duckdb.connect()  # in-memory, one per file so the rejects tables only hold this file's errors
    try:
        con.execute(
            f"""create table src as select * from read_csv({_sql_str(str(csv_path))}, header = true,
                auto_detect = false, delim = ',', quote = '"', escape = '"', columns = {columns},
                store_rejects = true)"""
        )
        malformed = con.execute("select count(distinct (scan_id, line)) from reject_errors").fetchone()[0]
        con.execute(
            f"""create table tagged as
            with n as (select {_NORMALIZE[schema]} from src)
            select *,
                date_diff('millisecond', started_at, ended_at) / 1000.0 as duration_sec,
                case
                    when started_at is null or ended_at is null then 'bad_timestamp'
                    when ended_at <= started_at then 'non_positive_duration'
                    when date_diff('second', started_at, ended_at) > {MAX_DURATION_SEC} then 'over_24h'
                    when start_lat is null or start_lng is null or end_lat is null or end_lng is null
                        then 'missing_coordinates'
                    when not ({inside}) then 'outside_bay_area'
                    when year(started_at) != {int(year)} or month(started_at) != {int(month)}
                        then 'outside_file_month'
                end as drop_reason
            from n"""
        )
        con.execute(
            """create table kept as
            select * exclude (rn) from (
                select *, row_number() over (partition by ride_id order by started_at, ended_at) as rn
                from tagged where drop_reason is null
            ) where rn = 1"""
        )
        rows_in = con.execute("select count(*) from tagged").fetchone()[0] + malformed
        counts = dict(
            con.execute(
                "select drop_reason, count(*) from tagged where drop_reason is not null group by 1"
            ).fetchall()
        )
        rows_out = con.execute("select count(*) from kept").fetchone()[0]
        valid = con.execute("select count(*) from tagged where drop_reason is null").fetchone()[0]
        dropped = {r: 0 for r in DROP_REASONS}
        dropped.update(counts)
        dropped["malformed_row"] = malformed
        dropped["duplicate"] = valid - rows_out

        part_dir = out_root / f"year={int(year)}" / f"month={int(month)}"
        if part_dir.exists():
            shutil.rmtree(part_dir)
        part_dir.mkdir(parents=True)
        select = ", ".join(
            {
                "trip_date": "cast(started_at as date) as trip_date",
                "source_file": f"{_sql_str(source_file)} as source_file",
                "schema_version": f"{_sql_str(schema)} as schema_version",
            }.get(c, c)
            for c in OUTPUT_COLUMNS
        )
        target = (part_dir / "part-0.parquet").as_posix()
        con.execute(
            f"copy (select {select} from kept order by started_at) to {_sql_str(target)} "
            "(format parquet, compression zstd)"
        )
    finally:
        con.close()
    return {"rows_in": rows_in, "rows_out": rows_out, "dropped": dropped, "schema_version": schema}


def clean_zip(zip_path: Path, year: int, month: int, out_root: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="baywheels-") as tmp:
        csv_path = extract_csv(zip_path, Path(tmp))
        return clean_csv(csv_path, year, month, out_root, source_file=zip_path.name)


def merge_audits(audits: dict[str, dict]) -> dict:
    """Totals over per-month audits (keyed by "YYYY-MM")."""
    dropped = {r: sum(a["dropped"].get(r, 0) for a in audits.values()) for r in DROP_REASONS}
    return {
        "rows_in": sum(a["rows_in"] for a in audits.values()),
        "rows_out": sum(a["rows_out"] for a in audits.values()),
        "dropped": dropped,
        "months": audits,
    }


# --- year runner (used by the Dagster assets and the CLI) --------------------------------------------


def manifest_path(raw_dir: Path) -> Path:
    return raw_dir / "manifest.json"


def load_manifest(raw_dir: Path) -> dict:
    p = manifest_path(raw_dir)
    return json.loads(p.read_text()) if p.exists() else {}


def save_manifest(raw_dir: Path, manifest: dict) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path(raw_dir).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", newline="\n")


def download_year(year: int, raw_dir: Path, objects: list[S3Object] | None = None) -> dict:
    """Download every monthly file for `year`. Returns metadata (months found/missing, bytes, downloaded)."""
    files = {ym: o for ym, o in monthly_files(objects or list_bucket()).items() if ym[0] == year}
    manifest = load_manifest(raw_dir)
    downloaded = []
    for (_, m), obj in files.items():
        _, fresh = download(obj, raw_dir, manifest)
        if fresh:
            downloaded.append(m)
        save_manifest(raw_dir, manifest)  # after each file, so an interrupted run resumes
    return {
        "year": year,
        "months": sorted(m for _, m in files),
        "keys": {f"{year}-{m:02d}": o.key for (_, m), o in files.items()},
        "downloaded": downloaded,
        "bytes": sum(o.size for o in files.values()),
    }


def year_zips(year: int, raw_dir: Path) -> dict[int, Path]:
    """The downloaded zips for a year, by month (from the manifest written by download_year)."""
    manifest = load_manifest(raw_dir)
    out = {}
    for key in manifest:
        m = _MONTHLY_KEY.match(key)
        if m and int(m.group(1)) == year and (raw_dir / key).exists():
            out[int(m.group(2))] = raw_dir / key
    return dict(sorted(out.items()))


def clean_year(year: int, raw_dir: Path, out_root: Path, audit_root: Path) -> dict:
    audits = {}
    for month, zip_path in year_zips(year, raw_dir).items():
        audits[f"{year}-{month:02d}"] = clean_zip(zip_path, year, month, out_root)
    audit = {"year": year, **merge_audits(audits)}
    audit_dir = audit_root / f"year={year}"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", newline="\n")
    return audit


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="+", required=True)
    ap.add_argument("--data-root", type=Path, default=ROOT / "data")
    ap.add_argument("--skip-download", action="store_true", help="clean what's already in data/raw/baywheels")
    args = ap.parse_args(argv)
    raw_dir = args.data_root / "raw" / "baywheels"
    objects = None if args.skip_download else list_bucket()
    for year in args.years:
        if not args.skip_download:
            meta = download_year(year, raw_dir, objects)
            print(
                f"{year}: {len(meta['months'])} monthly files, {len(meta['downloaded'])} downloaded",
                flush=True,
            )
        audit = clean_year(
            year,
            raw_dir,
            args.data_root / "parquet" / "baywheels_trips",
            args.data_root / "parquet" / "baywheels_audit",
        )
        print(
            f"{year}: {audit['rows_in']:,} rows in, {audit['rows_out']:,} out, dropped {audit['dropped']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
