# TransitPulse: current state

> **Scope of this file:** how the application works *right now*, and nothing else. No history, no plans.
> It is rewritten whenever behaviour changes. History lives in [`DEVLOG.md`](DEVLOG.md); the task list in
> [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
>
> **Last verified:** 2026-10-08, on Windows 11. Cloud resources exist (Terraform applied); no app is deployed.
> The Oracle VM deployment files exist but are not deployed.

---

## 1. What exists and runs

| Part | State | How to run |
|---|---|---|
| Website (static, `web/`) | **Working**: live train map, ridership tiles + charts, forecast explorer, Ask card UI | `uv run python tasks.py api` → http://localhost:8000 |
| API (`api/`) | **Working**: serves the site; data endpoints read the local DuckDB or BigQuery marts when a warehouse is configured; the agent endpoint answers 503 | same as above |
| Map data build (`pipeline/webdata/`) | **Working** | `uv run python tasks.py web-data` |
| Spark cleaning job (`pipeline/spark/`) | **Working** (Docker on Windows, native on Linux) | `uv run python tasks.py spark` |
| Bay Wheels download + cleaning (`pipeline/baywheels.py`) | **Working** (DuckDB, no Spark) | `uv run python tasks.py baywheels` |
| dbt warehouse models (`dbt/transitpulse/`) | **Working**: `local` (DuckDB) has BART + Bay Wheels; `dev` (BigQuery) has BART 2018–2025 (Bay Wheels models not built there) | `uv run python tasks.py stations` then `uv run python tasks.py dbt` (`DBT_TARGET=dev` for BigQuery) |
| Forecast (`ml/forecast/`) | **Working** locally (LightGBM, 14 days, every station) | `uv run python tasks.py forecast` |
| Dagster orchestration (`pipeline/definitions.py`) | **Working** in `local` and `gcp` mode, run from this PC | `uv run python tasks.py dagster` → http://localhost:3000 |
| Oracle VM deployment (`deploy/oracle/`) | **Files + runbook ready, not deployed** | [`ORACLE_VM.md`](ORACLE_VM.md) |
| Terraform (`infra/terraform/`) | **Applied** to GCP project `transitpulse-511002` (33 resources; `plan` = no changes) | see `infra/README.md` |
| CI (`.github/workflows/ci.yml`) | **Runs on GitHub** (python, spark, web, terraform jobs) | — |
| Causal analysis, agent, fine-tuning, BI reports, app deployment | **Not implemented** | — |

---

## 2. Data flow (local mode)

```
bart.gov GTFS zip ──► pipeline/webdata ──► web/data/{network,schedule,land}.json ──► browser map
        │
        └──────────► pipeline/stations ──► data/parquet/bart_stations/stations.csv ─┐
                                                                                     ▼
bart.gov OD CSV.gz ─► data/raw/bart_od/ ─► Spark clean_bart_od ─► data/parquet/bart_od/year=/month=/*.parquet
                                                                                     │
S3 baywheels-data ──► data/raw/baywheels/*.zip ─► DuckDB clean ─► data/parquet/baywheels_trips/year=/month=/
                                                                                     │
                                       dbt (DuckDB, data/transitpulse.duckdb) ◄──────┘
                                       staging ─► snapshot ─► core (dims/facts) ─► marts
                                                                                     │
                       ml/forecast ◄── marts.fct_station_daily       API (read-only) ◄┘
                            └──► marts.forecast_station_daily + ml.forecast_runs ──► API ──► site
```

- Everything under `data/` is generated and gitignored. `web/data/*.json` is generated **and committed**
  (the site needs it to run).
- In `gcp` mode (`TP_PIPELINE_MODE=gcp`, `DBT_TARGET=dev`) the same assets upload to GCS
  (`gs://transitpulse-511002-raw`) and load BigQuery (`raw.bart_od`, `raw.bart_stations`, and the code path for
  `raw.baywheels_trips`); dbt then builds `staging` and `marts` in BigQuery, and the forecast asset writes its two
  tables to BigQuery. Spark runs are queued one at a time (`pipeline/dagster.yaml`).
- Years BART hasn't published yet (currently 2026: an empty gzip) are skipped: the three yearly assets succeed with
  `published: false` and a warning.

### Data currently loaded
| Dataset | Where | Coverage | Size |
|---|---|---|---|
| BART hourly origin-destination | **BigQuery** `raw.bart_od` → `marts.*` | 2018–2025 (2020 is missing 4 days in BART's file) | 67,770,440 rows; 4.2 GB logical |
| BART hourly origin-destination | local DuckDB facts/marts | 2019 and 2025 (the local Parquet also holds 2018–2025; the incremental fact only loaded 2019 + 2025) | 19,257,542 rows in `fct_trips_hourly` |
| Bay Wheels trips | local Parquet / DuckDB (`stg_baywheels_trips`) | 2019 (Ford GoBike schema) and 2025 (Lyft schema) | 6,901,983 trips (2,506,867 + 4,395,116); 236 MB Parquet |
| Bay Wheels trips | BigQuery | **none** (load code exists, not run) | — |
| Station forecast | local DuckDB `marts.forecast_station_daily`, `ml.forecast_runs` | 2026-01-01 → 2026-01-14 (from data through 2025-12-31), 50 stations | 700 rows; 1+ run rows |
| BART GTFS | web/data, `raw.bart_stations` | feed version 72 (service 2026-08-10 → 2027-01-10) | 50 stations, 3,762 rail trips |

---

## 3. The website

### Page (single page, `web/index.html`)
1. **Nav**: sticky; links + "Ask a question" pill. Below 1120 px the links move into a full-screen menu
   (focus trapped, Esc closes, body scroll locked). Below 600 px the CTA becomes a search icon.
2. **Hero + Ask card**: question input, 4 suggestion chips, Ask button. Submitting POSTs to `/api/ask`; because the
   agent isn't connected, the page shows "The analyst isn't connected yet…". The client also handles a streamed
   (SSE) answer, refusals, rate limits (429) and network errors, but no server produces those yet.
3. **Live map** (see below).
4. **Trends** (`web/js/trends.js`, see below).
5. **Forecast** explorer (`web/js/forecast.js`, see below).
6. **Findings** (black band): heading + "analysis is in progress".
7. **About**: three FAQ rows (`<details>`).
8. **Footer**: data sources with licences (Bay Wheels links its Data License Agreement), GitHub link, credits.

### Trends band
- Loads `/api/kpis`, `/api/trends/ridership` and (in parallel, optional) `/api/trends/bikes-vs-trains`.
- **While loading:** skeletons of the final size; tiles and charts don't shift when the data arrives.
- **"Data through Dec 31, 2025. Tiles cover the 28 days to that date."** (caption, `mute`).
- **Four `stat-tile`s** (`auto-fit` grid: 1 column on phones, 4 on desktop), each with a value, a delta line and an
  ⓘ button that reveals the definition:
  - Recovery vs 2019
  - Average daily entries (▲/▼ % vs a year earlier, when that year is loaded)
  - Peak-hour share (▲/▼ pts vs the same ISO weeks of 2019)
  - Busiest station (+ its share of entries)

  Deltas use ink arrows, never green/red. Locally: 38%, 115,501, 10.9% (▼ 0.9 pts vs 2019), Powell Street (9.9%).
- **"Ridership since 2019"** chart card: monthly average daily entries as an inline SVG sized to its container
  (re-drawn on resize; 3 y-ticks and every other year below 600 px). The line breaks at months with no data
  (locally 2020–2024). A takeaway sentence sits above it and a visually hidden table holds the numbers.
- **"Bikes and trains"** chart card: BART entries per day (solid black) and Bay Wheels trips per day (dashed grey),
  each as % of the same month in 2019. The legend names both; below 600 px card width it moves under the chart.
- **States:**
  - 503 → "Ridership numbers will appear here once the data pipeline is connected." (info message).
  - Any other failure → error message + Retry.
  - Empty marts → one-sentence message.
  - Bike data missing (404) → only the bikes card shows a message; the BART parts stay.

### Forecast explorer
- **Station picker:** an ARIA combobox matching names or codes ("mac" → MacArthur, "12" → 12th St Oakland).
  ↑/↓ moves through the options, Enter picks, Esc closes the list. Below it, chips for Embarcadero, Montgomery St,
  Powell St, 12th St Oakland and MacArthur (the selected chip is outlined). Embarcadero loads by default.
- **Chart card:** station name; a caption about the first Tuesday in the forecast ("Expect about 11,400 entries on
  Tue, Jan 6, likely between 10,100 and 14,100"); the last 28 days of actuals (solid), the 14-day p50 forecast
  (dashed) and the p10–p90 band (`interval-fill`); a visually hidden table of the 14 days.
- **Source line:** "Forecast from data through Dec 31, 2025.", the model's back-test error vs the baseline's, and the
  measured interval coverage. It says plainly that the range is too narrow (48% of days instead of 80%).
- **Layout:** picker beside the chart from 768 px; stacked on phones.
- **States:**
  - 503 → "Forecasts will appear here once the forecasting model has run."
  - 404 → "There's no forecast for X yet." + "Try another station", which focuses the search box.
  - Other errors → Retry.

### Live map: how it works
- **Data**: `network.json` (50 stations, 51 track edges with their lines in lane order, label hints),
  `schedule.json` (11 service calendars, 34 stop patterns, 55 timing profiles, 3,762 trips, in minutes),
  `land.json` (Bay Area land polygons). 88 KB total.
- **Positions are scheduled, not live.** For the current Pacific time, `schedule.js` picks the services running on
  that date (weekday rules + holiday exceptions), includes the previous day's after-midnight trips, and interpolates
  each running trip linearly in time between its departure and next arrival. Trains dwell at stations between
  arrival and departure.
- **Rendering**: the SVG (land, track, stations, labels) and the canvas (trains) share one pixel coordinate space
  sized to the container. A `ResizeObserver` re-fits the network on every size change and resizes the canvas to
  container × `devicePixelRatio`.
- **Shared track** is drawn as parallel lanes (fixed order: yellow, red, green, blue, orange, airport), each line
  offset to the west/south side by lane index. Each train sits in its own line's lane.
- **Trains**: pills filled with the line colour, 1 px ink outline, pointing along the track. Length =
  `clamp(6px, 1.2% of map width, 14px)`. The selected train is 1.5× with an ink halo.
- **Stations**: white circles; on maps ≥ 600 px wide, transfer stations are capsules spanning all lanes.
- **Labels**: below 600 px map width only 9 hub stations are labelled. Above that, labels are placed greedily and
  any that would overlap a label, station or track are left out (reachable by hover/tap and the List view).
- **Map shape**: 1:1 on phones, 4:3 from 768 px, 16:9 from 1120 px, never taller than 80% of the viewport.
- **Controls**: clock ("8:15 AM · Wed, Oct 7 · Live schedule"; time only on narrow maps); Map/List toggle; zoom −/+
  (5 levels; drag to pan when zoomed); Now (live); time scrubber 4:00 AM → 2:30 AM; replay speed 1×/10×/60×;
  play/pause. Floating over the map when the map is ≥ 720 px wide, stacked under it otherwise.
- **Interaction**: hover (mouse) or tap shows a tooltip. Train: "Yellow line to SFO Airport / Next: 16th St Mission ·
  2 min". Station: name + lines and, once its summary has loaded (one request per station, cached in the page),
  "Entries on Dec 31, 2025: 4,956 (17% of 2019)". With no warehouse (503) or on an error there's no numbers line.
  Tap elsewhere to dismiss.
- **List view**: table of running trains (line, destination, next stop, minutes), refreshed every 5 s.
- **Out of service** (current feed: last train ends 1:52 AM; first departs 4:28 AM weekdays, 5:28 AM Saturdays,
  7:28 AM Sundays): a card says when service resumes, with *Jump to 8:00 AM*.
- **Performance**: redraws ~4×/s at 1×, ~20×/s at 10×, every frame at 60×; stops while off-screen or in a hidden tab.
- **Accessibility**: a polite live region announces "N trains running on K lines at h:mm" once a minute; reduced
  motion → positions update every 30 s with no animation; all controls are buttons ≥ 44 px on touch; skip link.
- **Failure**: if the map data can't load, the map area shows an error message with Retry.

### Design system
`web/css/tokens.css` mirrors `docs/DESIGN.md` **v1.0.1** (frozen). Black/white interface; line colours only in data
marks; Inter 400/500/700; pills for controls, 16 px cards. Chart, trends and forecast styles are in
`web/css/charts.css`. Deviations awaiting v1.1 are listed in `DESIGN_BACKLOG.md`.

---

## 4. API (`api/`)

| Method | Path | Current behaviour |
|---|---|---|
| GET | `/` and static files | serves `web/`. Cache: `/fonts/*` 1 year, `/data/*` 1 day, everything else `no-cache` |
| GET | `/healthz` | `{"ok": true}` |
| GET | `/api/kpis` | `{data_through, window:{start,end,days}, tiles:[{id,label,value,unit,delta,delta_label,definition}], source}` over the 28 days ending at the latest date in `mart_kpis_daily` |
| GET | `/api/trends/ridership` | `{data_through, rows:[{month_start, days, avg_daily_entries, avg_service_weekday_recovery}], source}` from `mart_ridership_monthly` |
| GET | `/api/trends/bikes-vs-trains` | `{rows:[{month_start, bart_entries, bike_trips, bart_avg_daily_entries, bike_avg_daily_trips, bart_index_2019, bike_index_2019, bikes_per_1000_bart_entries}], source}`; 404 `data_not_available` if the mart doesn't exist |
| GET | `/api/stations/{code}/summary` | `{code, name, data_through, entries, recovery_ratio, avg_weekday_entries_28d, peak_hour, peak_hour_share}` for the station's latest day |
| GET | `/api/forecast/{code}` | `{code, name, data_through, generated_at, forecast:[{date,p10,p50,p90}] ×14, actuals:[{date,entries}] ×28, model:{mae, baseline_mae, mae_diff_ci, interval_coverage}}`; 404 `forecast_not_available` if there's no forecast for a known station |
| POST | `/api/ask` | body `{"question": str (1–300)}` → **503** `{"code": "agent_unavailable"}` (501 if `TP_AGENT_ENABLED=true`) |
| GET | `/api/docs` | OpenAPI UI |

- Every data endpoint answers **503** `{"code": "warehouse_not_connected"}` when no warehouse is configured.
  Codes that don't match `^[A-Z0-9]{4}$` or aren't in the data get **404** `{"code": "unknown_station"}`.
  Errors are under `detail` (FastAPI's format).
- **Warehouse** (`api/warehouse.py`), chosen by `TP_WAREHOUSE`:
  - `none` (default): no warehouse; every data endpoint answers 503. If `TP_WAREHOUSE` is unset but
    `TP_GCP_PROJECT` is set, the default is `bigquery`.
  - `duckdb`: reads `TP_DUCKDB_PATH` (default `data/transitpulse.duckdb`, relative to the repo). A read-only
    connection is opened per query and closed straight away.
  - `bigquery`: reads `` `TP_GCP_PROJECT.marts.*` `` with typed query parameters, a 100 MB `maximum_bytes_billed`
    cap per query and location `us-west1`.

  The app never looks for the DuckDB file on its own; `tasks.py api` sets `TP_WAREHOUSE=duckdb` when the file exists.
- **Cache** (`api/cache.py`): results are kept in memory per warehouse + endpoint + arguments, for 1 h (KPIs,
  trends, stations) or 6 h (forecasts). Errors are not cached.
- On Windows, a running API briefly locks `data/transitpulse.duckdb` during each query; stop it before a full
  `dbt build` or forecast run if they report the file as locked.

Configuration: environment variables with prefix `TP_` (`api/settings.py`).

---

## 5. Pipeline

### Spark job (`pipeline/spark/clean_bart_od.py`)
Input: headerless CSV(.gz) `date,hour,origin,destination,trips`. Every row is tagged with a drop reason or kept:
`malformed_row`, `bad_date`, `bad_hour` (not 0–23), `bad_origin` / `bad_destination` (not 4 alphanumerics),
`bad_trips`, `non_positive_trips`, `duplicate` (same date/hour/origin/destination; the latest source file wins).
Kept rows get `weekday` (1 = Sunday), `is_holiday`/`holiday` (US federal), and are written as Parquet partitioned
by `year`/`month`, replacing only the months present. Writes `audit.json` (rows in/out, drops per reason).
Local mode needs ~4 GB driver memory for two years.

### Bay Wheels (`pipeline/baywheels.py`)
- **Discovery:** monthly zips are found by listing the public bucket (`s3.amazonaws.com/baywheels-data`) and matching
  keys that start with `YYYYMM-`, whatever the rest of the name. The yearly 2017 file is ignored; missing months
  (2020-04, 2024-12) simply have no file.
- **Download:** skipped when ETag + size match `data/raw/baywheels/manifest.json` (which also stores the sha256).
- **Cleaning (DuckDB):** each month is read with an explicit all-text schema from its header, and the two source
  schemas (Ford GoBike "legacy", Lyft) are normalised to one:
  - Columns: `ride_id`, `started_at`, `ended_at`, `duration_sec`, start/end station id + name, start/end lat/lng,
    `rideable_type`, `member_type`, `trip_date`, `source_file`, `schema_version`.
  - Legacy rows: `ride_id` is an md5 of the source fields; Subscriber/Customer → member/casual; bike type `unknown`.
  - Drop reasons: `malformed_row`, `bad_timestamp`, `non_positive_duration`, `over_24h`, `missing_coordinates`,
    `outside_bay_area`, `outside_file_month`, `duplicate`.
- **Output:** `data/parquet/baywheels_trips/year=/month=/part-0.parquet` (only the months processed are replaced)
  and `data/parquet/baywheels_audit/year=YYYY/audit.json`.

### dbt models (`dbt/transitpulse/`)
| Layer | Models | Materialization |
|---|---|---|
| staging | `stg_bart_od`, `stg_bart_stations`, `stg_baywheels_trips` | views |
| snapshot | `snap_bart_stations` (SCD2, check strategy on name/lat/lon) | snapshot |
| core | `dim_station` (SCD2, first version back-dated to 1900), `dim_date`, `fct_trips_hourly` (incremental, last 35 days re-processed), `fct_station_daily`, `fct_bike_trips_daily` | tables |
| marts | `mart_recovery`, `mart_peak_load`, `mart_od_flows`, `mart_kpis_daily`, `mart_ridership_monthly`, `mart_bikes_vs_trains` | tables |

68 data tests. KPI definitions: `docs/METRICS.md`. Targets:
- `local` (DuckDB, default): 83/83 pass, ~5.5 min. Needs the Bay Wheels Parquet: the source glob fails with no files.
- `dev` (BigQuery): the BART models are built over 2018–2025; the Bay Wheels models aren't.
- `ci`: never run.

On BigQuery, facts are partitioned by `trip_date` (and the BART facts clustered by station), and queries are capped
at 20 GB billed in `dev` / 500 MB in `ci` (`maximum_bytes_billed`). The forecast tables are written by
`ml/forecast`, not dbt; dbt leaves them alone.

### Forecast (`ml/forecast/`)
- **Input:** `marts.fct_station_daily` (daily entries per station).
- **Model:** one global LightGBM per quantile (p10, p50, p90). Rows are (station, forecast origin t, horizon 1–14),
  and every feature uses only data up to t:
  - last value, previous day and 7-day mean;
  - the seasonal-naive value and the mean of the last 4 same weekdays;
  - 28-day coefficient of variation;
  - horizon, target weekday and month, and US federal holiday flags for the target day, its neighbours and the
    naive reference day;
  - station (categorical).

  Values are scaled by the station's 28-day mean, so one model fits busy and quiet stations. Predictions are sorted
  (p10 ≤ p50 ≤ p90) and clipped at 0. Rows whose 28-day history has a missing day are dropped.
- **Baseline:** seasonal naive, i.e. the last observed value on the target's weekday at or before the origin.
- **Validation:** walk-forward with 6 folds, origins every 14 days, the last one 14 days before the end of the data.
  Each fold trains only on targets dated at or before its origin, within a 730-day window. Errors are pooled over
  folds, stations and horizons; a paired bootstrap over stations (B = 1000, seed 0) gives 95% CIs.
- **Latest local run (data through 2025-12-31):**

  | | LightGBM | Seasonal naive |
  |---|---|---|
  | MAE | **364.9** [277.1, 470.1] | 548.5 [416.9, 698.2] |
  | RMSE | 819.3 [548.2, 1080.2] | 1246.7 [857.4, 1630.2] |

  MAE improvement 183.7 [139.5, 234.1]. p10–p90 coverage **0.475** [0.458, 0.493], against 0.80 nominal: the
  intervals are too narrow.
- **Output:**
  - `marts.forecast_station_daily` (replaced each run): `run_id, generated_at, station_code, forecast_date,
    horizon_day, p10, p50, p90`.
  - `ml.forecast_runs` (appended): run id, timestamps, `data_through`, training window, folds, horizon, stations,
    every metric with `_lo`/`_hi` bounds, coverage, `params_json`, `fold_metrics_json`, duration.
- **CLI:** `python -m ml.forecast.run [--warehouse duckdb|bigquery] [--duckdb-path] [--horizon 14] [--folds 6]
  [--seed 0] [--train-days 730] [--bootstrap 1000]`.

### Dagster (`pipeline/definitions.py`)
- **Assets:**
  - `bart_gtfs`, `bart_stations_raw`, `web_map_data`.
  - `bart_od_files` → `bart_od_parquet` → `raw/bart_od` and `baywheels_files` → `baywheels_parquet` →
    `raw/baywheels_trips` (static yearly partitions 2018 → current year).
  - Every dbt model/snapshot as an asset (group `warehouse`).
  - `forecast_station_daily` (group `ml`, downstream of `marts/fct_station_daily`).
- **Jobs and schedules** (Pacific time):

  | Job | Schedule | What it does |
  |---|---|---|
  | `yearly_ingest` | 6th of each month, 06:00 | current year's BART partition |
  | `baywheels_ingest` | 7th of each month, 06:30 | current year's Bay Wheels partition |
  | `refresh_reference_and_models` | 6th of each month, 08:00 | GTFS, stations, map data, `dbt build` |
  | `weekly_forecast` | Mondays, 09:00 | retrain and publish the forecast |
- **Resources:** `Storage` (`local` | `gcp`), `SparkRunner` (`python` | `docker`), `DbtCliResource`.
- Runs locally against `.dagster_home/` (gitignored), started by `tasks.py dagster`, which includes the `ml` group.

### Oracle VM (`deploy/oracle/`, not deployed)
- Two systemd units: `transitpulse-dagster-daemon` (schedules) and `transitpulse-dagster-web` (UI on 127.0.0.1,
  reached by SSH tunnel).
  - Both run as the non-root `transitpulse` user from `/opt/transitpulse`, with the venv first on `PATH`.
  - Environment from `/etc/transitpulse/transitpulse.env` (mode 600). The key file is
    `/etc/transitpulse/sa-pipeline-key.json` (owner `transitpulse`, 600).
  - Memory caps `MemoryMax` 7 G (daemon, includes a Spark run) / 1 G (UI), `Nice=10` and `OOMScoreAdjust=500`,
    so SeismicSoCal keeps priority and is not the one killed if memory runs out.
  - Sized for a 2 OCPU / 12 GB VM (the Always Free maximum): `TP_SPARK_DRIVER_MEMORY=4g`, `TP_ML_THREADS=2`,
    `DBT_THREADS=2` in the env file. The current SeismicSoCal VM is 1 OCPU / 5.8 GiB with 3.2 GiB available, which
    is too small for a Spark run; the runbook says to resize it to 2 / 12 first.
- `bootstrap.sh` installs and updates everything (apt or dnf, Java 17, uv, `uv sync --frozen`, `dbt parse`). It
  starts the services only once the key is in place. Steps are in [`ORACLE_VM.md`](ORACLE_VM.md).

---

## 6. Tests

| Suite | Command | Count | Status |
|---|---|---|---|
| Python unit (map data, API data endpoints, Bay Wheels cleaning, dbt build on a generated fixture, forecast, Dagster definitions, VM files) | `uv run --group dbt --group ml --group pipeline pytest -m "not spark and not gcp and not localdata"` | 42 | pass (~1.5 min) |
| Local warehouse (real data) | `uv run --group dbt --group ml pytest -m localdata tests/local` | 5 | pass (needs `data/transitpulse.duckdb` with Bay Wheels + forecast) |
| Spark job | in Docker: `docker run --rm -v "$PWD:/app" transitpulse-spark python -m pytest tests/spark -m spark` | 1 | pass (auto-skipped on Windows outside Docker) |
| Browser maths (schedule, chart helpers, station search) | `node --test tests/web/` | 13 | pass |
| Browser (Playwright, Chromium; API mocked for data tests) | `npx playwright test` | 27 | pass |
| dbt data tests | `uv run python tasks.py dbt` | 68 (+15 models/snapshot) | pass |
| Shellcheck (VM bootstrap) | `docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable deploy/oracle/bootstrap.sh` | — | clean |
| ARM wheels (pipeline, dbt, ml groups) | `uv pip compile pyproject.toml --group pipeline --group dbt --group ml --python-platform aarch64-manylinux_2_28 --python-version 3.12 --only-binary :all:` | — | resolves |
| Lint/format | `uv run ruff check . && uv run ruff format --check .` | — | clean |
| Terraform | `terraform validate` / `fmt -check` / `plan` | — | clean; plan shows no changes |

---

## 7. Known limitations (current behaviour)
- Train positions follow the timetable; delays and disruptions are not shown.
- Local DuckDB has BART for 2019 and 2025 only, so year-over-year deltas and the forecast's training data are
  limited to 2025. BigQuery has BART 2018–2025 but no Bay Wheels and no forecast tables yet.
- `mart_kpis_daily.rolling_28d_avg_entries` is a 28-row window and spans date gaps (locally, the 2020–2024 gap).
  The API doesn't use it.
- The forecast's p10–p90 range held 48% of days in back-testing (nominal 80%). With one contiguous year of training
  data, holidays the model hasn't seen (e.g. New Year's Day) are badly forecast.
- The forecast covers the 14 days after the latest published data (currently 2026-01-01 → 14), not the next two
  weeks from today; the site says "forecast from data through".
- On Windows, Spark runs only through Docker.
- No app is deployed. GCP has the warehouse (raw → marts), bucket, registry, service accounts and $1/$5 budget
  alerts. The Oracle VM files are ready but not installed.
