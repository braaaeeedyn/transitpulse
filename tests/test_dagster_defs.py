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


def test_bart_sensor_reloads_a_year_only_when_its_file_changes(monkeypatch):
    import json
    from unittest import mock

    from dagster import build_sensor_context

    from pipeline import definitions
    from pipeline.assets import ingest

    stamps = {}  # url -> Last-Modified that BART "serves"

    def fake_urlopen(req, timeout):
        res = mock.MagicMock()
        res.__enter__.return_value.headers = {"Last-Modified": stamps[req.full_url]}
        return res

    monkeypatch.setattr(definitions.urllib.request, "urlopen", fake_urlopen)
    old, new = ingest.years.get_partition_keys()[-2:]
    stamps[ingest.OD_URL.format(year=old)] = "Sat, 03 Jan 2026 13:36:03 GMT"
    stamps[ingest.OD_URL.format(year=new)] = "Wed, 03 Jun 2026 12:35:02 GMT"

    def evaluate(cursor):
        ctx = build_sensor_context(cursor=cursor)
        reqs = list(definitions.bart_od_updates(ctx))
        return [r.partition_key for r in reqs], ctx.cursor

    first, cursor = evaluate(None)  # nothing seen yet: both years
    assert first == [old, new]
    assert evaluate(cursor)[0] == []  # same stamps: nothing to do
    stamps[ingest.OD_URL.format(year=new)] = "Wed, 14 Oct 2026 12:00:00 GMT"
    changed, cursor = evaluate(cursor)
    assert changed == [new]
    assert json.loads(cursor)[new] == "Wed, 14 Oct 2026 12:00:00 GMT"


def test_models_rebuild_after_ingest():
    from pipeline.definitions import defs

    sensors = {s.name: s for s in defs.sensors}
    assert sensors["bart_od_updates"].job_name == "yearly_ingest"
    assert sensors["models_after_ingest"].job_name == "refresh_reference_and_models"


def test_every_schedule_and_sensor_starts_running():
    # nothing on the VM ran until a person clicked "on" in the UI, and nobody did
    from dagster import DefaultScheduleStatus, DefaultSensorStatus

    from pipeline.definitions import defs

    assert all(s.default_status == DefaultScheduleStatus.RUNNING for s in defs.schedules)
    assert all(s.default_status == DefaultSensorStatus.RUNNING for s in defs.sensors)


def test_monthly_schedules_ingest_previous_months_year():
    # Lyft publishes a month's data early in the next month, so the January run must reload last year's
    # partition (to pick up December), not the new year's (which has nothing yet)
    import datetime as dt
    from zoneinfo import ZoneInfo

    from dagster import build_schedule_context

    from pipeline.definitions import baywheels_monthly

    pacific = ZoneInfo("America/Los_Angeles")
    cases = [
        (baywheels_monthly, dt.datetime(2027, 1, 7, 6, 30, tzinfo=pacific), "2026", "baywheels-2027-01"),
        (baywheels_monthly, dt.datetime(2026, 7, 7, 6, 30, tzinfo=pacific), "2026", "baywheels-2026-07"),
    ]
    for sched, when, year, run_key in cases:
        req = sched(build_schedule_context(scheduled_execution_time=when))
        assert (req.partition_key, req.run_key) == (year, run_key), (sched.name, when)
