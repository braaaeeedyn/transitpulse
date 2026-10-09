"""The Dagster code location loads and contains the Bay Wheels and forecast assets, jobs and schedules.
Needs dbt's target/manifest.json (run `dbt parse` first; CI does)."""


def test_definitions_include_new_assets_and_schedules():
    from pipeline.definitions import defs

    keys = {k.to_user_string() for k in defs.resolve_asset_graph().get_all_asset_keys()}
    assert {"baywheels_files", "baywheels_parquet", "raw/baywheels_trips", "forecast_station_daily"} <= keys
    # the dbt source raw.baywheels_trips is the ingest asset, so the warehouse models hang off it
    assert {"staging/stg_baywheels_trips", "marts/fct_bike_trips_daily", "marts/mart_bikes_vs_trains"} <= keys

    assert defs.resolve_job_def("baywheels_ingest") is not None
    assert defs.resolve_job_def("weekly_forecast") is not None
    schedules = {s.name: s for s in defs.schedules}
    assert schedules["baywheels_monthly"].job_name == "baywheels_ingest"
    assert schedules["baywheels_monthly"].cron_schedule == "30 6 7 * *"
    assert schedules["weekly_forecast"].job_name == "weekly_forecast"
    assert schedules["weekly_forecast"].cron_schedule == "0 9 * * 1"
    assert schedules["weekly_forecast"].execution_timezone == "America/Los_Angeles"

    graph = defs.resolve_asset_graph()
    from dagster import AssetKey

    forecast = graph.get(AssetKey("forecast_station_daily"))
    assert AssetKey(["marts", "fct_station_daily"]) in forecast.parent_keys
    stg = graph.get(AssetKey(["staging", "stg_baywheels_trips"]))
    assert AssetKey(["raw", "baywheels_trips"]) in stg.parent_keys


def test_monthly_schedules_ingest_previous_months_year():
    # BART and Lyft publish a month's data early in the next month, so the January run must reload last year's
    # partition (to pick up December), not the new year's (which has nothing yet)
    import datetime as dt
    from zoneinfo import ZoneInfo

    from dagster import build_schedule_context

    from pipeline.definitions import baywheels_monthly, monthly_ridership

    pacific = ZoneInfo("America/Los_Angeles")
    cases = [
        (monthly_ridership, dt.datetime(2027, 1, 6, 6, 0, tzinfo=pacific), "2026", "ridership-2027-01"),
        (monthly_ridership, dt.datetime(2026, 7, 6, 6, 0, tzinfo=pacific), "2026", "ridership-2026-07"),
        (baywheels_monthly, dt.datetime(2027, 1, 7, 6, 30, tzinfo=pacific), "2026", "baywheels-2027-01"),
        (baywheels_monthly, dt.datetime(2026, 7, 7, 6, 30, tzinfo=pacific), "2026", "baywheels-2026-07"),
    ]
    for sched, when, year, run_key in cases:
        req = sched(build_schedule_context(scheduled_execution_time=when))
        assert (req.partition_key, req.run_key) == (year, run_key), (sched.name, when)
