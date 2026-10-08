"""Dagster entry point: `dagster dev -m pipeline.definitions` (or `uv run python tasks.py dagster`).

Schedules (TRANSITPULSE_PLAN §5 Phase 1):
  * monthly_refresh - 6th of each month, 06:00 Pacific: re-download the current year's ridership file
    (BART appends a month at a time), re-clean it, reload it, rebuild the dbt models, refresh the map data.
  * Historical years are loaded once with a backfill of the `years` partitions from the Dagster UI.
"""

from dagster import (
    AssetSelection,
    Definitions,
    RunRequest,
    ScheduleEvaluationContext,
    define_asset_job,
    schedule,
)

from pipeline.assets import dbt as dbt_assets_mod
from pipeline.assets import ingest

ingest_assets = [
    ingest.bart_gtfs,
    ingest.bart_stations_raw,
    ingest.web_map_data,
    ingest.bart_od_files,
    ingest.bart_od_parquet,
    ingest.raw_bart_od,
]

# Each run starts a Spark job that needs ~4-6 GB. pipeline/dagster.yaml limits runs carrying this tag to one at a time,
# so a backfill of every year runs them in sequence instead of all at once (which crashed Docker Desktop).
SPARK_TAG = {"transitpulse/spark": "true"}

yearly_ingest = define_asset_job(
    "yearly_ingest",
    selection=AssetSelection.assets(ingest.bart_od_files, ingest.bart_od_parquet, ingest.raw_bart_od),
    partitions_def=ingest.years,
    tags=SPARK_TAG,
)
refresh_reference = define_asset_job(
    "refresh_reference_and_models",
    selection=AssetSelection.assets(ingest.bart_gtfs, ingest.bart_stations_raw, ingest.web_map_data)
    | AssetSelection.assets(dbt_assets_mod.transitpulse_dbt),
)


@schedule(job=yearly_ingest, cron_schedule="0 6 6 * *", execution_timezone="America/Los_Angeles")
def monthly_ridership(context: ScheduleEvaluationContext):
    year = str(context.scheduled_execution_time.year)
    return RunRequest(run_key=f"ridership-{context.scheduled_execution_time:%Y-%m}", partition_key=year)


@schedule(job=refresh_reference, cron_schedule="0 8 6 * *", execution_timezone="America/Los_Angeles")
def monthly_models(context: ScheduleEvaluationContext):
    # two hours after the ingest run, rebuild stations, the map data and every dbt model
    return RunRequest(run_key=f"models-{context.scheduled_execution_time:%Y-%m}")


def _resources() -> dict:
    from pipeline.resources import default_resources

    return {**default_resources(), "dbt": dbt_assets_mod.dbt_resource()}


defs = Definitions(
    assets=[*ingest_assets, dbt_assets_mod.transitpulse_dbt],
    jobs=[yearly_ingest, refresh_reference],
    schedules=[monthly_ridership, monthly_models],
    resources=_resources(),
)
