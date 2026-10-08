# TransitPulse: current state

> **Scope of this file:** how the application works *right now*, and nothing else. No history, no plans.
> It is rewritten whenever behaviour changes. History lives in [`DEVLOG.md`](DEVLOG.md); the task list in
> [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
>
> **Last verified:** 2026-10-07, on Windows 11. Cloud resources exist (Terraform applied); no app is deployed.

---

## 1. What exists and runs

| Part | State | How to run |
|---|---|---|
| Website (static, `web/`) | **Working**: live train map, nav, Ask card UI, page sections | `uv run python tasks.py api` → http://localhost:8000 |
| API (`api/`) | **Working shell**: serves the site; data/agent endpoints answer 503 | same as above |
| Map data build (`pipeline/webdata/`) | **Working** | `uv run python tasks.py web-data` |
| Spark cleaning job (`pipeline/spark/`) | **Working** (Docker on Windows, native on Linux) | `uv run python tasks.py spark` |
| dbt warehouse models (`dbt/transitpulse/`) | **Working on both targets**: `local` (DuckDB) and `dev` (BigQuery, all of 2018–2025) | `uv run python tasks.py stations` then `uv run python tasks.py dbt` (`DBT_TARGET=dev` for BigQuery) |
| Dagster orchestration (`pipeline/definitions.py`) | **Working** in `local` and `gcp` mode, run from this PC (not yet on the Oracle VM) | `uv run python tasks.py dagster` → http://localhost:3000 |
| Terraform (`infra/terraform/`) | **Applied** to GCP project `transitpulse-511002` (33 resources; `plan` = no changes) | see `infra/README.md` |
| CI (`.github/workflows/ci.yml`) | **Written, never run** (no GitHub remote yet) | — |
| Forecasting, causal analysis, agent, fine-tuning, BI reports, deployment | **Not implemented** | — |

---

## 2. Data flow (local mode)

```
bart.gov GTFS zip ──► pipeline/webdata ──► web/data/{network,schedule,land}.json ──► browser map
        │
        └──────────► pipeline/stations ──► data/parquet/bart_stations/stations.csv ─┐
                                                                                     ▼
bart.gov OD CSV.gz ─► data/raw/bart_od/ ─► Spark clean_bart_od ─► data/parquet/bart_od/year=/month=/*.parquet
                                                                                     │
                                       dbt (DuckDB, data/transitpulse.duckdb) ◄──────┘
                                       staging ─► snapshot ─► core (dims/facts) ─► marts
```

- Everything under `data/` is generated and gitignored. `web/data/*.json` is generated **and committed**
  (the site needs it to run).
- In `gcp` mode (`TP_PIPELINE_MODE=gcp`, `DBT_TARGET=dev`) the same assets upload to GCS
  (`gs://transitpulse-511002-raw`) and load BigQuery (`raw.bart_od`, `raw.bart_stations`); dbt then builds
  `staging` and `marts` in BigQuery. Spark runs are queued one at a time (`pipeline/dagster.yaml`).
- Years BART hasn't published yet (currently 2026: an empty gzip) are skipped: the three yearly assets succeed with
  `published: false` and a warning.

### Data currently loaded
| Dataset | Where | Coverage | Size |
|---|---|---|---|
| BART hourly origin-destination | **BigQuery** `raw.bart_od` → `marts.*` | 2018–2025 (2020 is missing 4 days in BART's file) | 67,770,440 rows; 4.2 GB logical |
| BART hourly origin-destination | local Parquet / DuckDB | 2019 and 2025 | 19,257,542 rows; 46 MB Parquet |
| BART GTFS | web/data, `raw.bart_stations` | feed version 72 (service 2026-08-10 → 2027-01-10) | 50 stations, 3,762 rail trips |
| Bay Wheels | — | **none** | — |

---

## 3. The website

### Page (single page, `web/index.html`)
1. **Nav**: sticky; links + "Ask a question" pill. Below 1120 px the links move into a full-screen menu
   (focus trapped, Esc closes, body scroll locked). Below 600 px the CTA becomes a search icon.
2. **Hero + Ask card**: question input, 4 suggestion chips, Ask button. Submitting POSTs to `/api/ask`; because the
   agent isn't connected, the page shows "The analyst isn't connected yet…". The client also handles a streamed
   (SSE) answer, refusals, rate limits (429) and network errors, but no server produces those yet.
3. **Live map** (see below).
4. **Trends** and **Forecast**: each shows an information message that the data isn't connected yet.
5. **Findings** (black band): heading + "analysis is in progress".
6. **About**: three FAQ rows (`<details>`).
7. **Footer**: data sources/licences, GitHub link, credits.

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
  2 min". Station: name + lines. Tap elsewhere to dismiss.
- **List view**: table of running trains (line, destination, next stop, minutes), refreshed every 5 s.
- **Out of service** (current feed: last train ends 1:52 AM; first departs 4:28 AM weekdays, 5:28 AM Saturdays,
  7:28 AM Sundays): a card says when service resumes, with *Jump to 8:00 AM*.
- **Performance**: redraws ~4×/s at 1×, ~20×/s at 10×, every frame at 60×; stops while off-screen or in a hidden tab.
- **Accessibility**: a polite live region announces "N trains running on K lines at h:mm" once a minute; reduced
  motion → positions update every 30 s with no animation; all controls are buttons ≥ 44 px on touch; skip link.
- **Failure**: if the map data can't load, the map area shows an error message with Retry.

### Design system
`web/css/tokens.css` mirrors `docs/DESIGN.md` **v1.0.1** (frozen). Black/white interface; line colours only in data
marks; Inter 400/500/700; pills for controls, 16 px cards. Deviations awaiting v1.1 are listed in `DESIGN_BACKLOG.md`.

---

## 4. API (`api/`)

| Method | Path | Current behaviour |
|---|---|---|
| GET | `/` and static files | serves `web/`. Cache: `/fonts/*` 1 year, `/data/*` 1 day, everything else `no-cache` |
| GET | `/healthz` | `{"ok": true}` |
| GET | `/api/kpis`, `/api/stations/{code}/summary`, `/api/forecast/{code}` | **503** `{"code": "warehouse_not_connected"}` (501 if `TP_GCP_PROJECT` is set: not implemented) |
| POST | `/api/ask` | body `{"question": str (1–300)}` → **503** `{"code": "agent_unavailable"}` (501 if `TP_AGENT_ENABLED=true`) |
| GET | `/api/docs` | OpenAPI UI |

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

### dbt models (`dbt/transitpulse/`)
| Layer | Models | Materialization |
|---|---|---|
| staging | `stg_bart_od`, `stg_bart_stations` | views |
| snapshot | `snap_bart_stations` (SCD2, check strategy on name/lat/lon) | snapshot |
| core | `dim_station` (SCD2, first version back-dated to 1900), `dim_date`, `fct_trips_hourly` (incremental, last 35 days re-processed), `fct_station_daily` | tables |
| marts | `mart_recovery`, `mart_peak_load`, `mart_od_flows`, `mart_kpis_daily` | tables |

41 data tests. KPI definitions: `docs/METRICS.md`. Targets: `local` (DuckDB, default; 52/52 pass), `dev`
(BigQuery: all 11 models built and tested over 2018–2025), `ci` (never run). On BigQuery, facts are partitioned by `trip_date` and clustered by station, and queries
are capped at 20 GB billed in `dev` / 500 MB in `ci` (`maximum_bytes_billed`).

### Dagster (`pipeline/definitions.py`)
- Assets: `bart_gtfs`, `bart_stations_raw`, `web_map_data`; `bart_od_files` → `bart_od_parquet` → `raw/bart_od`
  (static yearly partitions 2018 → current year); every dbt model/snapshot as an asset (group `warehouse`).
- Jobs/schedules: `yearly_ingest` on the 6th of each month at 06:00 Pacific (current year's partition);
  `refresh_reference_and_models` at 08:00 the same day (GTFS, stations, map data, `dbt build`).
- Resources: `Storage` (`local` | `gcp`), `SparkRunner` (`python` | `docker`), `DbtCliResource`.
- Runs locally against `.dagster_home/` (gitignored). Not deployed to the Oracle VM.

---

## 6. Tests

| Suite | Command | Count | Status |
|---|---|---|---|
| Python unit (map data, geometry) | `uv run pytest` | 12 | pass |
| Spark job | in Docker: `docker run --rm -v "$PWD:/app" transitpulse-spark python -m pytest tests/spark -m spark` | 1 | pass (auto-skipped on Windows outside Docker) |
| Browser schedule maths | `node --test tests/web/` | 5 | pass |
| Browser (Playwright, Chromium) | `npx playwright test` | 17 | pass |
| dbt data tests | `uv run python tasks.py dbt` | 41 (+11 models/snapshot) | pass |
| Lint/format | `uv run ruff check . && uv run ruff format --check .` | — | clean |
| Terraform | `terraform validate` / `fmt -check` / `plan` | — | clean; plan shows no changes |

---

## 7. Known limitations (current behaviour)
- Train positions follow the timetable; delays and disruptions are not shown.
- Ridership numbers are not yet shown on the site (the API doesn't read the warehouse).
- Local DuckDB has only 2019 and 2025; BigQuery has 2018–2025. There is no Bay Wheels data.
- On Windows, Spark runs only through Docker.
- No app is deployed. GCP has the warehouse (raw → marts), bucket, registry, service accounts and $1/$5 budget alerts.
