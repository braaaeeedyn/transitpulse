# TransitPulse: current state

> **Scope of this file:** how the application works *right now*, and nothing else. No history, no plans.
> It is rewritten whenever behaviour changes. History lives in [`DEVLOG.md`](DEVLOG.md); the task list in
> [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
>
> **Last verified:** 2026-10-10, on Windows 11. **Live at https://braedynthompson.com/transitpulse/**: the pages are
> published by the portfolio's GitHub Pages (`portfolio/static/transitpulse/`, exported with `tasks.py export
> --api-base`) and call the API on Cloud Run (https://transitpulse-api-etumz4pfva-uw.a.run.app) across origins
> (CORS allows `https://braedynthompson.com`). The Dagster pipeline runs on the Oracle VM against BigQuery.

---

## 1. What exists and runs

| Part | State | How to run |
|---|---|---|
| Website (static, `web/`) | **Working**: live train map, ridership tiles + charts, forecast explorer, Ask card UI | `uv run python tasks.py api` → http://localhost:8000 |
| API (`api/`) | **Working**: serves the site; data endpoints read the local DuckDB or BigQuery marts when a warehouse is configured; `POST /api/ask` streams the agent's answer when `TP_AGENT_ENABLED=true`, 503 otherwise (the default) | same as above |
| Ask TransitPulse agent (`api/agent/`) | **Working** locally: LangGraph text-to-SQL with guardrails, fake / Ollama / Gemini LLM, optional Langfuse | `TP_AGENT_ENABLED=true TP_AGENT_LLM=ollama uv run --group agent python tasks.py api` |
| Agent eval (`eval/`) | **Working**: 66 in-scope questions with gold SQL + 10 out-of-scope | `uv run python tasks.py eval [--llm ollama]` |
| Map data build (`pipeline/webdata/`) | **Working** | `uv run python tasks.py web-data` |
| Spark cleaning job (`pipeline/spark/`) | **Working** (Docker on Windows, native on Linux) | `uv run python tasks.py spark` |
| Bay Wheels download + cleaning (`pipeline/baywheels.py`) | **Working** (DuckDB, no Spark) | `uv run python tasks.py baywheels` |
| dbt warehouse models (`dbt/transitpulse/`) | **Working**: `local` (DuckDB) has BART + Bay Wheels; `dev` (BigQuery) has BART 2018–2025 and Bay Wheels 2018 → 2026-09 | `uv run python tasks.py stations` then `uv run python tasks.py dbt` (`DBT_TARGET=dev` for BigQuery) |
| Forecast (`ml/forecast/`) | **Working** locally and on BigQuery (LightGBM, 14 days, every station, split-conformal calibrated band) | `uv run python tasks.py forecast` |
| Dagster orchestration (`pipeline/definitions.py`) | **Working** in `local` and `gcp` mode, run from this PC | `uv run python tasks.py dagster` → http://localhost:3000 |
| Oracle VM deployment (`deploy/oracle/`) | **Running**: Dagster daemon + UI on the VM (2 OCPU / 12 GB), schedules on, `gcp` mode | [`ORACLE_VM.md`](ORACLE_VM.md) |
| Terraform (`infra/terraform/`) | M0 **applied** to GCP project `transitpulse-511002` (33 resources). `cloudrun.tf` + `wif.tf` (10 more resources) are **validated, not applied** | see `infra/README.md` |
| Container image (`Dockerfile`) | **Builds and passes its smoke tests locally** (non-root, 119 MB compressed); never pushed | `uv run python tasks.py image` |
| Cloud Run service `transitpulse-api` (us-west1) | **Live** (Terraform applied; image `api:manual-2dd730f`, deployed by hand). Ask agent off (`/api/ask` → 503) | [`CLOUD_RUN.md`](CLOUD_RUN.md) |
| Cloud Run deploy (`.github/workflows/deploy.yml`) | **Off** until the `DEPLOY_ENABLED` repo variable is `true` (the WIF pool/provider exist) | [`CLOUD_RUN.md`](CLOUD_RUN.md) |
| Pages at braedynthompson.com/transitpulse/ | **Live**: the portfolio repo publishes `static/transitpulse/`; re-export only when the website code changes | [`CLOUD_RUN.md`](CLOUD_RUN.md) §5 |
| Load test (`load/`) | **Working** locally: Locust at 1/10/25 users on a fixture warehouse with the fake LLM | `uv run python tasks.py load` |
| CI (`.github/workflows/ci.yml`) | **Runs on GitHub** (python, spark, web, container, terraform jobs) | — |
| Causal analysis, fine-tuning, BI reports | **Not implemented** | — |

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
| BART hourly origin-destination | local DuckDB facts/marts | 2018–2025, the same as BigQuery (2020 is missing 4 days) | 67,770,440 rows in `fct_trips_hourly`; 143,958 in `fct_station_daily`; `data/transitpulse.duckdb` 369 MB |
| Bay Wheels trips | local Parquet / DuckDB (`stg_baywheels_trips`) | 2019 (Ford GoBike schema) and 2025 (Lyft schema) | 6,901,983 trips (2,506,867 + 4,395,116); 236 MB Parquet |
| Bay Wheels trips | BigQuery `raw.baywheels_trips` → `marts.fct_bike_trips_daily`, `mart_bikes_vs_trains` | 2018 → 2026-09 | 25,989,969 trips; 3,165 days; 105 months |
| Station forecast | local DuckDB `marts.forecast_station_daily`, `ml.forecast_runs` | 2026-01-01 → 2026-01-14 (from data through 2025-12-31, trained on 2024-01-02 → 2025-12-31), 50 stations, with `lower`/`upper` | 700 rows; run `fc-20261009T131810Z-a3cda6` is the latest |
| Station forecast | BigQuery `marts.forecast_station_daily`, `ml.forecast_runs` | same window; written by the VM's weekly run with the pre-calibration code (p10/p50/p90 only) until the VM pulls this code | 700 rows |
| BART GTFS | web/data, `raw.bart_stations` | feed version 72 (service 2026-08-10 → 2027-01-10) | 50 stations, 3,762 rail trips |

---

## 3. The website

### Page (single page, `web/index.html`)
1. **Nav**: sticky; links + "Ask a question" pill. Below 1120 px the links move into a full-screen menu
   (focus trapped, Esc closes, body scroll locked). Below 600 px the CTA becomes a search icon.
2. **Hero + Ask card**: question input, 4 suggestion chips, Ask button. Submitting POSTs to `/api/ask` and reads
   the streamed answer (`web/js/ask.js`):
   - Progress steps are listed as `thinking` / `sql` / `rows` / `answer` events arrive; the answer renders as a
     heading (focused), a table and a "Show SQL" disclosure.
   - A refusal shows its message and suggestion chips (a chip asks its question); an `error` event shows the message.
   - 503 → "The analyst isn't connected yet…" (the default: the agent is off); 429 → "Lots of questions right now";
     other 4xx (e.g. 422) → "That question couldn't be read…"; 5xx → "The analyst ran into a problem…"; a failed
     request → "Check your connection"; a dropped stream or one that ends without answer/refusal/error → an error
     message instead of a half-finished step list.
   - The stream parser follows the SSE spec: LF, CRLF or CR line ends, multi-line `data:` joined with a newline,
     comment lines ignored, chunks split anywhere.
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
- **Chart card:** station name; a caption about the first Tuesday in the forecast, with the year and in the past
  tense ("For Tue, Jan 6, 2026 the model expected about 14,200 entries; calibrated model range
  10,500–16,800."); the last 28 days of actuals (solid), the 14-day p50 forecast (dashed) and the published band
  (`lo`–`hi` from the API, `interval-fill`); a legend; a visually hidden table of the 14 days (with the year).
- **What the band is called** depends on the API's `model.interval`:
  - calibrated and held 75–85% of back-test days → "80% range";
  - calibrated but outside 75–85% → "calibrated model range" (the drawn `lo`/`hi` are p10/p90 widened, so it is
    never called the 10th–90th percentile); the source line says "the calibrated model range (the model's
    10th–90th percentile, widened using earlier back-test weeks)" and the hidden table's headers are "Calibrated
    model range: low/high";
  - not calibrated → "model range (10th–90th percentile)".

  The caption, legend, table headers and the chart's text alternative all use the same label. Locally (calibrated,
  73%) it is the calibrated model range; production (uncalibrated, 70%) is the model range (10th–90th percentile).
- **Source line:** "Forecast from data through Dec 31, 2025. It covers Jan 1–14, 2026, the 14 days after the latest
  ridership BART has published.", the model's back-test error vs the baseline's, then what the band is and how often
  it held the actual value against the 80% target, adding "so it is narrower than it should be" below 75% or "so it
  is wider than needed" above 85%.
- **Section heading:** "A 14-day forecast, station by station" (it doesn't say "from today").
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
- **Outside the timetable** (before the first service's start or after the last one's end, counting added dates;
  the bundled feed ends **Jan 10, 2027**): the card says "This site's BART timetable ended on Jan 10, 2027. Positions
  can't be shown until it's updated." (or "starts on …"), without the Jump button.
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
| GET | `/api/forecast/{code}` | `{code, name, data_through, forecast_start, forecast_end, generated_at, forecast:[{date,p10,p50,p90,lo,hi}] ×14, actuals:[{date,entries}] ×28, model:{mae, baseline_mae, mae_diff_ci, interval_coverage, interval:{method, nominal, coverage, coverage_ci, calibrated}}}`; 404 `forecast_not_available` if there's no forecast for a known station. Reads both forecast-table schemas (see Forecast below); every run-log column is optional (missing → `null`, `mae_diff_ci` is `null` unless both bounds exist) |
| POST | `/api/ask` | body `{"question": str (1–300)}`. Agent off (default): **503** `agent_unavailable`. On: `text/event-stream` (below); **429** `rate_limited` (with `Retry-After: 60`) or `agent_busy` before the stream starts; 422 for an empty/too-long question |
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

### Ask TransitPulse (`api/agent/`, `api/routes/ask.py`)
- **Off by default.** `TP_AGENT_ENABLED=true` turns it on; only then are the agent packages (`agent` dependency
  group: LangGraph, LangChain, sqlglot) imported, so the rest of the API runs without them.
- **Stream:** `fastapi.sse`, LF-delimited, `event:` + one JSON `data:` line each:
  `thinking {message}` → `sql {sql}` → `rows {count, columns}` → `answer {text, columns, rows (lists), sql}`, or
  `thinking` → `refusal {message, suggestions ×3}`, or an `error {code, message}` at any point. Every run ends with
  exactly one of answer / refusal / error.
- **Graph** (`graph.py`, LangGraph `StateGraph`):
  - `route`: a keyword pre-filter refuses requests to change data, prompt-injection phrases and secrets; otherwise
    the LLM answers `sql`, `forecast` or `refuse`.
  - `sql`: the LLM writes BigQuery Standard SQL against `marts.<table>` → guardrails → dry run → execute. A rejected
    or failed query is retried **once** with the error in the prompt; a second failure ends with `error`
    (`sql_rejected`, `query_failed` or `too_expensive`).
  - `forecast`: finds the station (4-letter code or the longest station name in the question) and runs a fixed query
    on the latest `forecast_station_daily` run (date, p50, p10, p90); no station → a refusal asking which one.
  - `answer`: the LLM writes 1–3 sentences from the first 20 rows; the payload carries the SQL that ran.
- **Guardrails** (`guardrails.py`, sqlglot, BigQuery dialect): exactly one SELECT / WITH / set operation; no
  DML/DDL, `SELECT INTO`, `COPY`, `PRAGMA`, `SET`, `ATTACH`, `EXPORT`…; tables only from the allowlist
  (`marts.dim_date, dim_station, fct_station_daily, fct_bike_trips_daily, mart_kpis_daily, mart_recovery,
  mart_peak_load, mart_od_flows, mart_ridership_monthly, mart_bikes_vs_trains, forecast_station_daily` and
  `ml.forecast_runs`; not `fct_trips_hourly`), no other projects, `INFORMATION_SCHEMA`, table functions or file
  readers. `LIMIT` is added or clamped to `TP_AGENT_ROW_LIMIT` (200), then the SQL is transpiled to the warehouse's
  dialect with tables qualified (`` `project.marts.x` `` on BigQuery).
- **Execution** (`api/warehouse.py`): DuckDB uses a read-only connection with `enable_external_access=false` and a
  locked configuration, `EXPLAIN` as the dry run and an interrupt after `TP_AGENT_TIMEOUT_S` (20 s). BigQuery dry-runs
  (no cache) and refuses over `TP_AGENT_MAX_BYTES` (1 GB), then runs with that as `maximum_bytes_billed` and
  `job_timeout_ms` = `TP_AGENT_TIMEOUT_S`, so BigQuery stops the job itself; if the client-side wait times out the
  job is also cancelled and it counts as a failed query ("The query took longer than 20 s."; retried once, then
  `query_failed`).
- **Limits:** `TP_AGENT_RATE_PER_MIN` (10) questions per client IP per minute, in memory (above 10,000 tracked
  IPs, every IP with no hit in the last minute is forgotten); the IP is
  `request.client.host`, or the right-most `X-Forwarded-For` entry only with `TP_TRUST_PROXY=true`. A per-process
  daily budget of warehouse bytes (`TP_AGENT_DAILY_BYTES`, 10 GB, resets at UTC midnight): spent → 429 `agent_busy`
  before streaming, or an `agent_busy` error if a query would exceed it.
- **LLM** (`llm.py`, `TP_AGENT_LLM`): `fake` (default; deterministic test double with a few canned queries),
  `ollama` (`TP_OLLAMA_MODEL` llama3.1:8b at `TP_OLLAMA_URL`), `gemini` (`TP_GEMINI_MODEL`, key from
  `GOOGLE_API_KEY`).
- **Tracing** (`tracing.py`): Langfuse v4 callback only when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set;
  otherwise langfuse isn't imported.
- **Eval** (`eval/`): `questions.yaml` has 66 in-scope questions (tags kpi, station, trend, bikes, forecast, od) with
  BigQuery-dialect gold SQL and 10 that must be refused. `python -m eval.run_eval --llm fake|ollama|gemini
  --warehouse duckdb [--duckdb-path] [--ids] [--json] [--save-summary] [--results-dir]` scores execution accuracy
  (`eval/scoring.py`, defined in `docs/METRICS.md`), refusal accuracy, guardrail rejections and latency, and writes
  the per-question detail to `eval/results/` (gitignored). `summary-<llm>-<ts>.json` (committed) is written only
  with `--save-summary`; the one committed summary is `summary-ollama-20261009T143938Z.json`. `--llm fake` is an oracle (1.0 by
  construction). **llama3.1:8b on the local DuckDB: execution accuracy 0.27 (18/66), refusal accuracy 1.0,
  0 guardrail rejections, 11 failed queries, 7 in-scope questions refused, p50 2.4 s / p95 6.4 s.**

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
| core | `dim_station` (SCD2, first version back-dated to 1900), `dim_date` (incl. `iso_week` with its `iso_year`), `fct_trips_hourly` (incremental: re-processes the last 35 days, anything newer, and any date not loaded yet, so a backfilled older year is picked up), `fct_station_daily`, `fct_bike_trips_daily` | tables |
| marts | `mart_recovery`, `mart_peak_load`, `mart_od_flows`, `mart_kpis_daily`, `mart_ridership_monthly`, `mart_bikes_vs_trains` | tables |

73 data tests (incl. a singular test that every staged OD date is in `fct_trips_hourly`). KPI definitions:
`docs/METRICS.md`:
- The 2019 recovery baselines (`mart_recovery`, `mart_kpis_daily`) are the same ISO week of **ISO year** 2019
  (2018-12-31 → 2019-12-29); `mart_recovery` leaves out ISO-year-2019 days.
- `mart_kpis_daily.rolling_28d_avg_entries` averages the days present in the calendar window [d − 27, d], and
  `rolling_28d_days` counts them (28 without gaps; locally 26–27 around BART's four missing 2020 days).

Targets:
- `local` (DuckDB, default): 88/88 pass, ~2.3 min. Needs the Bay Wheels Parquet: the source glob fails with no files.
- `dev` (BigQuery): all models, built by the VM's `warehouse` runs.
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
- **Validation:** walk-forward over 12 origins every 14 days, the last one 14 days before the end of the data: 6
  warm-up (calibration) folds, then 6 test folds. Each fold trains only on targets dated at or before its origin,
  within a 730-day window. Errors are pooled over the 6 test folds, stations and horizons; a paired bootstrap over
  stations (B = 1000, seed 0) gives 95% CIs.
- **Interval calibration (split-conformal, CQR):** score = max(p10 − actual, actual − p90) ÷ the station's 28-day
  level. Each test fold moves both band edges by the ⌈(n+1)·0.8⌉-th smallest score of the 6 folds before it (all
  targets at or before its origin); the published forecast uses the last 6 folds' scores. The band is clipped at 0
  and always contains p50. p50 is untouched, so MAE/RMSE are identical with and without calibration.
  `--calib-folds 0` publishes the raw p10–p90. Calibration needs fold step ≥ horizon.
- **Latest local run** (`fc-20261009T131810Z-a3cda6`, data through 2025-12-31, trained from 2024-01-02, 123 s on 4
  threads; the same data and numbers as the production BigQuery run):

  | | LightGBM | Seasonal naive |
  |---|---|---|
  | MAE | **283.1** [215.9, 364.6] | 548.5 [416.9, 698.2] |
  | RMSE | 642.6 [430.9, 842.8] | 1246.7 [857.4, 1630.2] |

  MAE improvement 265.4 [199.6, 339.9]. Coverage against 0.80 nominal: raw p10–p90 **0.705** [0.691, 0.719],
  calibrated **0.730** [0.717, 0.744]. Mean band width 0.241 → 0.251 of the station's level; the published
  forecast's adjustment q = 0.023 (folds 0–5 used q ≈ 0.004–0.006). Per test fold, raw → calibrated: 0.807 → 0.833,
  0.757 → 0.786, 0.697 → 0.726, 0.650 → 0.683, 0.896 → 0.909, 0.420 → 0.444 (Christmas).
- **Output:**
  - `marts.forecast_station_daily` (replaced each run): `run_id, generated_at, station_code, forecast_date,
    horizon_day, p10, p50, p90, lower, upper` (`lower`/`upper` = the published band).
  - `ml.forecast_runs` (appended): run id, timestamps, `data_through`, training window, folds, horizon, stations,
    every metric with `_lo`/`_hi` bounds, raw coverage, `coverage_calibrated(_lo/_hi)`, `interval_nominal`,
    `interval_method`, `conformal_q`, `calib_folds`, `mean_width_raw`, `mean_width_calibrated`, `params_json`,
    `fold_metrics_json` (per test fold, incl. calibrated coverage and q), duration.
  - New run-log columns are added to an existing table before appending (DuckDB `ALTER TABLE`, BigQuery
    `ALLOW_FIELD_ADDITION`); older rows have NULL there.
- **CLI:** `python -m ml.forecast.run [--warehouse duckdb|bigquery] [--duckdb-path] [--horizon 14] [--folds 6]
  [--calib-folds 6] [--seed 0] [--train-days 730] [--bootstrap 1000]`. The Dagster asset runs 6 + 6 folds.

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
  | `yearly_ingest` | 6th of each month, 06:00 | the BART partition of the previous month's year (January reloads last year, to pick up December) |
  | `baywheels_ingest` | 7th of each month, 06:30 | the Bay Wheels partition of the previous month's year |
  | `refresh_reference_and_models` | 6th of each month, 08:00 | GTFS, stations, map data, `dbt build` |
  | `weekly_forecast` | Mondays, 09:00 | retrain and publish the forecast |
- **Resources:** `Storage` (`local` | `gcp`), `SparkRunner` (`python` | `docker`), `DbtCliResource`.
- Runs locally against `.dagster_home/` (gitignored), started by `tasks.py dagster`, which includes the `ml` group.
- The static `years` partitions are computed when the code location loads, so a daemon started in 2026 has no
  "2027" partition until it is restarted; the monthly schedules only ask for the previous month's year.

### Oracle VM (`deploy/oracle/`, running)
- Two systemd units: `transitpulse-dagster-daemon` (schedules) and `transitpulse-dagster-web` (UI on 127.0.0.1,
  reached by SSH tunnel).
  - Both run as the non-root `transitpulse` user from `/opt/transitpulse`, with the venv first on `PATH`.
  - Environment from `/etc/transitpulse/transitpulse.env` (mode 600). The key file is
    `/etc/transitpulse/sa-pipeline-key.json` (owner `transitpulse`, 600).
  - Memory caps `MemoryMax` 7 G (daemon, includes a Spark run) / 1 G (UI), `Nice=10` and `OOMScoreAdjust=500`,
    so SeismicSoCal keeps priority and is not the one killed if memory runs out.
  - Sized for a 2 OCPU / 12 GB VM (the Always Free maximum): `TP_SPARK_DRIVER_MEMORY=4g`, `TP_ML_THREADS=2`,
    `DBT_THREADS=2` in the env file. The VM (shared with SeismicSoCal) is 2 OCPU / 12 GB with a 4 GB swap file.
  - The weekly forecast with calibration fits 12 folds instead of 6 (about twice the ~21 min the uncalibrated run
    took there). The VM runs whatever code was last pulled; `git pull` + restarting the units picks up new code.
- `bootstrap.sh` installs and updates everything (apt or dnf, Java 17, uv, `uv sync --frozen`, `dbt parse`). It
  starts the services only once the key is in place. Steps are in [`ORACLE_VM.md`](ORACLE_VM.md).

### Cloud Run (`Dockerfile`, `infra/terraform/cloudrun.tf` + `wif.tf`, `deploy.yml`; live, deploys from GitHub off)
- **Image.**
  - Build stage: `python:3.12-slim-bookworm` + the uv binary. It runs
    `uv sync --frozen --no-dev --no-default-groups --group agent --no-install-project` into `/app/.venv` (main
    dependencies + the agent group; no dev, dbt, ML or pipeline packages; bytecode precompiled).
  - Runtime stage: the same base, with only the venv, `api/` and `web/` (`.dockerignore` is an allowlist), owned by
    root and run as uid 10001.
  - `CMD`: `uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}`.
  - Size: 120 MB (`docker image inspect`), 119 MB gzip-compressed.
  - Locally it answers `/healthz` about 1.5 s after `docker run` and idles at ~76 MiB.
  - Without a warehouse its data endpoints answer 503. `/api/ask` answers 503 unless `TP_AGENT_ENABLED=true`.
- **Service (Terraform).**
  - `transitpulse-api` in us-west1: 0–2 instances, 1 vCPU / 512 MiB, `cpu_idle`, concurrency 80, timeout 60 s,
    startup probe on `/healthz`.
  - Runs as `sa-agent` (read-only on `marts` + `ml`).
  - Env: `TP_WAREHOUSE=bigquery`, `TP_GCP_PROJECT`, `TP_TRUST_PROXY=true`, `TP_AGENT_ENABLED` from
    `var.agent_enabled` (default **false**). Only when that is true do `TP_AGENT_LLM=gemini`, `TP_GEMINI_MODEL` and
    `GOOGLE_API_KEY` (Secret Manager `transitpulse-gemini-api-key`, version `latest`, added by hand) appear, along
    with `sa-agent`'s access to that secret.
  - The image is in `ignore_changes`: the first revision uses Google's `hello` placeholder, and CI owns the image
    after that.
  - `allUsers` has `run.invoker` on this service only.
- **Workload Identity Federation.**
  - Pool `github`, provider `transitpulse` (GitHub OIDC), with the condition
    `assertion.repository == "braaaeeedyn/transitpulse" && assertion.ref == "refs/heads/main"`.
  - The principalSet for the repository may impersonate `sa-deploy`.
  - `sa-deploy` has `artifactregistry.writer` on the `transitpulse` repo, `run.developer` on the service, and
    `iam.serviceAccountUser` on `sa-agent` only.
- **`deploy.yml`.**
  - Runs on push to `main` and on `workflow_dispatch`. The job runs only if `vars.DEPLOY_ENABLED == 'true'`.
  - Auth: `id-token: write`, then `google-github-actions/auth` with `vars.GCP_WIF_PROVIDER` /
    `vars.GCP_DEPLOY_SA`.
  - Steps: `docker build` (tag `us-west1-docker.pkg.dev/<project>/transitpulse/api:<sha>`), then the container
    smoke tests (`uv run pytest -m docker tests/deploy` with `TP_TEST_IMAGE` = that image), then auth and
    `docker push`, then `gcloud run deploy --image`, then curl `/healthz` and `/`.
  - It doesn't wait for `ci.yml` (both start on the same push); only the container smoke tests gate the push.
  - No Terraform in Actions.
- Applying it, switching it on, enabling the agent, quotas, rollback, costs and teardown are in
  [`CLOUD_RUN.md`](CLOUD_RUN.md).

### Load test (`load/`)
- `load/run_local.py`:
  - builds the dbt fixture warehouse (3 stations, Jan 2019 + Jan 2025, synthetic forecast with a complete run row)
    in a child `uv run --group dbt` process, in a temp dir
  - starts uvicorn on it with `TP_AGENT_ENABLED=true`, `TP_AGENT_LLM=fake` and the per-IP rate limit lifted
  - runs `load/locustfile.py` headless for each user count (default 1, 10, 25; 20 s each)
  - reads Locust's CSV percentiles, stops the server, and prints p50/p95/p99, RPS and failures per endpoint
    (`--json` for JSON)
  - exits non-zero if the server doesn't start or any request fails
- Users wait 0.5–1.5 s between tasks: `/api/kpis` 3, `/api/forecast/{code}` 3, `/api/ask` 1 (an SQL question, a
  recovery question or an off-topic one). Each user calls all three once on start. An ask counts as failed unless
  its SSE stream ends in `answer` or `refusal`.
- Last run on this PC: 0 failures. At 25 users, ~30 req/s; forecast p50/p95/p99 5/14/30 ms; kpis 4/22/29 ms; ask
  37/140/140 ms. Full table in the README.

---

## 6. Tests

| Suite | Command | Count | Status |
|---|---|---|---|
| Python unit (map data, API data endpoints, Bay Wheels cleaning, dbt build on a generated fixture, dbt regressions (backfill, ISO year, rolling window), forecast + calibration, Dagster definitions and schedules, VM files, agent guardrails / graph / `/api/ask` / eval, Cloud Run Terraform + deploy workflow) | `uv run --group dbt --group ml --group pipeline --group agent pytest -m "not spark and not gcp and not localdata and not docker"` | 93 | pass (~40 s) |
| Local warehouse (real data, incl. every gold SQL of the agent eval) | `uv run --group dbt --group ml --group agent pytest -m localdata tests/local` | 8 | pass (needs `data/transitpulse.duckdb` with Bay Wheels + forecast) |
| Spark job | in Docker: `docker run --rm -v "$PWD:/app" transitpulse-spark python -m pytest tests/spark -m spark` | 1 | pass (auto-skipped on Windows outside Docker) |
| Browser maths (schedule, timetable range, chart helpers, station search, forecast wording, SSE parser) | `node --test tests/web/` | 24 | pass |
| Browser (Playwright, Chromium; API mocked for data and Ask tests) | `npx playwright test` | 35 | pass |
| dbt data tests | `uv run python tasks.py dbt` | 73 (+15 models/snapshot) | pass (incremental ~2.3 min) |
| Shellcheck (VM bootstrap) | `docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable deploy/oracle/bootstrap.sh` | — | clean |
| ARM wheels (pipeline, dbt, ml groups) | `uv pip compile pyproject.toml --group pipeline --group dbt --group ml --python-platform aarch64-manylinux_2_28 --python-version 3.12 --only-binary :all:` | — | resolves |
| Container (marker `docker`; needs the built image `transitpulse-api:loop`) | `docker build -t transitpulse-api:loop . && uv run pytest -m docker tests/deploy` | 5 | pass |
| Load test (Locust, fixture warehouse, fake LLM) | `uv run --group load --group agent python load/run_local.py [--users N --seconds S]` | — | 0 failures |
| Workflows | `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest` | — | clean (`ci.yml`, `deploy.yml`) |
| Lint/format | `uv run ruff check . && uv run ruff format --check .` | — | clean |
| Terraform | `terraform validate` / `fmt -check`; `plan` for the applied M0 resources | — | clean; the M0 plan showed no changes (the M7 files were never planned against the real backend) |

---

## 7. Known limitations (current behaviour)
- Train positions follow the timetable; delays and disruptions are not shown.
- Local Bay Wheels data covers 2019 and 2025 only (BigQuery has 2018 → 2026-09).
- The bundled GTFS timetable (`web/data/schedule.json`) ends on 2027-01-10; after that the map shows no trains and
  says the timetable has ended until `web/data` is rebuilt from a newer feed (`tasks.py web-data`).
- The agent's accuracy with llama3.1:8b is 27% on the eval set; it is off unless `TP_AGENT_ENABLED=true`. Its rate
  limit and byte budget are per process and in memory.
- The forecast's band held 73% of back-test days after calibration (raw p10–p90: 70.5%; nominal 80%), mostly because
  of the Christmas fold (44%), so the site calls it the "model range" and says it is narrower than it should be.
- Production (BigQuery) serves the pre-calibration run until the Oracle VM runs this code; the API then shows the raw
  band at 70% coverage, worded the same way.
- The forecast covers the 14 days after the latest published data (currently 2026-01-01 → 14), not the next two
  weeks from today; the site says "forecast from data through".
- On Windows, Spark runs only through Docker.
- The running Cloud Run image (`manual-2dd730f`) predates `/api/health`; the next deploy adds it. On `*.run.app`,
  `/healthz` is answered by Google's front end (404), so outside checks use `/api/health`.
- The first API request after the service scales to zero takes ~5 s (cold start + first BigQuery queries); later
  ones ~0.15 s. The map needs no API and shows immediately.
- The load-test numbers are from this PC on a tiny fixture warehouse, not from Cloud Run or BigQuery. Cloud Run's
  cold start has not been measured.
- Static assets have no hashed names: JS/CSS are served `no-cache` (revalidated), fonts are cached a year, and map
  data a day. The timetable is part of the image, so refreshing it means deploying a new image.
