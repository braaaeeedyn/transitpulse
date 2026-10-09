"""Dagster entry point: `dagster dev -m pipeline.definitions` (or `uv run python tasks.py dagster`).

Schedules (TRANSITPULSE_PLAN §5 Phase 1):
  * monthly_refresh - 6th of each month, 06:00 Pacific: re-download the ridership file of the previous month's year
    (BART appends a month at a time, so January reloads last year to pick up December), re-clean it, reload it,
    rebuild the dbt models, refresh the map data.
  * baywheels_monthly - 7th of each month, 06:30 Pacific: the Bay Wheels files of the previous month's year (Lyft
    publishes each month's trips early in the next month), cleaned and reloaded.
  * weekly_forecast - Mondays 09:00 Pacific: retrain and publish the 14-day station forecast (group `ml`).
  * Historical years are loaded once with a backfill of the `years` partitions from the Dagster UI.
"""

from datetime import timedelta

from dagster import (
    AssetSelection,
    Definitions,
    RunRequest,
    ScheduleEvaluationContext,
    define_asset_job,
    schedule,
)

from pipeline.assets import baywheels, forecast, ingest
from pipeline.assets import dbt as dbt_assets_mod

ingest_assets = [
    ingest.bart_gtfs,
    ingest.bart_stations_raw,
    ingest.web_map_data,
    ingest.bart_od_files,
    ingest.bart_od_parquet,
    ingest.raw_bart_od,
    baywheels.baywheels_files,
    baywheels.baywheels_parquet,
    baywheels.raw_baywheels_trips,
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
baywheels_ingest = define_asset_job(
    "baywheels_ingest",
    selection=AssetSelection.assets(
        baywheels.baywheels_files, baywheels.baywheels_parquet, baywheels.raw_baywheels_trips
    ),
    partitions_def=ingest.years,
)
weekly_forecast_job = define_asset_job(
    "weekly_forecast", selection=AssetSelection.assets(forecast.forecast_station_daily)
)
refresh_reference = define_asset_job(
    "refresh_reference_and_models",
    selection=AssetSelection.assets(ingest.bart_gtfs, ingest.bart_stations_raw, ingest.web_map_data)
    | AssetSelection.assets(dbt_assets_mod.transitpulse_dbt),
)


def _previous_months_year(context: ScheduleEvaluationContext) -> str:
    """The year of the month before the run: the latest month the publisher can have released."""
    t = context.scheduled_execution_time
    return str((t.replace(day=1) - timedelta(days=1)).year)


@schedule(job=yearly_ingest, cron_schedule="0 6 6 * *", execution_timezone="America/Los_Angeles")
def monthly_ridership(context: ScheduleEvaluationContext):
    year = _previous_months_year(context)
    return RunRequest(run_key=f"ridership-{context.scheduled_execution_time:%Y-%m}", partition_key=year)


@schedule(job=baywheels_ingest, cron_schedule="30 6 7 * *", execution_timezone="America/Los_Angeles")
def baywheels_monthly(context: ScheduleEvaluationContext):
    year = _previous_months_year(context)
    return RunRequest(run_key=f"baywheels-{context.scheduled_execution_time:%Y-%m}", partition_key=year)


@schedule(job=refresh_reference, cron_schedule="0 8 6 * *", execution_timezone="America/Los_Angeles")
def monthly_models(context: ScheduleEvaluationContext):
    # two hours after the ingest run, rebuild stations, the map data and every dbt model
    return RunRequest(run_key=f"models-{context.scheduled_execution_time:%Y-%m}")


@schedule(job=weekly_forecast_job, cron_schedule="0 9 * * 1", execution_timezone="America/Los_Angeles")
def weekly_forecast(context: ScheduleEvaluationContext):
    return RunRequest(run_key=f"forecast-{context.scheduled_execution_time:%Y-%m-%d}")


def _resources() -> dict:
    from pipeline.resources import default_resources

    return {**default_resources(), "dbt": dbt_assets_mod.dbt_resource()}


defs = Definitions(
    assets=[*ingest_assets, dbt_assets_mod.transitpulse_dbt, forecast.forecast_station_daily],
    jobs=[yearly_ingest, baywheels_ingest, refresh_reference, weekly_forecast_job],
    schedules=[monthly_ridership, baywheels_monthly, monthly_models, weekly_forecast],
    resources=_resources(),
)
