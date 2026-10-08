"""PySpark job: raw BART hourly origin-destination CSVs -> clean, de-duplicated, partitioned Parquet.

    spark-submit pipeline/spark/clean_bart_od.py --input 'data/raw/bart_od/*.csv.gz' \
        --output data/parquet/bart_od --audit data/parquet/ingest_audit
    # or: uv run python tasks.py spark --input ... --output ...

Input files (bart.gov ridership reports) have no header: date, hour, origin, destination, trips.

Spark concepts used here (TRANSITPULSE_PLAN §5 Phase 1):
  * explicit schema       - no inference pass over GBs of gzip (gzip isn't splittable, so inference = a full extra read)
  * lazy evaluation       - nothing runs until the write; `audit` is computed from one cached DataFrame
  * broadcast join        - the holidays table is tiny, so it is shipped to every executor instead of shuffled
  * shuffle               - dropDuplicates / the de-dup window repartition by key; that is the one wide stage
  * repartition vs coalesce - repartition(year, month) before the write gives one file per partition (a shuffle);
                            coalesce would only merge partitions without moving rows by key
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

RAW_SCHEMA = T.StructType(
    [
        T.StructField("trip_date", T.StringType()),
        T.StructField("hour", T.StringType()),
        T.StructField("origin", T.StringType()),
        T.StructField("destination", T.StringType()),
        T.StructField("trips", T.StringType()),
        T.StructField("_corrupt", T.StringType()),
    ]
)
KEY = ["trip_date", "hour", "origin", "destination"]
STATION_CODE = r"^[A-Z0-9]{4}$"


def read_raw(spark: SparkSession, path: str) -> DataFrame:
    """Read as strings with an explicit schema; rows that don't parse land in `_corrupt`."""
    return (
        spark.read.option("header", "false")
        .option("mode", "PERMISSIVE")
        .option("columnNameOfCorruptRecord", "_corrupt")
        .schema(RAW_SCHEMA)
        .csv(path)
        .withColumn("source_file", F.input_file_name())
    )


def classify(df: DataFrame) -> DataFrame:
    """Trim/cast every column and tag each row with a drop reason (null when the row is good)."""
    typed = df.select(
        F.to_date(F.trim("trip_date"), "yyyy-MM-dd").alias("trip_date"),
        F.trim("hour").cast("int").alias("hour"),
        F.upper(F.trim("origin")).alias("origin"),
        F.upper(F.trim("destination")).alias("destination"),
        F.trim("trips").cast("int").alias("trips"),
        "_corrupt",
        "source_file",
    )
    reason = (
        F.when(F.col("_corrupt").isNotNull(), "malformed_row")
        .when(F.col("trip_date").isNull(), "bad_date")
        .when(F.col("hour").isNull() | ~F.col("hour").between(0, 23), "bad_hour")
        .when(~F.col("origin").rlike(STATION_CODE), "bad_origin")
        .when(~F.col("destination").rlike(STATION_CODE), "bad_destination")
        .when(F.col("trips").isNull(), "bad_trips")
        .when(F.col("trips") <= 0, "non_positive_trips")
    )
    return typed.withColumn("drop_reason", reason)


def deduplicate(good: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Keep one row per (date, hour, origin, destination).

    Exact repeats (e.g. a file downloaded twice) and conflicting repeats (a corrected re-publish) are both
    resolved by keeping the row from the lexicographically latest source file, then the larger count.
    Returns (kept, duplicates).
    """
    w = Window.partitionBy(*KEY).orderBy(F.col("source_file").desc(), F.col("trips").desc())
    ranked = good.withColumn("_rn", F.row_number().over(w))
    kept = ranked.filter("_rn = 1").drop("_rn")
    dupes = ranked.filter("_rn > 1").drop("_rn").withColumn("drop_reason", F.lit("duplicate"))
    return kept, dupes


def holidays_frame(spark: SparkSession, years: list[int]) -> DataFrame:
    import holidays  # imported here so the module loads without it (e.g. for --help)

    rows = [(d, name) for y in years for d, name in holidays.country_holidays("US", years=y).items()]
    schema = T.StructType(
        [T.StructField("holiday_date", T.DateType()), T.StructField("holiday", T.StringType())]
    )
    return spark.createDataFrame(rows, schema)


def enrich(df: DataFrame, holidays_df: DataFrame) -> DataFrame:
    """Derive calendar fields and the holiday flag (broadcast join: the holidays table is ~11 rows/year)."""
    joined = df.join(F.broadcast(holidays_df), df.trip_date == holidays_df.holiday_date, "left")
    return joined.select(
        "trip_date",
        "hour",
        "origin",
        "destination",
        "trips",
        F.dayofweek("trip_date").alias("weekday"),  # 1 = Sunday … 7 = Saturday (Spark/BigQuery convention)
        F.col("holiday_date").isNotNull().alias("is_holiday"),
        "holiday",
        F.year("trip_date").alias("year"),
        F.month("trip_date").alias("month"),
    )


def run(spark: SparkSession, input_path: str, output_path: str, audit_path: str | None) -> dict:
    classified = classify(read_raw(spark, input_path)).cache()  # read once, used for output and audit
    good = classified.filter(F.col("drop_reason").isNull()).drop("drop_reason", "_corrupt")
    bad = classified.filter(F.col("drop_reason").isNotNull())
    kept, _ = deduplicate(good)

    # from the cached frame: cheap, and doesn't trigger the de-dup shuffle a second time
    years = [r.y for r in good.select(F.year("trip_date").alias("y")).distinct().collect()]
    clean = enrich(kept, holidays_frame(spark, years))

    (
        clean.repartition("year", "month")  # one output file per month partition
        .write.mode("overwrite")
        .option("partitionOverwriteMode", "dynamic")  # only rewrite the months present in this run
        .partitionBy("year", "month")
        .parquet(output_path)
    )

    rows_in = classified.count()
    dropped = {r.drop_reason: r["count"] for r in bad.groupBy("drop_reason").count().collect()}
    # rows written = Parquet row counts (footer metadata, no recompute); duplicates = good rows that weren't written
    written = spark.read.parquet(output_path).filter(F.col("year").isin(years)).count()
    dropped["duplicate"] = good.count() - written
    audit = {
        "input": input_path,
        "rows_in": rows_in,
        "rows_out": rows_in - sum(dropped.values()),
        "dropped": dict(sorted(dropped.items())),
        "years": sorted(years),
    }
    if audit_path:
        Path(audit_path).mkdir(parents=True, exist_ok=True)
        (Path(audit_path) / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    classified.unpersist()
    return audit


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="glob of raw CSV(.gz) files, local or gs://")
    ap.add_argument("--output", required=True, help="Parquet output root (partitioned by year/month)")
    ap.add_argument("--audit", help="directory for audit.json (row counts in/out, drops per reason)")
    ap.add_argument("--master", default="local[*]")
    ap.add_argument("--driver-memory", default="4g", help="local mode runs executors inside the driver JVM")
    args = ap.parse_args(argv)

    spark = (
        SparkSession.builder.appName("transitpulse-clean-bart-od")
        .master(args.master)
        .config("spark.driver.memory", args.driver_memory)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "64")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    print(json.dumps(run(spark, args.input, args.output, args.audit), indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
