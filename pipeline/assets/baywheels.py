"""Bay Wheels ingest assets (yearly partitions, like BART).

Lineage:  baywheels_files[year] -> baywheels_parquet[year] -> raw/baywheels_trips[year] -> dbt (stg_baywheels_trips ...)

The cleaning runs in-process with DuckDB (pipeline/baywheels.py explains why not Spark), so these runs don't carry
the one-at-a-time Spark tag.
"""

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from pipeline import baywheels as bw
from pipeline.assets.ingest import years
from pipeline.resources import Storage


def _raw_dir(storage: Storage):
    return storage.root / "raw" / "baywheels"


@asset(
    group_name="ingest",
    partitions_def=years,
    description="Monthly Bay Wheels trip zips for the year, discovered from the public bucket listing "
    "(names are irregular, some months are missing). Re-downloads only files whose ETag/size changed.",
)
def baywheels_files(context: AssetExecutionContext, storage: Storage) -> MaterializeResult:
    year = int(context.partition_key)
    meta = bw.download_year(year, _raw_dir(storage))
    if not meta["months"]:
        context.log.warning(f"no monthly Bay Wheels files for {year} in the bucket")
    missing = [m for m in range(1, 13) if m not in meta["months"]]
    uris = []
    for key in meta["keys"].values():
        uri = storage.upload(_raw_dir(storage) / key, f"baywheels/year={year}/{key}")
        if uri:
            uris.append(uri)
    return MaterializeResult(
        metadata={
            "months": MetadataValue.json(meta["months"]),
            "missing_months": MetadataValue.json(missing),
            "downloaded": MetadataValue.json(meta["downloaded"]),
            "bytes": meta["bytes"],
            "uploaded": len(uris),
        }
    )


@asset(
    group_name="ingest",
    partitions_def=years,
    deps=[baywheels_files],
    description="Cleaned Bay Wheels trips as Parquet partitioned by year/month (DuckDB), with drop counts per "
    "reason in parquet/baywheels_audit/year=YYYY/audit.json.",
)
def baywheels_parquet(context: AssetExecutionContext, storage: Storage) -> MaterializeResult:
    year = int(context.partition_key)
    audit = bw.clean_year(
        year,
        _raw_dir(storage),
        storage.root / "parquet" / "baywheels_trips",
        storage.root / "parquet" / "baywheels_audit",
    )
    if not audit["months"]:
        context.log.warning(f"no Bay Wheels files downloaded for {year}; nothing cleaned")
    return MaterializeResult(
        metadata={
            "rows_in": audit["rows_in"],
            "rows_out": audit["rows_out"],
            "dropped": MetadataValue.json(audit["dropped"]),
            "months": len(audit["months"]),
        }
    )


@asset(
    group_name="ingest",
    partitions_def=years,
    deps=[baywheels_parquet],
    key_prefix=["raw"],
    name="baywheels_trips",
    description="raw.baywheels_trips in BigQuery (partitioned by trip_date, clustered by start_station_id). Local "
    "mode: dbt's DuckDB target reads the Parquet directly, so this step only records file counts.",
)
def raw_baywheels_trips(context: AssetExecutionContext, storage: Storage) -> MaterializeResult:
    year = int(context.partition_key)
    base = storage.root / "parquet" / "baywheels_trips"
    files = sorted((base / f"year={year}").rglob("*.parquet"))
    if not files:
        context.log.warning(f"no Bay Wheels Parquet for {year}; nothing to load")
        return MaterializeResult(metadata={"files": 0})
    if storage.mode != "gcp":
        return MaterializeResult(metadata={"mode": "local", "files": len(files)})

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    uris = [storage.upload(f, f"parquet/baywheels_trips/{f.relative_to(base).as_posix()}") for f in files]
    client = bigquery.Client(project=storage.gcp_project)
    table = f"{storage.gcp_project}.raw.baywheels_trips"
    try:  # replace this year's rows; on the first load the table doesn't exist yet
        client.query(f"delete from `{table}` where extract(year from trip_date) = {year}").result()
    except NotFound:
        context.log.info(f"{table} doesn't exist yet; the load job will create it")
    job = client.load_table_from_uri(
        uris,
        table,
        job_config=bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition="WRITE_APPEND",
            time_partitioning=bigquery.TimePartitioning(field="trip_date"),
            clustering_fields=["start_station_id"],
            hive_partitioning=bigquery.HivePartitioningOptions.from_api_repr(
                {"mode": "AUTO", "sourceUriPrefix": f"gs://{storage.raw_bucket}/parquet/baywheels_trips/"}
            ),
        ),
    )
    job.result()
    return MaterializeResult(metadata={"mode": "gcp", "rows_loaded": job.output_rows, "files": len(uris)})
