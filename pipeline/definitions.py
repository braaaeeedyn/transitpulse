"""Dagster entry point: `dagster dev -m pipeline.definitions` (or `uv run python tasks.py dagster`).

Schedules and sensors (TRANSITPULSE_PLAN §5 Phase 1):
  * bart_od_updates (sensor) - every 6 hours: HEAD the BART ridership files of the last two years and reload a year
    as soon as its Last-Modified changes (BART posts on no fixed day; last year's file still changes in January).
  * models_after_ingest (sensor) - after every successful BART or Bay Wheels ingest run (not backfills): rebuild the
    dbt models and the map data, so new rows reach the marts and the site the same day.
  * baywheels_monthly - 7th of each month, 06:30 Pacific: the Bay Wheels files of the previous month's year (Lyft
    publishes each month's trips early in the next month), cleaned and reloaded.
  * monthly_models - 6th of each month, 08:00 Pacific: GTFS, stations, map data and every dbt model.
  * weekly_forecast - Mondays 09:00 Pacific: retrain and publish the 14-day station forecast (group `ml`).
  * Historical years are loaded once with a backfill of the `years` partitions from the Dagster UI.
"""

import json
import urllib.request
from datetime import timedelta

from dagster import (
    AssetSelection,
    DagsterRunStatus,
    DefaultScheduleStatus,
    DefaultSensorStatus,
    Definitions,
    RunRequest,
    RunStatusSensorContext,
    ScheduleEvaluationContext,
    SensorEvaluationContext,
    SkipReason,
    define_asset_job,
    run_status_sensor,
    schedule,
    sensor,
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


@sensor(job=yearly_ingest, minimum_interval_seconds=6 * 3600, default_status=DefaultSensorStatus.RUNNING)
def bart_od_updates(context: SensorEvaluationContext):
    # the last two partitions, not the clock: a daemon started in December has no partition for the new year yet
    seen = json.loads(context.cursor or "{}")
    for year in ingest.years.get_partition_keys()[-2:]:
        req = urllib.request.Request(
            ingest.OD_URL.format(year=year), method="HEAD", headers={"User-Agent": ingest.USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            stamp = res.headers.get("Last-Modified")
        if stamp and stamp != seen.get(year):
            seen[year] = stamp
            yield RunRequest(run_key=f"ridership-{year}-{stamp}", partition_key=year)
    context.update_cursor(json.dumps(seen))


@run_status_sensor(
    run_status=DagsterRunStatus.SUCCESS,
    monitored_jobs=[yearly_ingest, baywheels_ingest],
    request_job=refresh_reference,
    default_status=DefaultSensorStatus.RUNNING,
)
def models_after_ingest(context: RunStatusSensorContext):
    # a backfill of every year would otherwise rebuild dbt once per year
    if "dagster/backfill" in context.dagster_run.tags:
        return SkipReason("backfill run; rebuild the models once by hand when it finishes")
    return RunRequest(run_key=f"models-after-{context.dagster_run.run_id}")


@schedule(
    job=baywheels_ingest,
    cron_schedule="30 6 7 * *",
    execution_timezone="America/Los_Angeles",
    default_status=DefaultScheduleStatus.RUNNING,
)
def baywheels_monthly(context: ScheduleEvaluationContext):
    year = _previous_months_year(context)
    return RunRequest(run_key=f"baywheels-{context.scheduled_execution_time:%Y-%m}", partition_key=year)


@schedule(
    job=refresh_reference,
    cron_schedule="0 8 6 * *",
    execution_timezone="America/Los_Angeles",
    default_status=DefaultScheduleStatus.RUNNING,
)
def monthly_models(context: ScheduleEvaluationContext):
    # monthly GTFS/stations refresh and a full rebuild, even in a month with no new ridership
    return RunRequest(run_key=f"models-{context.scheduled_execution_time:%Y-%m}")


@schedule(
    job=weekly_forecast_job,
    cron_schedule="0 9 * * 1",
    execution_timezone="America/Los_Angeles",
    default_status=DefaultScheduleStatus.RUNNING,
)
def weekly_forecast(context: ScheduleEvaluationContext):
    return RunRequest(run_key=f"forecast-{context.scheduled_execution_time:%Y-%m-%d}")


def _resources() -> dict:
    from pipeline.resources import default_resources

    return {**default_resources(), "dbt": dbt_assets_mod.dbt_resource()}


defs = Definitions(
    assets=[*ingest_assets, dbt_assets_mod.transitpulse_dbt, forecast.forecast_station_daily],
    jobs=[yearly_ingest, baywheels_ingest, refresh_reference, weekly_forecast_job],
    schedules=[baywheels_monthly, monthly_models, weekly_forecast],
    sensors=[bart_od_updates, models_after_ingest],
    resources=_resources(),
)
