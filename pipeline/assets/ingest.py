"""Ingest assets: download raw files, clean them with Spark, load them into the warehouse.

Lineage:  bart_gtfs -> bart_stations_raw ┐
                    -> web_map_data      │
          bart_od_files[year] -> bart_od_parquet[year] -> raw_bart_od[year] -> dbt models (dbt.py)
"""

import hashlib
import json
import urllib.request
from datetime import date

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    StaticPartitionsDefinition,
    asset,
)

from pipeline.resources import ROOT, SparkRunner, Storage

OD_URL = "https://afcweb.bart.gov/ridership/origin-destination/date-hour-soo-dest-{year}.csv.gz"
GTFS_URL = "https://www.bart.gov/dev/schedules/google_transit.zip"
# bart.gov rejects Python's default User-Agent with 403
USER_AGENT = "TransitPulse/0.1 (+https://github.com/braaaeeedyn/transitpulse)"
FIRST_YEAR = 2018  # one year before the 2019 baseline, and the year eBART opened (causal study, M4)
years = StaticPartitionsDefinition([str(y) for y in range(FIRST_YEAR, date.today().year + 1)])


def _download(url: str, dest) -> tuple[str, int, bool]:
    """Download if the content changed. Returns (sha256, bytes, changed)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as res, tmp.open("wb") as f:
        while chunk := res.read(1 << 20):
            f.write(chunk)
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    old = hashlib.sha256(dest.read_bytes()).hexdigest() if dest.exists() else None
    tmp.replace(dest)
    return digest, dest.stat().st_size, digest != old


@asset(group_name="ingest", description="BART GTFS schedule feed (zip).")
def bart_gtfs(context: AssetExecutionContext, storage: Storage) -> MaterializeResult:
    dest = storage.path("cache", "bart_gtfs.zip")
    digest, size, changed = _download(GTFS_URL, dest)
    uri = storage.upload(dest, "gtfs/bart_gtfs.zip")
    return MaterializeResult(
        metadata={"sha256": digest, "bytes": size, "changed": changed, "uri": uri or str(dest)}
    )


@asset(group_name="ingest", deps=[bart_gtfs], description="Station list observation for the SCD2 snapshot.")
def bart_stations_raw(storage: Storage) -> MaterializeResult:
    from pipeline.stations import FIELDS, station_rows

    rows = station_rows(storage.path("cache", "bart_gtfs.zip"))
    out = storage.path("parquet", "bart_stations", "stations.csv")
    import csv

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if storage.mode == "gcp":
        from google.cloud import bigquery

        client = bigquery.Client(project=storage.gcp_project)
        job = client.load_table_from_file(
            out.open("rb"),
            f"{storage.gcp_project}.raw.bart_stations",
            job_config=bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.CSV,
                skip_leading_rows=1,
                autodetect=True,
                write_disposition="WRITE_APPEND",  # every observation is kept; dbt picks the latest
            ),
        )
        job.result()
    return MaterializeResult(metadata={"stations": len(rows)})


@asset(group_name="web", deps=[bart_gtfs], description="Static map data for the website (web/data/*.json).")
def web_map_data(storage: Storage) -> MaterializeResult:
    from pipeline.webdata.build import main as build

    build(["--gtfs", str(storage.path("cache", "bart_gtfs.zip")), "--out", str(ROOT / "web" / "data")])
    sizes = {p.name: p.stat().st_size for p in (ROOT / "web" / "data").glob("*.json")}
    return MaterializeResult(metadata={"bytes": MetadataValue.json(sizes)})


def _has_rows(gz_path) -> bool:
    """BART serves an empty gzip for years it hasn't published yet (e.g. the current year early on)."""
    import gzip

    with gzip.open(gz_path, "rb") as f:
        return bool(f.read(1))


@asset(
    group_name="ingest", partitions_def=years, description="Raw yearly BART origin-destination CSV (gzip)."
)
def bart_od_files(context: AssetExecutionContext, storage: Storage) -> MaterializeResult:
    year = context.partition_key
    dest = storage.path("raw", "bart_od", f"date-hour-soo-dest-{year}.csv.gz")
    digest, size, changed = _download(OD_URL.format(year=year), dest)
    if not _has_rows(dest):
        context.log.warning(f"BART hasn't published {year} ridership yet (empty file); nothing to load")
        return MaterializeResult(metadata={"published": False, "bytes": size})
    uri = storage.upload(dest, f"bart_od/year={year}/{dest.name}")
    return MaterializeResult(
        metadata={
            "published": True,
            "sha256": digest,
            "bytes": size,
            "changed": changed,
            "uri": uri or str(dest),
        }
    )


@asset(
    group_name="ingest",
    partitions_def=years,
    deps=[bart_od_files],
    description="Cleaned, de-duplicated Parquet partitioned by year/month (PySpark job).",
)
def bart_od_parquet(
    context: AssetExecutionContext, storage: Storage, spark: SparkRunner
) -> MaterializeResult:
    year = context.partition_key
    if not _has_rows(storage.root / "raw" / "bart_od" / f"date-hour-soo-dest-{year}.csv.gz"):
        context.log.warning(f"no {year} ridership published yet; skipping Spark")
        return MaterializeResult(metadata={"published": False, "rows_out": 0})
    rel = storage.root.relative_to(ROOT).as_posix()  # relative paths work both in-process and inside Docker
    audit_dir = f"{rel}/parquet/ingest_audit/year={year}"
    spark.run_module(
        "pipeline.spark.clean_bart_od",
        "--input", f"{rel}/raw/bart_od/date-hour-soo-dest-{year}.csv.gz",
        "--output", f"{rel}/parquet/bart_od",
        "--audit", audit_dir,
    )  # fmt: skip
    audit = json.loads((ROOT / audit_dir / "audit.json").read_text())
    return MaterializeResult(
        metadata={
            "rows_in": audit["rows_in"],
            "rows_out": audit["rows_out"],
            "dropped": MetadataValue.json(audit["dropped"]),
        }
    )


@asset(
    group_name="ingest",
    partitions_def=years,
    deps=[bart_od_parquet],
    key_prefix=["raw"],
    name="bart_od",
    description="raw.bart_od in BigQuery (partitioned by trip_date, clustered by origin). Local mode: the Parquet is "
    "read directly by dbt's DuckDB target, so this step only records row counts.",
)
def raw_bart_od(context: AssetExecutionContext, storage: Storage) -> MaterializeResult:
    year = context.partition_key
    parquet_dir = storage.root / "parquet" / "bart_od" / f"year={year}"
    if not any(parquet_dir.rglob("*.parquet")):
        context.log.warning(f"no Parquet for {year} (not published yet); nothing to load")
        return MaterializeResult(metadata={"published": False, "files": 0})
    if storage.mode != "gcp":
        files = list(parquet_dir.rglob("*.parquet"))
        return MaterializeResult(metadata={"mode": "local", "files": len(files)})

    from google.cloud import bigquery

    # upload this year's Parquet, then replace the year's date partitions in one load job
    uris = []
    for f in parquet_dir.rglob("*.parquet"):
        blob = f"parquet/bart_od/{f.relative_to(storage.root / 'parquet' / 'bart_od').as_posix()}"
        uris.append(storage.upload(f, blob))
    client = bigquery.Client(project=storage.gcp_project)
    table = f"{storage.gcp_project}.raw.bart_od"
    from google.api_core.exceptions import NotFound

    try:  # replace this year's rows; on the very first load the table doesn't exist yet
        client.query(f"delete from `{table}` where extract(year from trip_date) = {int(year)}").result()
    except NotFound:
        context.log.info(f"{table} doesn't exist yet; the load job will create it")
    job = client.load_table_from_uri(
        uris,
        table,
        job_config=bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition="WRITE_APPEND",
            time_partitioning=bigquery.TimePartitioning(field="trip_date"),
            clustering_fields=["origin"],
            hive_partitioning=bigquery.HivePartitioningOptions.from_api_repr(
                {"mode": "AUTO", "sourceUriPrefix": f"gs://{storage.raw_bucket}/parquet/bart_od/"}
            ),
        ),
    )
    job.result()
    return MaterializeResult(metadata={"mode": "gcp", "rows_loaded": job.output_rows, "files": len(uris)})
