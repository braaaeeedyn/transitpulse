# TransitPulse dev log

A running, append-only record of what is happening in the codebase: what was built, what was decided, what broke,
and what is blocked. Newest entries at the bottom. For a description of how the app works *right now*, see
[`CURRENT_STATE.md`](CURRENT_STATE.md); for where each target skill lives, see [`SKILLS_MAP.md`](SKILLS_MAP.md).

Entry format: `## YYYY-MM-DD · milestone · short title`, then **Did / Decided / Blocked / Next** as needed.

---

## 2026-10-07 · planning · plan + design frozen
**Did**
- `docs/IMPLEMENTATION_PLAN.md` written from `TRANSITPULSE_PLAN.md` (M0–M7 backend, F1–F7 frontend).
- `docs/DESIGN.md` rewritten as the TransitPulse design system v1.0 and **frozen** (original kept at
  `docs/reference/DESIGN_SOURCE_uber-analysis.md`).

## 2026-10-07 · M0 · environment check
**Did**
- Checked the local toolchain: Python 3.12.4 (`py`), uv 0.12, Java 22, Node 20, Docker 28, git.
- Downloaded the BART GTFS feed (feed version 72, service dates 2026-08-10 → 2027-01-10) to inspect it.
  It contains `shapes.txt`, so line geometry comes from real shapes, not straight-line fallbacks.

**Found**
- `make` is not installed on this Windows machine → added `tasks.py` (pure Python task runner). The `Makefile`
  just forwards to it so CI (Linux) and `make` users get the same commands.
- `terraform` is not installed → Terraform code is written but can't be validated here yet.
- Java is 22; Spark 3.5 supports Java 8/11/17 only → PySpark jobs need a Java 17 install (`JAVA_HOME`) before they run.
- GTFS includes two bus-bridge routes (`BB-A`, `BB-B`, `route_type=3`); these are excluded from the train map.
- GTFS calls the Oakland Airport connector "Grey" (`route_id` 19/20). It maps to the design token `line-beige`.

## 2026-10-07 · M0 · scaffold
**Did**
- Repo layout per `IMPLEMENTATION_PLAN.md §1`; `pyproject.toml` (uv, Python 3.12) with dependency groups per area
  (`pipeline`, `spark`, `dbt`, `ml`, `agent`, `webdata`, `load`) so each part installs only what it needs.
- `tasks.py` task runner + forwarding `Makefile`; `.gitignore` covers secrets, raw data, Terraform state, model files.
- Terraform base in `infra/terraform/`: APIs, **$1 and $5 budget alerts** (as code, not by hand), raw bucket,
  BigQuery datasets `raw/staging/marts/ml/ci` (ci tables auto-expire after 3 days), Artifact Registry with a
  keep-last-3 cleanup policy, service accounts `sa-pipeline` (read/write) / `sa-agent` (read-only on marts+ml) / `sa-deploy`.
- `terraform validate` passes (run through the `hashicorp/terraform:1.9` Docker image, since terraform isn't installed).

**Blocked (needs the user)**
- Creating the GCP project, billing account and the state bucket, then `terraform apply` (`infra/README.md`).

## 2026-10-07 · F2 · map data from GTFS
**Did**
- `pipeline/webdata/` turns the GTFS zip into `web/data/network.json` (13 KB), `schedule.json` (63 KB) and
  `land.json` (12 KB): 50 stations, 51 track edges, 6 lines, 34 stop patterns, 3,762 trips.
- Schedule compression: trips are `[pattern, service, profile, start]`; 3,762 trips share only 55 timing profiles.
- Output is deterministic (verified: two builds give identical hashes). 12 pytest checks in `tests/test_webdata.py`.

**Decided**
- One `schedule.json` (with the service calendar inside) instead of per-service files: at 63 KB it's small enough,
  and the browser can then pick the correct service for any date, including holidays (`calendar_dates`).
- Land shape from **US Census cartographic county boundaries** (public domain, already clipped to the shoreline)
  instead of Natural Earth (1:10M is too coarse to show the Bay). Same intent as DESIGN.md §6 (public-domain coastline);
  logged in `DESIGN_BACKLOG.md`.
- Station-to-shape snapping scans forward for the first close local minimum, so patterns that double back
  (Millbrae ↔ SFO) don't snap to the wrong pass.

**Fixed**
- Some trips stop at two SFO platforms in a row → a bogus `SFIA→SFIA` edge. Consecutive stops at the same parent
  station are now merged (first arrival, last departure).

## 2026-10-07 · F1 · design tokens + responsive shell
**Did**
- `web/css/tokens.css` transcribes every `DESIGN.md` token; `base.css`, `layout.css`, `components.css`, `map.css`
  use only those variables. Inter (OFL) self-hosted; Lucide icons (ISC) as an inline sprite.
- `web/index.html`: nav (overlay menu < 1120 px with focus trap, Esc, scroll lock), hero + Ask card, live map,
  Trends / Forecast (honest "not connected yet" states), Findings ink band, FAQ, footer.
- `api/main.py` (FastAPI) serves `web/` with cache headers and stub `/api/*` routes that answer **503** with a
  machine-readable reason until the warehouse (M2) and the agent (M5) exist.

**Fixed (found by Playwright)**
- At 320 px the page was 352 px wide: `.btn`/`.icon-btn` load after the nav's `display:none` rules, so both nav CTAs
  and the menu button showed at every width. Nav rules are now scoped under `.nav`.
- Hero grid used an `auto` column that refused to shrink → `minmax(0, 1fr)`.
- Findings band had no top padding (`.band + .band` zeroed it); the hero and the map band double-spaced.
- Text input placeholder uses `body` grey, not `mute`: `mute` on `canvas-soft` is ~4.0:1 and fails AA.

## 2026-10-07 · F3 · live train map
**Did**
- `web/js/map/`: `schedule.js` (pure schedule maths: which services run on a date, where each trip is),
  `geometry.js` (fit-to-container view, parallel-lane offsets, sampling along paths), `network.js` (SVG base layer +
  label placement), `trains.js` (canvas pills + hit testing), `map.js` (clock, controls, interaction, list view,
  screen-reader summary, pausing).
- 51–53 trains at 8:15 AM on a weekday; none at 3 AM, with "Service resumes at 4:xx AM" + *Jump to 8:00 AM*.
- Redraw rate follows speed (1× ≈ 4 fps, 10× ≈ 20 fps, 60× every frame) because at 1× trains move < 1 px/s;
  paused off-screen / in hidden tabs; reduced motion → still positions every 30 s.

**Decided**
- SVG and canvas share one **pixel** coordinate space (viewBox = container size) instead of a fixed
  `0 0 1000 1000` viewBox: line widths, station radii, label sizes and lane offsets are then plain CSS px, and the
  canvas lines up exactly. Data stays in 0–1000 map units. Same visual result as DESIGN.md §6.
- Labels are placed at render time (hubs first, then busier stations; try the preferred side, then E/W/N/S; skip
  if it would overlap a label, a station or the track). Fixed sides alone overlapped badly in the downtown core.

**Design change (accessibility exception) → DESIGN.md v1.0.1**
- On a 358 px map, transfer-station capsules (up to 23 px) overlapped each other and hid the 6 px trains.
  Below 600 px map width every station is now a plain circle. Recorded in DESIGN.md's changelog.

## 2026-10-07 · F7 (early) · tests
**Did**
- `tests/web/site.spec.js` (Playwright, 17 tests): no horizontal scroll at 320/390/768/1024/1440/1920 px; canvas
  backing store = container × devicePixelRatio (also after resize); trains at rush hour; out-of-service notice;
  list view; replay/live switching; tooltip; zoom limits; phone menu focus trap; offline Ask message; data-load
  failure message; reduced motion.
- `tests/web/schedule.test.mjs` (node:test, 5 tests): trip interpolation, service calendar exceptions, real
  schedule at rush hour vs 3 AM, after-midnight trips, clock formatting.

## 2026-10-07 · M1 · Spark, dbt, Dagster on real data
**Did**
- `pipeline/spark/clean_bart_od.py`: explicit schema, PERMISSIVE parse with a corrupt-record column, per-reason drop
  counts, window de-dup (latest source file wins), broadcast holiday join, Parquet partitioned by year/month with
  dynamic partition overwrite, `audit.json`. 2019 + 2025: **19,257,542 rows → 46 MB Parquet in 84 s**, 0 dropped.
- `dbt/transitpulse`: 2 staging views, SCD2 snapshot → `dim_station`, `dim_date`, incremental `fct_trips_hourly`,
  `fct_station_daily`, 4 marts. 41 tests (generic + custom `non_negative`, `unique_combination_of_columns`).
  `dbt build`: **52/52 pass in 7.5 s**. Sanity check: 2025 weekday recovery = **43.1% of 2019**; Embarcadero busiest;
  5 PM peak.
- `pipeline/definitions.py` (Dagster): ingest assets (GTFS, stations, map data, yearly OD files → Parquet → raw),
  dbt assets via dagster-dbt, two monthly schedules. Materialized end to end locally, including a 2025 partition
  through Spark-in-Docker.
- `docs/METRICS.md`: KPI definitions with formulas and the columns that compute them.
- `.github/workflows/ci.yml`: lint, pytest, Spark tests (Java 17), node + Playwright, `dbt parse`, terraform validate.

**Decided**
- **Spark runs in Docker on Windows** (`pipeline/spark/Dockerfile`: Debian bookworm + OpenJDK 17). Spark 3.5 on
  Windows needs `winutils.exe` and only supports Java ≤ 17 (this machine has 22); reads hung. The Oracle VM and CI
  run it natively. Spark tests auto-skip on Windows (`tests/spark/conftest.py`).
- **dbt `local` target on DuckDB** reads the Spark Parquet directly, so the warehouse layer is built and tested before
  the GCP project exists. Adapter differences (ISO week, weekday, date spine, incremental strategy) are dispatched
  macros in `macros/schema_and_dates.sql`; BigQuery-only configs (partitioning, clustering) are conditional.
- Recovery baseline = average **service weekday in the same ISO week of 2019** (more stable than a single day).
- `dim_station` back-dates each station's first version to 1900 so pre-snapshot trips still join (all 19.26M did).

**Fixed**
- Spark OOM on two years: local mode runs executors inside the 1 GB default driver → `--driver-memory 4g`; the job
  also recomputed the de-dup shuffle three times (years list, write, duplicate count) → now once.
- bart.gov returns **403** to Python's default User-Agent → downloads send `TransitPulse/0.1`.
- dagster-dbt runs dbt from inside the project folder → data paths come from `TP_DATA_ROOT` / `TP_DUCKDB_PATH`.
- `from __future__ import annotations` breaks Dagster's context-type check → removed from asset modules.
- Line endings normalized to LF; `.gitattributes` added.

**Blocked (needs the user)**
- GCP project + billing + state bucket → `terraform apply`, then `TP_PIPELINE_MODE=gcp` loads BigQuery.
- Oracle VM: install Java 17 and the systemd unit for Dagster.
- Bay Wheels ingest not started (next M1 task).

## 2026-10-07 · docs · state, skills map, plan status
**Did**
- `docs/CURRENT_STATE.md`: how the app works right now (rewritten when behaviour changes).
- `docs/SKILLS_MAP.md`: every skill from the plan → status, file:line, what it does, how it works.
- `docs/IMPLEMENTATION_PLAN.md`: tasks marked `[x]` / `[~]` (with what's left) / `[ ]`.
- `README.md`: local run instructions for the site and the pipeline.

**Next (in order)**
1. User: create the GCP project + billing + state bucket → `terraform apply` → run Dagster with `TP_PIPELINE_MODE=gcp`.
2. M1: Bay Wheels ingest; backfill 2018–2024; Oracle VM deployment.
3. F4 + M2: `/api/kpis` reading the marts → KPI tiles and trend charts; Looker Studio; Power BI.

## 2026-10-07 · M0 · GCP project ready for apply
**Did**
- User created project `transitpulse-511002`, linked billing, signed in (`gcloud` + application-default
  credentials) and created the state bucket `transitpulse-511002-tfstate`. `versions.tf` now points at it;
  `terraform.tfvars` (gitignored) filled in.
- `terraform init` + `plan` against the real project: **31 to add, 0 to change, 0 to destroy**.

**Fixed (before first apply / first load)**
- Budget email channel needs `monitoring.googleapis.com`, which wasn't enabled → added to the API list.
- `raw_bart_od` deleted the year's rows before loading, which fails when `raw.bart_od` doesn't exist yet
  (first run) → `NotFound` is now caught.

## 2026-10-07 · M0 · first terraform apply: bootstrap APIs
**Found**
- First apply on the new project failed with 403s: `google_project_service` needs the **Cloud Resource Manager
  API** already on to manage other APIs, and service accounts were created before `iam.googleapis.com` was enabled.
  BigQuery, Storage and Monitoring APIs were enabled before it stopped (kept in state).

**Fixed**
- `infra/README.md` step 4: enable `cloudresourcemanager`, `serviceusage`, `iam` once by hand (bootstrap, like the
  state bucket). They're also in the Terraform list so they stay on.
- Service accounts now `depends_on` the enabled APIs.

## 2026-10-07 · M0 done · GCP applied
**Did**
- `terraform apply` succeeded on `transitpulse-511002`: 30 added, 6 replaced (the API records tainted by the first
  failed run; `disable_on_destroy = false`, so no API was switched off). Verified: 12 APIs on, 3 service accounts,
  both budgets, datasets, bucket, registry.

**Fixed**
- Two permanent diffs (every `plan` showed "3 to change"): the Budgets API stores the project **number**, not the ID
  → `data.google_project.this.number`; Artifact Registry drops `older_than = "0s"` → `tag_state = "ANY"`.
  `plan` now: **No changes**.
- BART serves an **empty gzip** for unpublished years (2026 today). The yearly assets now skip cleanly with
  `published: false` instead of failing every month. Verified with a local 2026 run.
- dbt `dev` cost cap 2 GB → 20 GB: the first full BigQuery build reads ~3–6 GB of raw data and would have been refused.

## 2026-10-07 · M1 · first GCP backfill crashed Docker Desktop
**Found**
- The backfill launched all 9 yearly runs at once → 8 Spark containers × 4 GB driver heap. At 20:35:04 every
  container lost its Docker connection (`error waiting for container: unexpected EOF`, exit 125): the Docker Desktop
  VM ran out of memory. 2026 (skipped, no Spark) succeeded. Raw files had already downloaded.

**Fixed**
- `yearly_ingest` runs carry the tag `transitpulse/spark`; `pipeline/dagster.yaml` (copied into `$DAGSTER_HOME` by
  `tasks.py dagster`) limits those runs to **one at a time**, so backfills run in sequence.
- Docker runner adds `--memory 6g`: a runaway job is killed alone instead of taking down the VM.

## 2026-10-07 · M1 · raw data in BigQuery
**Did**
- Sequential backfill succeeded (one Spark container at a time). `raw.bart_od`: **67,770,440 rows, 2018–2025**,
  4.2 GB logical, partitioned by day. 2019 and 2025 row counts match the local build exactly. `raw.bart_stations` loaded.
- Docker Desktop's VM has 8 GB total: confirms the one-at-a-time limit and the 6 GB container cap are required.

**Found (to check)**
- 2020 has 362 day-partitions, not 366: 4 days missing from BART's 2020 file.
- ADC has no quota project (google-auth warning) → `gcloud auth application-default set-quota-project transitpulse-511002`.

## 2026-10-07 · M1 · first BigQuery dbt build
**Found**
- Warehouse build stopped after `dim_station`: the `accepted_values` tests (hour 0–23, weekday 1–7) failed with
  `No matching signature for operator IN for argument types INT64 and {STRING}`. dbt quotes accepted values by
  default; DuckDB casts implicitly, BigQuery doesn't. The failed tests made dbt skip every downstream model.
- (Also: the first warehouse run was cut off when the terminal running Dagster was closed. Safe to re-run:
  BigQuery `CREATE OR REPLACE` is atomic, so tables are whole or absent.)

**Fixed**
- `quote: false` on the three integer `accepted_values` tests. Verified: local 52/52; on BigQuery all 9
  `stg_bart_od` tests pass over 67.8M rows.

## 2026-10-07 · M1 · warehouse built on BigQuery
**Did**
- Dagster `warehouse` run on BigQuery built every model except `mart_od_flows`:
  `fct_trips_hourly` 67,770,440 rows (= raw), `dim_date` 2,922 days, `mart_kpis_daily` 2,918 days (4 missing 2020
  days), `fct_station_daily` 143,958, `mart_recovery` 86,525. Biggest query: 2.44 GB billed.
- KPIs match the local DuckDB build exactly (2019: 324,958 avg daily; 2025: 149,335, recovery 0.431, peak share 0.107).
- Recovery curve 2018–2025: 1.01 → 1.00 → 0.27 → 0.20 → 0.33 → 0.39 → 0.41 → 0.43. Busiest station moved from
  Montgomery (2018–19) to Powell (2020–22) to Embarcadero (2023–25).

**Fixed**
- `mart_od_flows` failed with `TIMESTAMP = DATETIME`: on BigQuery `dbt.date_trunc` returns TIMESTAMP and
  `dbt.dateadd` returns DATETIME. Every `date_trunc`/`dateadd` result is now cast to DATE (5 models), so both
  adapters see the same types. Verified: local 52/52; BigQuery dry run of the 4 affected models passes.

## 2026-10-07 · M1 · warehouse complete on BigQuery
- Re-run (05:50 UTC) succeeded: all 11 models built, `mart_od_flows` 233,631 rows; `fct_trips_hourly` ran
  incrementally (MERGE of the last 35 days, 0.17 GB billed). Dagster run green, so every error-severity test passed.

## 2026-10-07 · repo · pushed to GitHub; first CI runs
**Did**
- Commits pushed to `github.com/braaaeeedyn/transitpulse` (no co-author trailer, per the user).
- First two CI runs: terraform, python, spark (native Java 17 on Linux) **pass**; web **failed** in Playwright.

**Found**
- Reproduced the CI web job in a Linux container (node:20 + `playwright install --with-deps chromium`): at 320 px
  the page was **334 px** wide. The Ask card's first suggestion chip ("Which stations grew most since 2022?") never
  wrapped; with Linux font metrics it measured 294 px and the card's `auto` grid column grew to fit it. On Windows
  it happened to fit, which hid the bug (a phone with larger fonts would hit it too).

**Fixed**
- `.ask-card` and its form use `grid-template-columns: minmax(0, 1fr)`; chips get `max-width: 100%` so long
  suggestions wrap to two lines. Verified: 17/17 Playwright on Linux and on Windows; Linux page width = 320 px.

## 2026-10-08 · F4 · ridership numbers on the site
**Did**
- `api/warehouse.py`: one `Warehouse` interface with two backends. `DuckDBWarehouse` opens a read-only connection
  per query and closes it straight away. `BigQueryWarehouse` uses typed `ScalarQueryParameter`s, a 100 MB
  `maximum_bytes_billed` cap and location `us-west1`. Endpoint SQL is plain `SELECT … WHERE … ORDER BY … LIMIT`
  with `@name` parameters; dates are computed in Python.
- `api/cache.py`: in-process TTL cache keyed by warehouse + endpoint + arguments (1 h for KPIs, trends and
  stations; 6 h for forecasts). Errors are never cached.
- Endpoints: `/api/kpis`, `/api/trends/ridership`, `/api/trends/bikes-vs-trains`, `/api/stations/{code}/summary`,
  `/api/forecast/{code}`. All answer 503 `warehouse_not_connected` unless a warehouse is configured. Unknown or
  malformed codes get 404 `unknown_station`.
- New mart `mart_ridership_monthly` (the chart series), so the API doesn't need dialect-specific month truncation.
- Trends band: 4 KPI tiles (ⓘ definitions, ▲/▼ deltas in ink), a "Data through" line and a "Ridership since 2019"
  SVG chart (`web/js/chart.js` helpers, `web/js/trends.js`). The chart line breaks at months with no data.
  Skeletons are the same size as the loaded content (Playwright checks the height changes by ≤ 2 px). 503 keeps
  the honest empty message; errors show Retry. The map's station tooltip now adds
  "Entries on Dec 31, 2025: 4,956 (17% of 2019)" from the summary endpoint.
- Values on the local build, for the 28 days to 2025-12-31 (holiday season): recovery 38%, 115,501 average daily
  entries, peak-hour share 10.9% (▼ 0.9 pts vs the same weeks of 2019), busiest station Powell St (9.9% of entries,
  busiest on 17 of 28 days). YoY and recovery deltas are null locally because 2024 isn't loaded.

**Decided**
- The warehouse is explicit opt-in: `TP_WAREHOUSE=none|duckdb|bigquery`. The default is `none`; if
  `TP_GCP_PROJECT` is set the default becomes `bigquery`. The app never auto-detects the DuckDB file, so tests and CI
  behave the same whether or not `data/` exists. `tasks.py api` sets `TP_WAREHOUSE=duckdb` when the file exists.
- KPI windows are computed by date, not from `rolling_28d_avg_entries`.

**Found**
- `mart_kpis_daily.rolling_28d_avg_entries` is a 28-*row* window, so locally it spans the 2020–2024 gap
  (Jan 2025 averages include Dec 2019). Known issue, not fixed (out of scope); the API doesn't use that column.
- DuckDB `DECIMAL` (and BigQuery `NUMERIC`) values come back as `Decimal`, which FastAPI serialises as strings.
  Fixed: the warehouse layer converts them to floats.
- `data/parquet/bart_od` locally holds 2018–2025 (written by the gcp-mode backfill), but the local facts only have
  2019 and 2025 because `fct_trips_hourly` is incremental. `stg_bart_od` tests now scan all 8 years, so a full local
  `dbt build` takes ~5.5 min.

## 2026-10-08 · M1 · Bay Wheels
**Did**
- `pipeline/baywheels.py`: keys come from the bucket listing (ListObjects XML, paginated) by their `YYYYMM-` prefix,
  never from a template. That handles `fordgobike`/`baywheels`/`baywheeels`/`lyftbikes`, `.zip` without `.csv`,
  the yearly 2017 file (skipped) and the missing months (2020-04, 2024-12). Downloads are skipped when the ETag
  and size match `data/raw/baywheels/manifest.json`, which also records each file's sha256. Zips are untrusted:
  only the single CSV member is extracted (basename only, `__MACOSX/` skipped).
- Cleaning in DuckDB with an explicit all-VARCHAR schema from the header (`store_rejects` counts malformed rows).
  Both schemas are normalised to one; each dropped row gets one reason, and rows are de-duplicated on `ride_id`
  (legacy rows get an md5 of their source fields). Output is Parquet `year=/month=` (replacing only the months
  processed) plus `parquet/baywheels_audit/year=YYYY/audit.json`.
- Local run, 2019 + 2025 (24 files, 252 MB of zips): **56 s** for download + clean; 236 MB of Parquet.
  - 2019: 2,506,983 rows in, 2,506,867 kept. Dropped: 104 outside the Bay Area, 11 non-positive duration, 1 over 24 h.
  - 2025: 4,397,438 in, 4,395,116 kept. Dropped: 1,767 over 24 h, 435 outside the file's month, 76 missing
    coordinates, 41 non-positive duration, 3 outside the Bay Area.
  - No malformed rows or duplicates in either year.
- dbt: source `raw.baywheels_trips`, `stg_baywheels_trips`, `fct_bike_trips_daily`, `mart_bikes_vs_trains`
  (full outer join of the monthly series; index vs the same month of 2019 = 100). Local build 83/83 pass.
- Dagster: `baywheels_files[year]` → `baywheels_parquet[year]` → `raw/baywheels_trips[year]`, job `baywheels_ingest`,
  schedule on the 7th at 06:30 Pacific. Materialized 2019 through Dagster as well (downloads skipped, 11 s clean).
  The BigQuery load code (partition `trip_date`, cluster `start_station_id`) exists but **was not run**.
- Site: second chart card "Bikes and trains" (BART solid `series-primary`, Bay Wheels dashed `series-secondary`,
  legend in text, under the chart below 600 px). If bike data is missing the card says so and the BART parts stay.
- Footer + README: Bay Wheels licence link verified (Lyft "Data License Agreement",
  `baywheels-assets.s3.amazonaws.com/data-license-agreement.html`, linked from the Lyft system-data page).

**Decided**
- Python + DuckDB instead of Spark for Bay Wheels: 2–5 M rows/year is single-machine work. DuckDB runs natively on
  Windows, in CI and on the ARM VM (no JVM, no Docker), and has an explicit-schema CSV reader with reject tracking and
  partitioned Parquet output. Spark stays on the BART OD data, which is 3–4× larger.

**Found (sanity numbers)**
- Bikes per 1,000 BART entries: **21.1 in 2019 → 80.6 in 2025**. In 2025, Bay Wheels ran at 127–210% of its
  2019 trips per day (month by month), while BART ran at 43–48%. 2025 is 79% e-bike trips; 4.7% are dockless.

## 2026-10-08 · M3 + F5 · station forecast
**Did**
- `ml/forecast/`: direct multi-horizon model. Rows are (station, origin t, horizon 1–14) and every feature uses
  only data up to t: last value, previous day, 7-day mean, the seasonal-naive value, the mean of the last 4 same
  weekdays, 28-day CV, and target-date calendar + US federal holiday flags. Values are scaled by the station's
  28-day mean so one global LightGBM fits all stations. Quantile objectives give p10/p50/p90, which are then
  sorted and clipped at ≥ 0. Rows whose 28-day window has a missing day are dropped. Seeds are fixed and
  `deterministic=True`.
- Walk-forward: 6 folds, origins every 14 days ending 2025-12-17, each trained only on targets ≤ its origin
  (730-day window; locally that means 2025-01-29 onwards, because 2020–2024 isn't loaded). Paired bootstrap over
  stations (B = 1000, seed 0).
- Results (local, data through 2025-12-31, 50 stations, 4,200 test rows):

  | | LightGBM (p50) | Seasonal naive |
  |---|---|---|
  | MAE | **364.9** [277.1, 470.1] | 548.5 [416.9, 698.2] |
  | RMSE | 819.3 [548.2, 1080.2] | 1246.7 [857.4, 1630.2] |

  **MAE improvement 183.7, 95% CI [139.5, 234.1]: excludes zero.** Per fold, MAE (model vs baseline):
  242 vs 250 · 196 vs 285 · 200 vs 267 · 518 vs 637 · 230 vs 828 · 802 vs 1024. The big wins are the
  Thanksgiving and Christmas folds, where repeating last week fails.
- Outputs: `marts.forecast_station_daily` (latest run, replaced) and `ml.forecast_runs` (appended: metrics + CIs,
  coverage, per-fold JSON, params). Dagster asset `forecast_station_daily` (group `ml`) + job/schedule
  `weekly_forecast` (Mondays 09:00 Pacific). `tasks.py forecast`. One full run takes ~1–3.5 min locally.
- F5 explorer: ARIA combobox ("mac" → MacArthur; ↑/↓, Enter, Esc), 5 station chips, and a chart with actuals solid,
  forecast dashed and the p10–p90 band in `interval-fill`. Caption: "Expect about 11,400 entries on Tue, Jan 6,
  likely between 10,100 and 14,100". The source line says "Forecast from data through Dec 31, 2025", plus model vs
  baseline error and the measured interval coverage.

**Found**
- **The intervals are too narrow:** p10–p90 held 47.5% [45.8, 49.3] of actual days, not 80%. The worst fold
  (Christmas) held 21%. The site says so. Not tuned on the test folds.
- New Year's Day is not in the training window (it starts Jan 29), so the forecast for Jan 1 2026 is implausibly
  high (Embarcadero p50 10,275). Expected with one contiguous year; more history (BigQuery 2018–2025) should fix it.

**Fixed**
- LightGBM with 4 threads ran up to 10× slower inside the full test session (thread contention). `n_jobs` is now a
  parameter (default 4); the tests use 1, and the forecast tests went from ~60 s to ~12 s.

**Next**
- Conformal calibration of the interval (calibration split inside the training window), and train on the full
  BigQuery history so holidays are seen more than once.

## 2026-10-08 · M1 · Oracle VM deployment files (not deployed)
**Did**
- `deploy/oracle/`: `transitpulse-dagster-daemon.service` (schedules + run queue) and `transitpulse-dagster-web.service`
  (UI on 127.0.0.1 only, reached by SSH tunnel). Both run as the non-root `transitpulse` user from
  `/opt/transitpulse` with `EnvironmentFile=/etc/transitpulse/transitpulse.env` and the venv first on `PATH`
  (SparkRunner calls bare `python`). `Restart=on-failure`; `MemoryMax=` 6 G (daemon, includes a Spark run) and
  1 G (web); `Nice=10` and `CPUWeight=50`, so SeismicSoCal keeps priority.
- `bootstrap.sh` (bash, `set -euo pipefail`, idempotent; shellcheck clean). It warns on non-aarch64 and installs
  git + Java 17 with apt or dnf, detecting `JAVA_HOME`. It then creates the user and directories, installs uv,
  clones or fast-forwards the repo, runs `uv sync --frozen` for the pipeline/dbt/ml/spark groups, and installs the
  env file only if absent (mode 600). It copies `dagster.yaml` and runs `dbt parse`. It checks that the key file is
  owned by `transitpulse` with mode 600 and refuses to start services otherwise; the key is never printed.
  Last, it installs the units and runs `daemon-reload` + enable/restart.
- `docs/ORACLE_VM.md` runbook; `tests/test_oracle_vm.py` (static checks). CI now syncs the dbt/ml/pipeline groups,
  runs `dbt parse` before pytest (the Dagster test needs the manifest), excludes `localdata`, and runs shellcheck.

**Blocked / not done**
- Nothing deployed: the VM can't be reached from here. Runs on the existing VM next to `seismicsocal.service`;
  no second VM assumed. OS (Oracle Linux vs Ubuntu) unknown, hence the apt/dnf detection.

## 2026-10-08 · Oracle VM · sized for the real VM
**Found**
- SeismicSoCal VM (measured via SSH): VM.Standard.A1.Flex **1 OCPU / 5.8 GiB, 3.2 GiB available, no swap**;
  SeismicSoCal ~0.8 GB + MLflow ~1.1 GB; load ~0; disk 31 GB free. Tenancy limits page: 1 A1 core used, 3 available.
- Oracle halved the Always Free A1 allowance on 2026-06-15 to **2 OCPU / 12 GB per tenancy** (max 2 instances).
  A Spark run (~5–6 GB) doesn't fit next to SeismicSoCal on the current shape.

**Decided**
- Recommend resizing the existing VM to 2 OCPU / 12 GB (= the free allowance) rather than a second VM.

**Changed** (follow-ups from the build-loop final review)
- Daemon unit: removed `MemoryHigh=5G` (a soft cap below the Spark peak throttled the run), `MemoryMax=7G`;
  web unit: removed `MemoryHigh`. Both: `OOMScoreAdjust=500`, so the kernel kills TransitPulse before SeismicSoCal.
- New env knobs (defaults unchanged elsewhere): `TP_SPARK_DRIVER_MEMORY` (SparkRunner), `TP_ML_THREADS`
  (LightGBM `n_jobs`), `DBT_THREADS` (all dbt targets); the VM env example sets 4g / 2 / 2.
- `docs/ORACLE_VM.md`: sizing section with the free-tier limit, the measured VM, the resize steps, an optional
  swap file, and `systemctl edit` drop-ins instead of editing unit files (bootstrap re-copies them).
- Verified: pytest 42/42, Oracle VM + forecast tests, shellcheck, `systemd-analyze verify`, Dagster validate.

## 2026-10-08 · deploy · TransitPulse running on the Oracle VM
**Did**
- VM resized to 2 OCPU / 12 GB (free maximum) + 4 GB swap; `bootstrap.sh` installed Java 17, uv, the repo and both
  Dagster units next to `seismicsocal.service` (key check refused to start until the key was transitpulse:600, as designed).
- First VM runs: `baywheels_ingest` loaded **25,989,969 trips (2018 → 2026-09)** into `raw.baywheels_trips`; the
  `warehouse` run rebuilt every BART model on BigQuery as `sa-pipeline`.

**Found**
- The warehouse run failed one test: `accepted_values` on `stg_baywheels_trips.rideable_type` — **8 trips in
  September 2024 are `electric_scooter`**. Local data (2019 + 2025 only) never had it. dbt skipped the two bike models
  downstream (`fct_bike_trips_daily`, `mart_bikes_vs_trains`).

**Fixed**
- Staging keeps the source truthful (`electric_scooter` is an accepted value); `fct_bike_trips_daily` counts bikes only
  (`where rideable_type != 'electric_scooter'`), so bikes-vs-trains isn't inflated. Verified: all 10 staging tests
  pass on BigQuery, dry run of the fact passes, local `stg_baywheels_trips+` build passes.

## 2026-10-09 · deploy · VM pipeline complete on BigQuery
- After the scooter fix, the VM's `warehouse` run built `fct_bike_trips_daily` (3,165 days, 2018 → 2026-09) and
  `mart_bikes_vs_trains` (105 months). No BigQuery errors.
- First `weekly_forecast` on BigQuery (run `fc-20261009T045221Z-558f0e`, 2 threads, 21 min on 2 OCPUs): trained on
  730 days (2024-01-02 → 2025-12-31). MAE **283.1** [215.9, 364.6] vs baseline 548.5; improvement 265.4
  [199.6, 339.9]; p10–p90 coverage **0.705** [0.691, 0.719] (local, 2025-only training: 0.475). Still under the
  nominal 0.80, but far closer. Wrote `marts.forecast_station_daily` (700 rows) and `ml.forecast_runs`.
- Schedules turned on in the VM's Dagster (Automation page).

## 2026-10-09 · build loop iter 1 · backfill fix, calibrated forecast band, honest forecast wording
**Did**
- **B2 (silent backfill loss).** `fct_trips_hourly`'s incremental filter only took `trip_date >= max − 35`, so a year
  loaded *after* a newer one was skipped: the local Parquet held 2018–2025 but the facts only 2019 + 2025. The filter
  now also takes any date not yet in `{{ this }}` (anti-join). New singular dbt test
  `assert_fct_trips_hourly_has_every_od_date` (error). `tests/test_dbt_regressions.py` builds Dec 2025, adds
  2018-12-31 / 2019-01-02..04 / 2019-12-30..31 and rebuilds incrementally; it failed before the fix (the new dbt test
  reported 6 missing dates) and passes after.
- Local `dbt build` after the fix (2 threads): 84/84 in 2 min 6 s. `fct_trips_hourly` now has **67,770,440** rows and
  `fct_station_daily` **143,958**, exactly BigQuery's counts; `data/transitpulse.duckdb` 118 → 369 MB. The incremental
  rerun (the `dbt-build-local` check) takes 2 min 21 s.
- **Calibration.** Rolling split-conformal on CQR scores (`ml/forecast/evaluate.py`): the walk-forward runs 6 warm-up
  folds before the usual 6 test folds; each test fold widens/narrows p10/p90 by the finite-sample 80% quantile of
  `max(p10 − y, y − p90) / level` from the 6 folds before it (asserted: all their targets ≤ its origin). The
  published forecast uses the last 6 folds. New columns: `lower`, `upper` in `marts.forecast_station_daily`;
  `coverage_calibrated(_lo/_hi)`, `interval_nominal`, `interval_method`, `conformal_q`, `calib_folds`,
  `mean_width_raw`, `mean_width_calibrated` in `ml.forecast_runs`. `--calib-folds` CLI; the Dagster asset passes 6.
- **B5 (run log can't evolve).** DuckDB adds missing columns before `insert … by name`; BigQuery appends with
  `ALLOW_FIELD_ADDITION`. Without this the VM's next weekly run would have failed on the new columns.
- **API.** `/api/forecast/{code}` reads `select *` from both tables, so it serves the old production schema and the
  new one. Items gain `lo`/`hi`; `model.interval = {method, nominal, coverage, coverage_ci, calibrated}`;
  `forecast_start`/`forecast_end` added. Existing fields unchanged.
- **B6 (copy overclaims).** Caption, legend, hidden-table headers and chart text alternative are worded from
  `model.interval`: "80% range" only if calibrated and within ±5 pts of 80%, else "model range (10th–90th
  percentile)". The caption carries the year and is past tense; the source line gives the window ("It covers
  Jan 1–14, 2026, the 14 days after the latest ridership BART has published") and says "narrower than it should be"
  only below 75% / "wider than needed" only above 85%. Heading "Two weeks ahead…" → "A 14-day forecast, station by
  station". Fixtures: `forecast-EMBR.json` has the new fields (calibrated, 79%); `forecast-MCAR.json` stays on the
  old shape. The two allowed caption assertions were replaced by the new exact strings.

**Measured** (local run `fc-20261009T131810Z-a3cda6`, data through 2025-12-31, trained from 2024-01-02)
- MAE **283.147** [215.9, 364.6] vs baseline 548.5; improvement 265.4 [199.6, 339.9]; RMSE 642.6. An in-memory
  `calib_folds=0` run on the same data gives MAE 283.14707110926554, bit-identical (calibration doesn't touch p50),
  and the same numbers as production `fc-20261009T045221Z-558f0e` (283.1, coverage 0.705), as predicted.
- Coverage vs 0.80: raw **0.705** [0.691, 0.719] → calibrated **0.730** [0.717, 0.744]. Per test fold raw →
  calibrated: 0.807 → 0.833, 0.757 → 0.786, 0.697 → 0.726, 0.650 → 0.683, 0.896 → 0.909, 0.420 → 0.444 (Christmas).
- Width (÷ level) 0.241 → 0.251 (ratio 1.04, far from the 2.5 "too wide" flag). Per-fold q 0.004–0.006; the
  published forecast's q is 0.023 because its calibration window includes the Christmas fold.
- Run time 64.8 s uncalibrated → 122.8 s calibrated (1.9×) on 4 threads here; the VM's ~21 min run should become
  ~40 min.
- BigQuery dry run (free, not executed) of the compiled incremental SQL: 2,981,902,160 bytes (2.98 GB) with or
  without the anti-join (the estimate can't prune on a subquery filter either way), under the 10 GB threshold, so no
  `INFORMATION_SCHEMA.PARTITIONS` macro. Within the 20 GB `dev` cap.

**Decided**
- Decision rule applied: calibrated coverage 0.730 is < 0.75 but closer to 0.80 than raw, so the calibrated band is
  published and called the **model range** with the measured 73% and "narrower than it should be".
- The API serves the raw band if a calibrated run is *farther* from nominal than the raw one (the plan's "if
  calibration makes it worse, publish raw"), so this needs no manual step on the VM.
- The band is clipped to contain p50 and stay ≥ 0, also during back-testing, so the published band and the measured
  coverage are the same thing.
- `model.interval_coverage` keeps meaning the raw p10–p90 coverage (existing field, unchanged).
- Rejected: a global inflation factor fitted on the test folds (tuning on the test set); per-horizon q (300 scores
  per horizon per window, noisy); refitting a calibration model per fold (doubles cost again). Holiday-aware
  calibration is the obvious follow-up for the Christmas fold.

**Found**
- Calibration from the 6 preceding folds barely moves the band (q ≈ 0.005 of level) because those folds were already
  near 80%; the shortfall is concentrated in the holiday fold. Conformal calibration under a shift like Christmas
  can't anticipate it.
- `test_api_data.py::test_forecast_from_duckdb` compares whole dicts, so its expected forecast item and `model` were
  extended with the new keys (`lo`, `hi`, `interval`), with exact values, not loosened.
- A new local test first assumed 365 days in 2020; BART's 2020 file is missing 4 days, so the check is ≥ 360 days a
  year plus "every staged date is in the fact".

**Not done (next iterations)**: B1, B3, B7, B8 (iteration 2); agent + B4 (3); Cloud Run code (4); Locust (5).
Production keeps the pre-calibration run until the VM pulls this code (the API falls back to the raw band).

## 2026-10-09 · build loop iter 2 · bug hunt (ISO year, schedules, rolling window, timetable expiry) and the Ask agent
**Did**
- **B1 (ISO week vs calendar year).** `dim_date` gains `iso_year` (dispatched macro: `extract(isoyear …)` on BigQuery,
  `isoyear()` on DuckDB). `mart_recovery` and `mart_kpis_daily` take the 2019 baseline from `iso_year = 2019`
  (2018-12-31 → 2019-12-29), and `mart_recovery` leaves out ISO-2019 days instead of calendar-2019 days. The API's
  peak-share delta now matches (ISO year, ISO week) pairs in Python from `mart_kpis_daily` dates, so it doesn't need
  the new `dim_date` column (production BigQuery gets it at the next `dbt build`). New tests:
  `test_dbt_regressions.py::test_recovery_baseline_uses_iso_year_2019` (failed before: EMBR's week-1 baseline came
  out 90 instead of 66) and `test_api_data.py::test_peak_share_delta_uses_iso_year_weeks` (failed before: the
  baseline mixed in Dec 30–31, 2019).
- **B3 (January ingests the wrong year).** `monthly_ridership` / `baywheels_monthly` request the partition of the
  previous month's year; run keys unchanged. `test_dagster_defs.py::test_monthly_schedules_ingest_previous_months_year`
  (Jan 6 2027 → "2026", Jul 6 2026 → "2026", both schedules) failed before with "2027".
- **B7 (28-row "28-day" average).** `rolling_28d_avg_entries` is now the mean over the days present in the calendar
  window [d − 27, d] (a range self-join on the daily totals; `RANGE` over dates isn't portable), plus
  `rolling_28d_days`. `test_rolling_28d_average_ignores_gaps` failed before (the column didn't exist / 2025-12-01
  averaged in 2019 days). Two schema tests added (not_null, non_negative).
- **B8 (timetable expiry).** `schedule.js` gains `timetableRange` / `isOutsideTimetable` (service start/end plus
  added dates). Outside the range the map notice reads "This site's BART timetable ended on Jan 10, 2027. Positions
  can't be shown until it's updated." (or "starts on …") and hides *Jump to 8:00 AM*. Tests: `tests/web/timetable.test.mjs`
  and `site.spec.js` "map: an expired timetable says so" (clock 2027-02-01 08:00 PT).
- **M5 agent (whole).** `api/agent/` (`guardrails.py`, `prompts.py`, `llm.py`, `graph.py`, `tracing.py`,
  `service.py`), agent methods on both warehouses, `POST /api/ask` as `fastapi.sse` with rate limit, proxy-aware
  client IP and a daily byte budget; `eval/questions.yaml` (66 in-scope + 10 refusals), `eval/scoring.py`,
  `eval/gold.py`, `eval/run_eval.py`, `tasks.py eval`. Tests: `test_agent_guardrails.py` (8),
  `test_agent_graph.py` (7), `test_ask_api.py` (5), `test_agent_eval.py` (5), `tests/local/test_agent_local.py`.
  The dbt fixture generator moved from `test_dbt_fixture.py` to `tests/dbt_fixture_data.py` (that test's assertions
  unchanged); `tests/conftest.py` builds it once per session, in a child process, plus a small synthetic forecast.
- **B4 (SSE client).** `web/js/ask.js` has a spec-compliant incremental parser (`createEventParser`: LF/CRLF/CR, a CR
  split from its LF across chunks, multi-line `data:` joined with "\n", comments, unfinished events dropped). A 4xx
  says the question couldn't be read, a 5xx says the analyst had a problem, a dropped stream or one that ends with no
  answer/refusal/error shows an error instead of a dangling step list. Tests: `tests/web/ask.test.mjs` (3) and
  `tests/web/ask.spec.js` (5, streams mocked with `page.route`, using CRLF and multi-line data).
- CI's python job and `tasks.py test` now sync the `agent` group and exclude the new `docker` marker (registered in
  `pyproject.toml`), so the agent tests run there too. `.gitignore`: `eval/results/*` except `summary-*.json`.

**Measured**
- Local `dbt build` after B1/B7: 88/88 (73 data tests) in 2 min 17 s.
- KPI before → after on the local warehouse (28 days to 2025-12-31):
  - Recovery tile 0.38286 → **0.38209**. Days in ISO week 1 of 2026 changed: 2025-12-29 0.3182 → 0.3131,
    12-30 0.3398 → 0.3344, 12-31 0.2618 → 0.2576; EMBR on 12-31 0.1683 → 0.1646, MONT 0.1363 → 0.1316.
  - Peak-share baseline for weeks 49–52 + 1: 0.118151 → 0.118093, so the tile's delta −0.873 → **−0.868 pts**.
  - 2025 average service-weekday recovery 0.431 → 0.430.
  - Rolling 28-day: unchanged where there's no gap (e.g. 2025-12-31 115,500.7, 28 days). BART's 2020 file is
    missing 4 days (Jan 21, Feb 19, Feb 24, Apr 28), so 85 days between 2020-01-22 and 2020-05-25 now average 26–27
    days instead of reaching back 29–30 calendar days; 2018-01-01..27 average 1–27 days.
- BigQuery: free dry runs (not executed) of the compiled `dim_date`, `mart_kpis_daily` and `mart_recovery` (with
  `dim_date` inlined, since production's doesn't have `iso_year` yet) are valid: 0.65 GB, 2.28 GB and 0.65 GB
  estimated, under the 20 GB `dev` cap. The inequality join in the rolling CTE is accepted (inner join).
- Agent eval, fake LLM (oracle, harness check): execution 1.0, refusal 1.0, 0 guardrail rejections, p50 0.03 s.
- **Agent eval, llama3.1:8b (Ollama, RTX 4060, local DuckDB), 76 questions in 3 min 32 s:** execution accuracy
  **0.273** (18/66), refusal accuracy **1.0** (10/10), 0 guardrail rejections, 11 queries that failed twice, 7
  in-scope questions refused (bikes and `ml.forecast_runs` questions), latency p50 2.4 s / p95 6.4 s. By tag: station
  0.47, forecast 0.50, kpi 0.27, bikes 0.18, trend 0.07, od 0.0. Summary committed as
  `eval/results/summary-ollama-20261009T143938Z.json`. Typical misses: summing `fct_station_daily` instead of reading
  `mart_kpis_daily`, filtering one day (`trip_date = '2025-01-01'`) for a year, `COUNT(trips)` instead of
  `SUM(trips)`, station names where codes are needed, extra or missing columns.
- Test counts: pytest 80 (was 51, ~40 s), node 23 (19), Playwright 35 (29), localdata 8 (7).

**Decided**
- The API's ISO-week matching is done in Python on dates rather than with `dim_date.iso_year`, so the API keeps
  working against production BigQuery before the VM rebuilds `dim_date` (same reasoning as the forecast `select *`).
- `mart_recovery` now excludes ISO-year-2019 days (2018-12-31 drops out, 2019-12-30/31 come in, compared with ISO
  week 1 of 2019), as the plan specified. `mart_kpis_daily` still outputs 2019 days (recovery ≈ 1 there).
- Rolling window: range self-join on the ~2,900 daily totals, chosen over `RANGE BETWEEN INTERVAL` (DuckDB and
  BigQuery spell it differently and BigQuery needs a numeric order key) and over a date spine (would invent zero days).
- `/api/ask` checks (503, rate limit, budget) live in a FastAPI dependency, because a streaming handler can't change
  the status once it has started; the handler only yields `ServerSentEvent`s. Returning a response object from an
  `EventSourceResponse` route doesn't work (FastAPI iterates the return value).
- The agent's warehouse is `None`-safe: with the agent on but no warehouse, off-topic questions are still refused and
  in-scope ones get an `agent_unavailable` error (useful for the container smoke test).
- `fct_trips_hourly` is not on the agent's allowlist (68M rows; a careless query would read GBs on BigQuery);
  `mart_od_flows` covers origin-destination questions.
- The forecast tool queries p10/p50/p90 (not `lower`/`upper`) so it works on both forecast-table schemas.
- Eval scoring is strict on column count (an extra column is wrong), lenient on order/names/float noise. With
  accuracy < 50%, the plan's rule says: propose the few-shot arm (schema card + retrieved examples) for the next run.
  I did not tune the prompts on the eval set.
- The fixture warehouse is built in a child process: dbt-duckdb keeps its connection open in the process that ran
  it, and DuckDB then refuses the agent's differently configured connection to the same file.
- Rejected: `sse-starlette` (FastAPI 0.142 has `fastapi.sse`); a chart tool (the client draws no charts); an LLM-only
  router (the keyword pre-filter catches "drop the tables"/"ignore your instructions" before any model call).

**Found (not fixed)**
- ISO year 2019 has 52 weeks, so days in ISO week 53 (2020-12-28..2021-01-03, 2026-12-28..2027-01-03) have no
  baseline and a NULL recovery. Small and pre-existing; options are to map week 53 to week 52 or leave it NULL and
  say so in METRICS.
- A long-running Dagster daemon keeps the `years` partitions from import time; on Jan 6 the schedule now asks for
  the previous year, which exists, but backfilling the new year needs a restart (runbook note, M7).
- `web/data/schedule.json` expires 2027-01-10; refreshing `web/data` from a newer GTFS feed is a user action.

**Not done (next iterations)**: Cloud Run code (Dockerfile, Terraform + WIF, deploy workflow, runbook, container
smoke tests) and Locust. Production keeps the old `dim_date`/marts until the VM pulls this code and runs `dbt build`.

## 2026-10-09 · build loop iter 3 · Cloud Run deploy code (M7) and the Locust load test
**Did**
- **Image.** `Dockerfile` (multi-stage) and `.dockerignore` (an allowlist).
  - Build stage: `python:3.12-slim-bookworm` plus the pinned uv binary (`ghcr.io/astral-sh/uv:0.12.11`). It runs
    `uv sync --frozen --no-dev --no-default-groups --group agent --no-install-project` with bytecode compiled.
  - Runtime stage: the same base with the venv, `api/` and `web/` only, root-owned and run as uid 10001.
  - `CMD sh -c "exec uvicorn … --port ${PORT:-8080}"`.
- **Container smoke tests.** `tests/deploy/test_container.py` (marker `docker`, image `${TP_TEST_IMAGE:-transitpulse-api:loop}`,
  random host port, `--memory 512m`, containers removed afterwards), 5 tests:
  - non-root and read-only code
  - site, health and the three cache-header classes
  - 503 from the data endpoints and `/api/ask` without a warehouse
  - the fake-LLM agent refusing an off-topic question over SSE
  - no keys, `.env`, DuckDB, tfstate, `.git`, `node_modules`, tests or dev packages in the image
- **Terraform** (validated, **not applied, not planned against the backend**):
  - `cloudrun.tf`: the service, the public invoker on that service, and the Gemini secret (no version)
  - `wif.tf`: pool, GitHub provider pinned to repo + main, and `sa-deploy`'s three narrow bindings
  - `secretmanager.googleapis.com` added to the API list
  - new variables `agent_enabled` (false), `gemini_model`, `api_initial_image` (Google's hello image) and
    `github_repository`
  - outputs `api_url`, `github_wif_provider`, `github_deploy_service_account`
  - commented optional variables in `terraform.tfvars.example`
- **`deploy.yml`.** Push to `main` + `workflow_dispatch`. The job runs only if `vars.DEPLOY_ENABLED == 'true'`. It
  authenticates through WIF (`id-token: write`, repo variables `GCP_WIF_PROVIDER` / `GCP_DEPLOY_SA` / `GCP_PROJECT`),
  then builds, pushes the image tagged with the commit SHA, runs `gcloud run deploy --image` and curls the result.
- **CI.** A `container` job in `ci.yml` (build + `tests/deploy`, prints the image size). Both workflows pass
  actionlint.
- **`tests/test_infra_cloudrun.py`** (8 tests, python-hcl2 8.1.4 + pyyaml added to the `dev` group). It covers
  scaling, the runtime SA and its exact roles, that only `run.invoker` is public, the WIF condition and principalSet,
  `sa-deploy`'s exact roles, budgets $1/$5 and keep-3, the deploy workflow (gate, OIDC, no `credentials_json`, no
  terraform command or action), and the agent being off by default.
- **Load test.**
  - `load/locustfile.py`: kpis 3 : forecast 3 : ask 1, each user hits all three on start, and an ask fails unless its
    SSE stream ends in `answer`/`refusal`.
  - `load/run_local.py`: builds the dbt fixture warehouse in a child `uv run --inexact --group dbt` process, fills
    in the forecast run row's missing columns, starts uvicorn with the fake LLM and the rate limit lifted, runs
    Locust headless (1/10/25 users or `--users N`), reads the CSV percentiles, stops the server, and exits 1 on any
    failed request.
- `tasks.py image` and `tasks.py load`.
- **Docs.**
  - new runbook `docs/CLOUD_RUN.md`
  - `infra/README.md`, `CURRENT_STATE.md`, `SKILLS_MAP.md` (#1, #3, #13, #18; every link and line anchor checked by
    script), `IMPLEMENTATION_PLAN.md` M7 markers, `README.md` (deploy + load section with the numbers)
  - `ORACLE_VM.md`: restart the daemon after New Year

**Measured**
- Image: `docker image inspect` Size 120,062,457 B; `docker save | gzip -1` **119,175,652 B (≈ 119 MB)**, under the
  166 MB limit, so 3 kept versions ≈ 357 MB fit the 0.5 GB free tier. `keep_count` stays at 3; nothing needed slimming
  (`langchain-ollama` is tiny). Largest items: DuckDB's `.so` 58 MB, zstandard 23 MB, google 21 MB, grpc 19 MB
  (uncompressed). The venv is 243 MB uncompressed.
- Container locally: `/healthz` answers ~1.5 s after `docker run`, the first `/api/ask` (fake LLM, refusal) takes
  0.7 s, and memory is 76 MiB of 512 MiB.
- Docker build ~17 s from a warm cache.
- Locust (this PC, fixture warehouse, fake LLM, 20 s per step), **0 failures**. Each cell is p50 / p95 / p99 in ms:

  | Users | Req/s | forecast | kpis | ask |
  |---|---|---|---|---|
  | 1 | 1.2 | 54 / 62 / 62 | 5 / 540 / 540 | 42 / 870 / 870 |
  | 10 | 11.8 | 4 / 8 / 17 | 4 / 11 / 17 | 43 / 58 / 58 |
  | 25 | 29.7 | 5 / 14 / 30 | 4 / 22 / 29 | 37 / 140 / 140 |

  The 1-user tails are the cold first requests: cache misses and the agent graph being built.
- pytest 88 passed (was 80) in ~39 s; node 23; Playwright 35; localdata 8; `tests/deploy` 5.

**Decided**
- **No `terraform apply` in Actions** (as the plan says). It would need owner-level rights for `sa-deploy`, so
  Terraform stays a human step and `deploy.yml` changes only the image. This differs from IMPLEMENTATION_PLAN M7, and
  the user should confirm it.
- **The Gemini secret is always created, never given a version by Terraform.** Its IAM binding and the env var exist
  only when `agent_enabled`.
  - Rejected: a `google_secret_manager_secret_version` resource, which would put the key in state.
  - Rejected: creating the secret only when enabled, because then the version can't be added before switching on.
- **The builder stage is `python:3.12-slim-bookworm` + the uv binary**, not the `ghcr.io/astral-sh/uv:python3.12-*`
  image. That keeps the venv's interpreter path identical between stages and reuses the base already pulled. uv is
  pinned to the local version.
- **`.dockerignore` is an allowlist** (`*` plus `!api/ !web/ !pyproject.toml !uv.lock !.python-version`), plus the
  plan's explicit exclusions. `pipeline/spark/Dockerfile` copies nothing, so it is unaffected.
- **`startup_cpu_boost = false`** (it bills extra CPU at startup), and the image ships compiled bytecode to keep cold
  starts short instead.
- **Containers get `--memory 512m` in the smoke tests**, matching Cloud Run.
- **The secret scan runs as root**, so no directory is skipped. It ignores directories named `credentials` inside
  `site-packages`: google-genai ships two source packages with that name.
- **`deploy.yml` has no `environment:`**: the variables live at repo level and nothing auto-creates an environment.
- **Load test.**
  - The per-IP rate limit is lifted, because every simulated user is 127.0.0.1.
  - The shared fixture's forecast run row is completed in the load harness rather than in `tests/dbt_fixture_data.py`,
    which leaves the shared test helper alone.
  - Missing endpoints only warn: the plan says exit non-zero only on startup or request failure, and `on_start`
    makes every endpoint appear anyway.
- **BigQuery quota.** The runbook recommends 20 GiB/day per user ("Query usage per day per user") before the agent is
  enabled, because the agent's 10 GB daily budget is per process and resets on every cold start.

**Found**
- The load test's first run failed every `/api/forecast` call with a 500 (`KeyError: 'mae_diff_lo'`). The cause: the
  agent-test fixture's `ml.forecast_runs` row lacks the run metrics every real run writes. This is not an API bug,
  because production rows always have them. The harness now adds the columns.
  - Possible hardening, not done: `_forecast` could use `.get()` for `mae_diff_lo/hi`.
- No DuckDB "different configuration" clash showed up under 25 concurrent users mixing data endpoints and the
  agent's locked-down connection. The API's 1 h / 6 h response cache keeps the plain connections rare after warm-up.
- The site's timetable ships inside the image, so the 2027-01-10 GTFS expiry needs a new image after the user
  refreshes `web/data` (in the runbook).

**Not done**: anything in GCP (by design). Cloud Run cold start and remote latency can only be measured after the user
applies and deploys. The local `.terraform` dir and the state in `gs://transitpulse-511002-tfstate` were not
touched: no `init`, `plan` or `apply`.

## 2026-10-09 · build loop iter 4 · final review revision 1 (R1–R6)
The Architect's final review rejected iteration 3 for six small defects. This entry fixes only those.

**Did**
- **R1 · band label.** A calibrated band is p10/p90 widened by the conformal correction, so it can no longer be called
  the "10th–90th percentile". `rangeLabel` (`web/js/forecast.js`) now has three cases:
  - calibrated and within 5 points of 80% → "80% range"
  - calibrated but outside that → "calibrated model range"
  - uncalibrated → "model range (10th–90th percentile)"

  For the calibrated model range, the source line says "the calibrated model range (the model's 10th–90th
  percentile, widened using earlier back-test weeks)". The hidden table's headers read "Calibrated model range:
  low/high". The local run (calibrated, 73%) now shows "calibrated model range". Production (uncalibrated, 70%) is
  unchanged. New test: `tests/web/forecast-label.test.mjs`.
- **R2 · `_forecast`.** `api/routes/data.py` reads every run-log column with `.get()`, and `mae_diff_ci` is `null`
  unless both bounds exist. New test: `test_forecast_tolerates_missing_optional_run_columns`. The fixture completion
  in `load/run_local.py` stays (harmless).
- **R3 · BigQuery agent timeout.** `agent_query` sets `job_timeout_ms = timeout_s × 1000`, so BigQuery stops the job
  itself. On `concurrent.futures.TimeoutError` it calls `job.cancel()` (errors suppressed) and raises
  `AgentQueryError("The query took longer than … s.")` instead of a generic `agent_error`. New test:
  `test_bigquery_agent_query_timeout_is_capped_and_reported`.
- **R4 · rate limiter.** Above 10,000 keys, the cleanup drops every key whose newest hit is at least 60 s old, not
  only empty deques. Idle clients are forgotten, and the O(n) scan no longer repeats on every request. New test:
  `test_rate_limiter_forgets_idle_clients` (10,001 keys at t=0, then one call at t=61 → 1 key left).
- **R5 · eval summaries.** `eval/run_eval.py` writes `summary-<llm>-<ts>.json` only with `--save-summary`, and
  `--results-dir` makes the output directory injectable. The gitignored per-question detail is still written.
  - Deleted the two duplicate summaries `…150528Z` and `…155658Z`. Kept `…143938Z`, the one the docs cite.
  - New test: `test_eval_writes_summary_only_when_asked`, which uses the fake LLM on the session fixture and two
    questions.
- **R6 · deploy gate.** `deploy.yml` now runs in this order:
  1. build
  2. `astral-sh/setup-uv`
  3. `uv run pytest -m docker tests/deploy` with `TP_TEST_IMAGE` = the built image
  4. auth and `docker push`
  5. deploy and curl

  `CLOUD_RUN.md` says that deploy doesn't wait for `ci.yml`, so only the container smoke tests gate it. It also tells
  the user to check, after the first deploy, that the right-most `X-Forwarded-For` entry is the real client IP. New
  test: `test_deploy_workflow_smoke_tests_image_before_push`.

**Measured**
- `node --test tests/web/`: 24/24.
- pytest (not spark/gcp/localdata/docker): all pass, including the 5 new tests.
- Playwright: 35/35, including the 320 px tests.
- `ruff check` and `format --check`: clean. actionlint: clean.
- `docker build` (cached) and the 5 container smoke tests: pass.
- SKILLS_MAP links: re-verified by script, 0 broken.

**Decisions**
- **Two more test edits than R1 listed.** R1 allowed editing only `forecast-caption.test.mjs:69-70`. But lines 31
  and 37 of the same file also assert that a *calibrated* band off target (0.74/0.86/0.705/0.42, and 0.7 in the
  caption) is "model range (10th–90th percentile)". That is exactly the behaviour R1 removes, so they can't pass
  with R1 implemented. I changed them to the new label with the same exactness. The uncalibrated assertions are
  untouched.
- **Kept the "80% range" source wording for a calibrated band near target** ("the 80% range, calibrated on earlier
  back-test weeks"). EMBR's existing Playwright and node assertions require it and may not change. The "widened
  using earlier back-test weeks" wording is used for the calibrated model range.
- **`job_timeout_ms` is stored as a string** by google-cloud-bigquery 3.46 (`'2500'`). The test compares
  `int(config.job_timeout_ms)`.

**Not done**: no forecast or dbt re-run (nothing in `ml/` or `dbt/` changed), no GCP access, no Ollama run.

## 2026-10-09 · Oracle VM · bootstrap blocked by another program's apt source
**Found**
- Updating the VM (`bootstrap.sh`) stopped at `apt-get update`: the **Caddy** package source (SeismicSoCal's web
  server, `dl.cloudsmith.io/public/caddy/stable`) now answers `402 Payment Required`, and `set -e` aborted the script
  before any TransitPulse step. Caddy itself is installed and unaffected; only its update channel is broken.

**Fixed**
- `bootstrap.sh` skips apt when git, curl, ca-certificates and Java 17 are already installed (`dpkg-query`), and
  treats a failing `apt-get update` as a warning; `apt-get install` still fails if our own packages can't be fetched.
  Verified in an Ubuntu 22.04 container with the broken Caddy source: all-installed → apt skipped; git missing →
  warning, git installed. Shellcheck clean; VM file tests pass.

## 2026-10-09 · deploy · production on the calibrated forecast
- VM updated to `025f80a` (bootstrap fetched from GitHub; apt skipped). VM `warehouse` run rebuilt BigQuery with the
  ISO-year baseline (`dim_date.iso_year`), calendar-day rolling window (112 of 2,918 days have < 28 days in their
  window) and the backfill-safe `fct_trips_hourly`.
- VM `weekly_forecast` run `fc-20261009T215231Z-bd85f0` (40 min): MAE 283.1 vs baseline 548.5 (unchanged);
  raw p10–p90 coverage 0.705; **calibrated 0.730 [0.717, 0.744]**, conformal q 0.023, 6 calibration folds,
  width +4%. Identical to the local run. BigQuery's `ml.forecast_runs` gained the 6 new columns via
  `ALLOW_FIELD_ADDITION` (older run rows are NULL there) — the B5 fix working on BigQuery.
- The site labels it "calibrated model range" (calibrated but > 5 pts from 80%).

## 2026-10-09 · web · static export for braedynthompson.com/transitpulse
**Why**: the site only ran on the dev PC (the VM runs the pipeline, Cloud Run isn't deployed). braedynthompson.com
is GitHub Pages built by the `portfolio` repo (`build.py` copies `static/` as-is into `site/`), so a path on that
domain must be published by the portfolio, as static files.

**Did**
- `pipeline/webexport.py` (`tasks.py export`): copies `web/` and saves every read-only GET response the page uses
  (KPIs, ridership trend, bikes vs trains, 50 station summaries, 50 forecasts) through the real FastAPI app at the
  same relative paths without extensions, so `fetch("api/...")` works unchanged on a static host; 404s are left
  out (the host 404s too). Adds `<meta name="tp-mode" content="static">` and `snapshot.json`.
- `web/js/ask.js`: in static mode the Ask box explains the analyst needs the live server instead of POSTing.
- First export from BigQuery (2018–2025): 103 responses, 0.5 MB. Previewed on a plain static server under
  `/transitpulse/` at 1440 and 390 px: no console errors or failed requests, no horizontal scroll, KPI tiles
  (incl. −5.3% YoY, which needs BigQuery's history), charts, calibrated forecast, live map, static Ask message.
- Copied to `portfolio/static/transitpulse/`; the portfolio's `build.py` publishes it at `site/transitpulse/`.

**Decided**: static snapshot on GitHub Pages ($0, no server, no cold starts) instead of Cloud Run for now; refresh by
re-running the export after new monthly data. The Ask analyst stays for a later Cloud Run deploy.

## 2026-10-09 · web · pages on braedynthompson.com, API on Cloud Run
**Why**: the user wants braedynthompson.com/transitpulse/ with both the frontend and the backend working. GitHub
Pages (the portfolio) can't run the API, and a Cloud Run domain mapping can't take a path on a domain GitHub Pages
serves. So: pages from the portfolio, API on Cloud Run, the browser calling across origins.

**Did**
- `api/settings.py` `cors_origins` (`TP_CORS_ORIGINS`) + `CORSMiddleware` in `api/main.py` (GET/POST, Content-Type
  and Accept headers, 1 h preflight cache); empty by default = same-origin only.
- Terraform: `var.site_origins` (default `["https://braedynthompson.com"]`) → `TP_CORS_ORIGINS` on the service.
- `web/js/util/api.js` `apiUrl()`: `api/...` goes to `<meta name="tp-api-base">` when present, else same origin;
  used by the data fetches (trends/forecast), station tooltips and Ask.
- `pipeline/webexport.py --api-base URL`: pages only, pointed at the live API (no snapshot, Ask enabled).
- `docs/CLOUD_RUN.md` §5: publishing the pages to `portfolio/static/transitpulse/`.
- Tests: `tests/test_cross_origin.py` (6: allowed origin incl. trailing slash, POST preflight, other origin and the
  default get no CORS, live export, https required, Terraform origin) and `tests/web/api-base.test.mjs` (4).
  pytest 99 passed, node 28, Playwright 35, terraform fmt/validate clean.

## 2026-10-09 · deploy · Cloud Run live
- `terraform apply`: 10 added, 0 changed, 0 destroyed (Cloud Run service, public invoker, WIF pool + provider pinned
  to braaaeeedyn/transitpulse @ main, sa-deploy bindings, Gemini secret without a version, Secret Manager API).
- First image `api:manual-2dd730f` pushed and deployed: revision `transitpulse-api-00002-jvl`, URL
  https://transitpulse-api-etumz4pfva-uw.a.run.app (alias https://transitpulse-api-245326382421.us-west1.run.app).
  `/`, `/api/kpis` (5.2 s cold incl. first BigQuery queries, then ~0.15 s), `/api/forecast/EMBR`, `/data/...` all
  200; `access-control-allow-origin: https://braedynthompson.com` on API responses.
- **Found**: `/healthz` returns Google's own 404 on `*.run.app` (the front end answers paths ending in "z"); the
  startup probe still works because it reaches the container directly. deploy.yml's post-deploy curl would always
  fail. **Fixed**: added `/api/health` (same handler); deploy.yml and docs/CLOUD_RUN.md use it; test added.
  pytest 100 passed, actionlint clean.

## 2026-10-09 · M4 · build loop iter 1 · eBART study: data, estimator, synthetic validation (no real estimate)
**Did**
- Pre-registration: `analysis/causal/preregistration.json` was already committed (`4c80c9b`) byte-identical to the
  Architect's copy (sha256 `a05df985…40f4`); untouched. `analysis/causal/design.py` loads and validates it (sets
  disjoint and covering all 50 stations, 34 controls, corridor = treated + new, placebo set sizes = estimand sizes,
  bins consistent with the windows). Draw counts, interval quantiles (0.025/0.975), the caution threshold (0.10), the
  in-time fake week and the post bins are parsed from the file's text, so no constant is repeated in code.
- `analysis/causal/panel.py` → committed `analysis/causal/data/station_week.csv` (5,412 rows, 50 stations, ISO weeks
  2018-01-01 → 2020-02-17; ANTC/PCTR on every week with missing days as 0). Read-only DuckDB connection, closed.
- `analysis/causal/monthly.py` → committed `station_month_weekday.csv` (2,388 rows, 2016-01 → 2020-02) and
  `station_codes_2letter.csv` (50 codes, names from `web/data/network.json`). All 50 workbooks parsed; every column
  sum matched the sheet's "Entries" row within 1.
- `analysis/causal/did.py`: TWFE + event study (statsmodels, CR1 by station), exact double differences, aggregate
  units, placebo / RI inference, verdict and caution rules, implied daily entries, `headline`.
- `analysis/causal/synthetic.py`: the coverage study. `tests/test_causal.py`: 25 tests (prereg 5, synthetic 7,
  placebo/randomization/cluster 6 + rules 1, monthly 6), no data/ and no network.
- `openpyxl>=3.1` added to the `ml` group (`uv.lock`: openpyxl 3.1.5 + et-xmlfile 2.0.0); the arm64 resolve still
  passes. No other package added.
- `.gitignore`: `!analysis/causal/data/`, because the global `data/` rule would hide the committed CSVs.

**Decided**
- Workbook layout is read by header text: the sheet whose name contains "weekday" and "OD" (it is "Weekday OD" to
  Jan 2018, "Avg Weekday OD" after), the header row = the row with an "Exits" cell, entry codes = the cells before
  it (19/12/16/24 are numbers in the sheet), row labels = the column holding most of those codes, totals = its
  "Entries" row. The month comes from the date in the title row (file names change from `Ridership_April2016` to
  `Ridership_201801`; the name is only a fallback). ML/BE columns (zeros) appear from May 2018 and are kept.
- `USER_AGENT` is read from `pipeline/assets/ingest.py` with `ast` rather than imported, because importing that
  module needs Dagster and the plan's commands use the `ml` group only.
- Placebo draws: for a random-draw estimand, distinct sets in first-seen order from `default_rng(20180526)`; when
  the draws asked for are ≥ the number of combinations (e.g. 5-station corridors from the 16 suburban controls,
  C(16,5) = 4,368), every combination is used. The real estimate uses all 34 controls; each placebo draw uses the
  remaining 34 − k.
- The monthly cross-check skips station-months under 100 entries a day and the transition month 2018-05.
- Weeks are dropped as incomplete when any treated, buffer or control station has < 7 days (the new and excluded
  stations don't count, since ANTC/PCTR are filled with zeros and MLPT/BERY only have test trips).

**Measured**
- Monthly vs daily cross-check (25 months, 48 stations): median |% diff| over controls + treated **0.78%**, worst
  control/treated station median 3.30% (19TH), corridor stations ≤ 3.54% (ANTC), none over 10%.
- Synthetic study, `--sims 200 --seed 0` (σ = 0.04, ρ = 0.5, 141 s):

  | scenario | estimand | truth | bias | RMSE | placebo cov. | CR1 cov. |
  |---|---|---|---|---|---|---|
  | null | legacy | 0 | −0.0010 | 0.0100 | 0.935 | 0.79 |
  | null | corridor | 0 | −0.0015 | 0.0114 | **0.84** | — |
  | moved | legacy | −0.0744 | −0.00004 | 0.0091 | 0.965 | 1.00 (mean width 0.255) |
  | moved | corridor | 0 | 0.0001 | 0.0101 | 0.91 | — |
  | new | legacy | 0 | 0.0008 | 0.0094 | 0.95 | 0.825 |
  | new | corridor | 0.1398 | 0.0016 | 0.0107 | **0.87** | — |

  RI rejection at 5% under the null: legacy 0.065, corridor **0.175**. Verdicts: new 200/200 in "new", moved
  182/200 in "moved" (9 new, 9 fewer), inconclusive 168/200 in "null" (15 new, 17 fewer).
- CR1 coverage for legacy is 0.79–0.825 when the effect is homogeneous, confirming it should not be the headline.
- pytest (default check): 125 passed (100 before + 25). ruff clean. Localdata 8 passed, Dagster validate OK, image
  rebuilt (lock changed) and its 5 smoke tests pass.

**Found / escalated (the plan's stop rule)**
- **The corridor placebo interval under-covers: 0.84 (null) and 0.87 (new), below the 0.90 bar.** Cause: before the
  opening the real corridor aggregate is only the 3 legacy stations (ANTC/PCTR are 0), and the pre-period mean
  dominates the variance of the double difference (20 pre vs 89 post weeks), while each placebo corridor sums 5
  control stations, so placebo corridors are smoother than the real one and the placebo distribution is too narrow.
  Diagnostic (300 null sims, same DGP, not the pre-registered method): 5-station placebo corridors cover 0.85,
  3-station placebo corridors cover 0.93.
- Per the plan I have **not** changed the method. The legacy, buffer and per-station placebo intervals are not
  affected (placebo sets have the same size as the treated set). The Architect decides before any real run.
- `test_randomization_null_rejection_rate_is_about_5_percent` therefore checks the legacy estimand only; its
  docstring points here.

**Not done**: no real-data treatment estimate was computed or looked at (only the panels and the monthly-vs-daily
data cross-check). No `run.py`, `/api/findings`, site band, FINDINGS.md or other docs (iteration 2). No BigQuery,
commits or deploys.

## 2026-10-10 · M4 · build loop iter 2 · Amendment 1, the single real run, /api/findings, the Findings band, FINDINGS.md
**Ruling (Architect, Amendment 1, before any real-data estimate)**
- Iteration 1's stop rule tripped for the corridor only: placebo coverage 0.84 / 0.91 / 0.87 and RI null rejection
  0.175. The cause was placebo corridors of 5 controls against a real corridor that is 3 stations before the
  opening.
- **Correction:** corridor placebo corridors are all C(34,3) = 5,984 sets of 3 controls, each summed before the
  log.
- **Rejected:**
  - pre-3/post-5 placebos (adding stations at the fake date creates a spurious jump);
  - a studentized (Ferman–Pinto style) placebo (more modelling choices than needed);
  - demoting the corridor (it is the estimand that answers new vs moved).
- Verdict and caution rules are unchanged.
- `analysis/causal/preregistration-amendment-1.json` (sha256 `96395c97…6061`) was committed and pushed by the user
  in `39b1a70` before the real run. The orchestrator confirmed the push.

**Did**
- `design.py`:
  - `load()` reads the original, then the required amendment. It checks `amends_sha256` against the original's
    sha256 and applies each `changes` entry (a dotted path; asserts the current value equals `was`, sets `now`)
    before `parse()`.
  - New fields: `Design.amendments` (file, sha256, fixed_on) and `apply_amendment()`. `Design.sha256` is still the
    original's.
  - `validate()`: the corridor placebo size is now `len(d.treated)`.
  - `did.py` is unchanged.
- `synthetic.py`: only adds `placebo_n_draws` per estimand and top-level `amendments`. DGP, noise, scenarios, seed
  handling and sim counts are unchanged.
- `tests/test_causal.py`:
  - 3 `test_amendment_1_*` tests.
  - Updated this loop's own iteration-1 tests that encoded the old corridor draw: the corridor count is now 5,984,
    and the seed-determinism and "more draws than combinations" checks moved to the buffer draws (C(16,4) = 1,820).
    The RI null-rejection test now also covers the corridor, and its docstring points to Amendment 1.
  - 4 `test_findings_doc_*` tests.
- **Gate:** `accept-causal-amended-coverage` passed (numbers below). Only after that came the single real run.
- `analysis/causal/run.py` (`--check`, `--summary`, `--plots`; `tasks.py causal`) → `api/data/findings.json` and
  `docs/img/findings-event-study-{weekly,monthly}.png`.
  - Before the real run, the code was exercised end to end on a **scrambled** copy of the inputs (random log-normal
    values in the real CSV shape), so that bugs could be fixed without seeing a real estimate.
  - The real run was then done **once**. `--check` reproduces it byte for byte. No bug fix after the run, so there
    are no before/after numbers to log.
- **API:** `api/routes/findings.py` (`GET /api/findings`) and the `TP_FINDINGS_PATH` setting. It is cached per
  process, sends `Cache-Control: public, max-age=86400`, needs no warehouse, and gives 404 `findings_not_available`.
  `"api/findings"` was added to `webexport._paths`.
  - `.gitignore`: added `!api/data/`, because the global `data/` rule hid `findings.json`.
  - `.dockerignore` already lets `api/` in, since its `data/` rule is root-only.
- **Site:** `web/js/findings.js` (pure formatters exported), the Findings band markup in `web/index.html`, the
  import in `main.js`, and styles in `charts.css`.
- **Tests:**
  - `tests/test_api_findings.py`: 10.
  - `tests/web/findings.test.mjs`: 8.
  - `tests/web/findings.spec.js`: 7, with the synthetic fixture `tests/web/fixtures/api/findings.json`.
  - `tests/local/test_causal_local.py`: 4.
  - `test_findings_served_from_image` in `tests/deploy/test_container.py`.
- **Docs:**
  - new: `docs/FINDINGS.md`;
  - updated: SKILLS_MAP (#21 ✅, #7), IMPLEMENTATION_PLAN (M4 ticked, §6 DiD line), METRICS ("Causal
    estimates"), README (Findings section, data source), DESIGN_BACKLOG (4 rows), CLOUD_RUN §5, CURRENT_STATE.

**Decided**
- **`findings.json`:**
  - `generated_at` = `data_through` = the last analysed day (2020-02-16), taken from the data so `--check` is
    byte-stable.
  - Floats are rounded to 6 decimals (−0.0 → 0.0).
  - Robustness blocks (exits, suburban controls, monthly, in-time placebo) carry legacy, corridor and buffer in the
    estimate shape. Monthly also has its pre-trend RI p and event-study series (for the monthly PNG).
  - CR1 intervals are given for unaggregated estimands only.
- `run.py` asserts the fast double difference equals statsmodels (1e-8) for every CR1 fit.
- **Site:**
  - Event-study panels are drawn in % (100·(e^b − 1)) rather than log points, which lay readers understand.
  - The method line takes its control count and date from the JSON.
  - The write-up link is an on-ink text link, not the planned `button-on-ink` (logged in DESIGN_BACKLOG).
- **Fixed (regression found by the full Playwright run):** the findings SVGs first reused `.chart__svg`. Two existing
  Trends tests count `.chart__svg` page-wide and saw 4 instead of 2, because the unmocked server now serves the real
  findings. The findings charts now use their own `findings-chart__svg` class with the same box CSS. The existing
  tests are unchanged.

**Measured**
- **Synthetic study after Amendment 1** (`--sims 200 --seed 0`, unchanged DGP; 133 s with CR1), with iteration 1's
  numbers alongside:

  | scenario | estimand | placebo cov. iter 1 | placebo cov. amended | CR1 cov. | placebo width (amended) |
  |---|---|---|---|---|---|
  | null | legacy | 0.935 | 0.935 | 0.79 | 0.039 |
  | null | corridor | **0.84** | **0.925** | — | 0.041 |
  | moved | legacy | 0.965 | 0.965 | 1.00 | 0.039 |
  | moved | corridor | 0.91 | 0.96 | — | 0.041 |
  | new | legacy | 0.95 | 0.95 | 0.825 | 0.038 |
  | new | corridor | **0.87** | **0.935** | — | 0.041 |

  - RI rejection at 5% under the null: legacy 0.065 → 0.065, corridor **0.175 → 0.075**. Corridor
    `placebo_n_draws` = 5,984.
  - Verdicts: new 200/200 in "new"; moved 192/200 in "moved" (was 182); inconclusive 183/200 in "null".
  - Bias ≤ 0.002, RMSE ≈ 0.01.
  - **Gate passed:** min placebo coverage 0.925 ≥ 0.90; null RI ≤ 0.10 for both estimands.
- **Real data (single run, final):**
  - **Verdict: new. Caution: false.**
  - Corridor b = 0.0415, **+4.2% [+1.6%, +7.1%]** (95% placebo), RI p 0.0007; about 505 [199, 824] extra entries
    a day.
  - Legacy b = −0.2730, **−23.9% [−25.8%, −21.8%]**, RI p 0.0002; CR1 [−39.6%, −4.1%].
  - Buffer +0.5% [−1.7%, +3.0%].
  - Per station: PITT −40.1%, NCON −23.1%, CONC −4.3% [−7.4%, −0.0%].
  - Weekly pre-trend RI p: legacy 0.43, corridor 0.66. Legacy CR1 Wald p = 0.027.
  - **Robustness** (corridor / legacy):

    | analysis | corridor | legacy |
    |---|---|---|
    | exits | +3.8% [+0.7, +7.2] | −24.1% |
    | suburban controls | +3.8% [+1.1, +7.3] | −24.2% |
    | monthly | +6.4% [+2.2, +12.3] | −22.5% |
    | in-time placebo | +1.2% [−1.0, +2.8] | +1.4% [−0.6, +3.1] |

  - Monthly pre-trend RI p: legacy 0.069, corridor 0.11. The monthly event study shows the corridor about 6.5% below
    the reference in early 2016, i.e. it was drifting up against the controls before the opening.
  - The corridor's weekly gain is largest in the first half-year and is +1–3% from week 36. Only 3 of the 23 post
    bins exclude 0.
- **Reported, not acted on:** none of these is in the pre-registered caution rule, so the flag stays off. FINDINGS
  §Interpretation and §Limitations say plainly that part of the +4.2% may be trend. No trend-adjusted estimate was
  computed (not pre-registered).
- **The OD data records eBART riders through to their destination:** 1.09% of ANTC/PCTR entries
  (22,338 / 2,049,800, 2018-05-28 → 2020-02-16) end at PITT.
- **Checks:**
  - pytest (default) **142** passed (125 + 17);
  - localdata 12 (8 + 4);
  - node 36 (28 + 8);
  - Playwright **42** (35 + 7);
  - container smoke 6 (5 + 1) on a rebuilt `transitpulse-api:loop`;
  - ruff clean; Dagster validate OK; `accept-load-local` OK;
  - `run --check` reproducible.

**Not done / for the user:**
- Commit `api/data/findings.json`, `docs/img/*.png` and the rest (no Claude co-author line).
- Rebuild and deploy the Cloud Run image, then re-export the pages (`CLOUD_RUN.md` §5), so `/api/findings` and the
  band go live.
- No BigQuery, commits, pushes or deploys were made here.

## 2026-10-10 · M4 · build loop iter 3 · Revision 1: hedged Findings copy and FINDINGS.md limitations
**Why:** the final review found that the site said more than the write-up. With the caution flag off, the Findings
band's "new" sentence read "eBART brought new riders: …", which is an unqualified causal claim. FINDINGS.md itself
tells readers to treat the result as "a small effect that may partly be trend". The "moved" sentence ("didn't grow")
likewise overstated a null. The review also found three wording slips in FINDINGS.md and four missing limitations.

**What changed (wording and docs only):**
- `web/js/findings.js`:
  - Every verdict sentence is hedged ("consistent with …"), with no "eBART brought" and no "caused".
  - New exported `VERDICTS_HEDGE_NOTE`, shown under the figures only for `new`, as a muted `findings__note`. It
    says the effect is largest in the first months and the monthly data show the line rising before the opening.
  - The note is fixed copy because the run is final. The pre-registered caution sentence is unchanged.
  - CSS reuses `--color-mute-on-ink` and the body-sm type tokens, so no new tokens and no DESIGN_BACKLOG entry.
- Tests:
  - The loop's own findings tests now use the new phrases, with test names unchanged.
  - Added a node test, "verdict sentences are hedged".
  - Added a Playwright test: the note is shown for `new` and not for `moved`, using the synthetic fixture.
  - Added `test_findings_doc_limitations_cover_the_known_threats`.
- `docs/FINDINGS.md`:
  - §Assumptions: the weekly pre-bins are "within ±2% but rising about 2 points" rather than "flat", with the CR1
    Wald p of 0.027 cited.
  - §Robustness: "every robustness row excludes 0", and the in-time placebo is described as a falsification test
    that correctly contains 0.
  - §Limitations: added return-trip contamination of the controls (SUTVA), the COVID cut-off (21 months post),
    Amendment 1's "wide side" assumption against ramp-up and parking saturation, and BART's own weekday and holiday
    definitions in the monthly source.
  - The SUTVA figure is descriptive and comes from the committed `station_week.csv`: about 500 extra entries a day
    against the 34 controls' post-period mean of about 276,000 a day (about 8,100 per station), roughly 0.2%.
- README verdict bullet: "consistent with a small net gain, not a firm finding". CURRENT_STATE §Findings band
  describes the hedged copy and the `new`-only note.

**No estimate was recomputed.** `analysis.causal.run` was run only with `--check` (reproducible). The sha256 of
`api/data/findings.json` is still `7ba1f859…6218`, and the PNGs, CSVs and both pre-registration files are
byte-identical.

**Checks:**
- pytest (default) 143 (142 + 1);
- node 37 (36 + 1);
- Playwright 43 (42 + 1);
- ruff clean.

The container image was not rebuilt. Its findings test reads only the unchanged JSON.

## 2026-10-14 · M4 + M1 · BART attribution; BART ingest on a change sensor

**Attribution.** BART's terms allow the derived `analysis/causal/data/*.csv` in the public repo with attribution.
"Data provided by BART" is now in `analysis/causal/data/README.md` (new: what each file is derived from), the intro of
`docs/FINDINGS.md`, a source caption under the Findings band and the footer's ridership line.

**BART refresh.** The monthly `monthly_ridership` schedule (6th, 06:00) is replaced by the sensor `bart_od_updates`:
every 6 hours it sends a HEAD for the last two `years` partitions and requests a `yearly_ingest` run when a file's
`Last-Modified` changes (cursor = last stamp per year, run key = year + stamp). BART posts on no fixed day (the 2025
file last changed 2026-01-03; the 2026 file is still 20 bytes), so a fixed day of the month could lag by weeks. The
new run-status sensor `models_after_ingest` runs `refresh_reference_and_models` after every successful BART or Bay
Wheels ingest (backfills skipped), so new rows reach the marts the same day instead of on the next 6th; before
this, Bay Wheels (7th) waited almost a month for its dbt rebuild. Both sensors default to RUNNING. The first
evaluation reloads 2025 once (no cursor yet). The eBART CSVs don't refresh: their 2016–2020 window is fixed by the
pre-registration.

**Checks:** `tests/test_dagster_defs.py` 4 (sensor change detection with a faked HEAD, sensor wiring; the
`monthly_ridership` cases removed); the sensor evaluated once against BART's live server.

## 2026-10-14 · M1 · VM updated; schedules on by default

The VM was on `025f80a` (Oct 9). `bootstrap.sh` brought it to `1fd224a`. Its first `bart_od_updates` tick requested
`yearly_ingest` for 2025 and 2026, as designed. The Dagster API also showed `baywheels_monthly`, `monthly_models` and
`weekly_forecast` as **STOPPED**, and the run history has no scheduled run at all: the weekly forecast of Monday
2026-10-12 never ran. The schedules had never been switched on in the UI. All three now set
`default_status=DefaultScheduleStatus.RUNNING`, like the sensors (a UI toggle still overrides it), and
`test_every_schedule_and_sensor_starts_running` keeps it that way.

## 2026-10-14 · M5 + M4 + M2 · build loop iter 1 · A/B test (B ships), post-hoc eBART trend adjustment, BI guide

**Did.**
- **M5 A/B harness.** `Settings.agent_examples_k` (`TP_AGENT_EXAMPLES_K`) → `AgentDeps.examples_k` →
  `service.get_agent`. `prompts.retrieve_examples` (BM25, k1 1.2, b 0.75, standard library, ties in pool order) over
  `api/agent/examples.json`, the eval's 63 in-scope `sql` questions exported by `python -m eval.examples --write`.
  `sql_prompt` gained a keyword-only `examples=()`; with none the prompts are byte-identical (fingerprint
  `85a1cbe8…da56` unchanged). The graph reads `exclude_examples` from its input state, which `eval.run_eval.evaluate`
  sets to the scored question's id (leave-one-out). `run_eval --arm A|B` (k 0 / 5); summaries add `arm`,
  `examples_k`, `eval_sha256`, `ollama_version`, `per_question`, `sql_prompt_chars_mean`; files are named
  `<llm>-<arm>-<ts>.json`. New `eval/ab.py` (exact McNemar, paired bootstrap, power, `--check`) and
  `tests/test_ab.py` (the plan's 8 tests).
- **Order of the A/B, with times (UTC, 2026-10-15; PDT is 2026-10-14, −7 h):**
  1. 01:26 — `docs/AB_TEST.md` Question and pre-registered Design written (copied from the plan).
  2. 01:26:42–01:30:24 — arm A run (`summary-ollama-A-20261015T013021Z.json`).
  3. 01:30:49 — `python -m eval.ab --power --json` on arm A; the Power section written right after.
  4. 01:31:20–01:33:57 — arm B run (`summary-ollama-B-20261015T013355Z.json`).
  5. Then Results and Decision, and `agent_examples_k` set to 5.
  The two arms ran one at a time, never in parallel (memory: the machine had 0.5–5.5 GB free during the runs).
- **M4 post-hoc trend adjustment.** `analysis/causal/trend_adjusted.py` (`--write`, `--check`, `--summary`) →
  `analysis/causal/trend_adjusted.json`. It reuses `design.load`, `did.monthly_panel`, `did.weekly_panel`, `did.gap`,
  `did.aggregate_unit`, `did.draw_sets` and `run.render`. The trend fit is written as one weight vector, so every
  placebo draw costs one matrix product (the whole run takes under 1 s). FINDINGS.md gets "Post-hoc:
  trend-adjusted estimate (not pre-registered)"; four new `trend_adjusted` tests in `tests/test_causal.py`.
- **M2 BI guide.** `bi/README.md`: the check week, Looker Studio (connector, data sources, charts that mirror the
  tiles, owner's credentials, sharing, the embed URL and the `tp-looker-url` meta), Power BI (connector, model, four
  DAX measures, the check, `.pbix`/PDF/screenshots). `tests/local/test_bi_week.py` (localdata) recomputes the week;
  `tests/test_docs_deliverables.py::test_bi_guide_present` (default suite) checks the guide's content.

**Decided.**
- **Ship arm B** (`agent_examples_k` default 5) by the pre-registered rule: McNemar p = 0.00408 < 0.05, acc_B 0.5000 >
  acc_A 0.2727, B's refusal accuracy 1.0 ≥ 0.9. `eval.ab --check` fails if the default and the rule ever disagree.
- **Leave-one-out through graph state, not by matching question text.** Excluding by text would also drop a
  visitor's question that happens to equal a pool question; production must use the whole pool.
- **Power = P(B ahead and p < 0.05)**, i.e. the rule's first two conditions, conditioning on arm A's observed 18
  right / 48 wrong. Rejected: simulating A too (adds noise for no decision value).
- **Doc check parses labelled numbers in the Results section** (`Execution accuracy | k/n = x | k/n = x`, `b = `,
  `c = `, `McNemar exact p = `, `acc_B - acc_A = `, `bootstrap CI [..]`) and compares them as formatted strings.
  Rejected: substring search for each number (a wrong "0.125" would pass a check for "0.1").
- **Weekly secondary adjustment = weekly b − β × (mean post-week date − mean pre-week date in months).** The weekly
  and monthly gaps have different levels (7-day sums vs average weekdays), so only the monthly slope carries over.
- **The FINDINGS post-hoc section is a `###` subsection at the end of §Interpretation**, not a new `##` section: the
  existing `test_findings_doc_has_the_sections_in_order` pins the `##` list, and existing tests are not edited. It
  still sits directly before Limitations, as the plan asks.
- **Check week 2025-W39** (22–28 Sep): 7 days, 5 service weekdays, no holiday, and a clear busiest station
  (Embarcadero 5 of 7 days; W12 and W38 split 4/3).
- `make eval` does not run both arms in one call; one arm per call keeps memory low. Recorded on the M5 "Done when"
  line.

**Found.**
- Arm A reproduced the earlier runs exactly on Ollama 0.40.4: all 76 per-question outcomes equal those of each of
  the 8 local llama3.1:8b runs of Oct 9–10. Temperature 0 is deterministic here.
- B's gains are in trend (+5), OD (+4), KPI (+4) and bikes (+2) questions. Station questions are flat (s01, s03,
  s05, s06 fixed; s02, s04, s13, s14 broken); t07 is the fifth question B broke. For 8 of the 20 questions B fixed, the top retrieved example is a
  near-twin with a word or two changed (k05/k06, s05/s06, t04/t05/t06, b03/b02, o05/o02), the stated leave-one-out
  limitation.
- B is faster, not slower: p50 2.46 → 1.74 s, p95 6.71 → 4.71 s, with errors 11 → 7. Its SQL prompt is 34% longer
  (3,423 → 4,595 characters).
- Ollama runs llama3.1:8b with a 4,096-token context; B's prompts (about 1,200 tokens) fit.
- The trend adjustment reproduces the pre-registered unadjusted numbers exactly (weekly corridor +4.235082%,
  monthly +6.39275%), so the units are built as the pre-registered analysis builds them.
- The monthly corridor pre-bins rise mostly in 2016 (−6.8% → −0.8% by months −19…−17, then between −2.6% and 0), so a
  straight line over all 28 pre months may over-correct. Stated in FINDINGS.

**Fixed.** Nothing broken was found. Three SKILLS_MAP line links into `graph.py` and `run_eval.py` moved with this
change and were updated (build_graph 136 → 138, run 143 → 145, run_agent 288 → 292, evaluate 52 → 70).

**Measured.**
- A/B: arm A 18/66 = 0.2727, arm B 33/66 = 0.5000; b = 5, c = 20; McNemar p = 0.00408; acc_B − acc_A = +0.2273,
  95% paired bootstrap CI [+0.0909, +0.3636]; refusal 10/10 both.
- Power (n = 66, p_A = 0.2727, g = 0.05, 10,000 sims, seed 0): 0.114 / 0.532 / 0.856 / 0.970 at +5/+10/+15/+20
  points; minimum detectable improvement **+14 points** (0.804; +13 gives 0.747). The Architect's hand estimate was
  about +15.
- Post-hoc trend-adjusted (not pre-registered): corridor monthly −0.1% [−4.3%, +3.2%] (RI p 0.95), weekly +1.0%
  [−2.4%, +4.2%] (RI p 0.57); legacy monthly −26.5% [−29.1%, −24.0%], weekly −25.9% [−28.2%, −23.8%]; β = +0.0025
  (corridor) and +0.0021 (legacy) log points a month. Both corridor intervals contain 0, so FINDINGS says the +4.2%
  is not distinguishable from trend. The pre-registered verdict ("new") is unchanged; `findings.json`, the PNGs and
  both pre-registration files are byte-identical (hash checks pass).
- Check week 2025-W39: total entries 1,128,303; service-weekday recovery 0.4385; service-weekday peak-hour share
  0.1169; Embarcadero busiest on 5 of 7 days at a mean share of 0.0912.
- Tests: pytest default 159 passed (this iteration adds 13: 8 A/B, 4 trend-adjusted, 1 BI guide); localdata 13
  (+ 1, the BI week); node 37; ruff clean.
- Read-only GETs on 2026-10-14: the live pages, `/api/health` (`{"ok":true}`) and `/api/findings` all answer 200, so
  CURRENT_STATE's lines saying they weren't live were removed.

**Not done / for the owner.**
- The BI dashboards themselves (Looker Studio, Power BI) need the owner's Google account and Power BI Desktop; the
  guide is ready.
- The live agent runs Gemini, which this A/B didn't test; the optional Gemini A/B goes in `docs/OWNER_STEPS.md`
  (iteration 3).
- Docker checks were not run this iteration (Docker Desktop was stopped to free memory); nothing here changes the
  image except `api/agent/examples.json` and the new default, which ships inside `api/`.

## 2026-10-14 · F5–F7 + M7 · build loop iter 2 · website gaps, style guide, axe + Lighthouse, README images, `make up`, owner steps

This build iteration did the plan's iteration 2 (website, polish, README images, design review) and, with every
check still green, its iteration 3 (`make up`, `docs/OWNER_STEPS.md`).

**Did.**
- **Ask history and Copy SQL** (`web/js/ask.js`). Answers and refusals (never errors) go to `sessionStorage`
  (`tp-ask-history`): question, text, columns, the first 20 rows, SQL; at most 5, newest first. After a reload they
  render under the Ask card ("Earlier answers") through `renderAnswer`, the same escaping path as a live answer.
  `readHistory` reshapes every stored entry and drops anything malformed; storage errors read as no history. "Show
  SQL" gained a Copy icon button (`navigator.clipboard.writeText`); the toast (`aria-live`) says "Copied". The toast
  moved from `main.js` to `web/js/util/toast.js`, so `ask.js` can use it without importing `main.js` (which would
  break `ask.js`'s node tests).
- **Map → forecast** (`map.js`, `forecast.js`). A click or tap on a station (pointerup, never a hover) dispatches
  `tp:station` on `document`; the forecast explorer picks the station with its existing `choose()`. No scrolling. The
  station tooltip ends with "See its forecast" → `#forecast`.
- **Busiest station.** The map's live summary appends "Busiest station in the latest data: <name>." from the
  `busiest_station` KPI tile. `trends.js` now has `getKpis()`, one shared `/api/kpis` request per page (Retry
  refetches), which the map and the footer reuse.
- **Dashboard slot.** `<meta name="tp-looker-url" content="">`; with an `https:` URL, `initDashboard` renders a
  "Dashboard" chart card under the bikes card: a lazy 4:3 `iframe` on cards ≥ 768 px (container query), an "Open
  dashboard" pill below that. Empty or non-https → nothing.
- **Open Graph.** `og:*` (absolute URLs on braedynthompson.com) and `twitter:card`; `web/img/og.png`, 1200×630.
- **Images.** `tests/web/screenshots.mjs` (`tasks.py screenshots`) with a shared `tests/web/server.mjs` that starts
  uvicorn on a free port (local DuckDB when present) and kills the process tree on Windows. Wednesday 8:00 AM PT:
  `web/img/og.png` (map stage forced to 1200×630, controls hidden), `docs/img/screenshot-phone.png` (390 px, the
  map band), `docs/img/screenshot-desktop.png` (1440 px, top of the page through the map).
- **Style guide** (`web/styleguide.html`, `web/js/styleguide.js`): text tokens on their allowed surfaces, type
  samples, token tables rendered from `tokens.css`'s `:root` rules (media overrides included), the icon sprite
  copied from `index.html`, and every component block. Linked from the footer, `noindex`.
- **axe + Lighthouse.** `@axe-core/playwright`, `lighthouse` 12.8 (Node ≥ 18.16, so it runs on Node 20 and CI) and
  `chrome-launcher` (declared, not relied on transitively) as devDependencies. `tests/web/a11y.spec.js`;
  `tests/web/lighthouse.mjs` (`tasks.py lighthouse`, `make lighthouse`).
- **Design review** (below) and `docs/DESIGN_BACKLOG.md` rewritten as a numbered "v1.1 list" (the 10 open rows + 9
  new gaps).
- **README:** a Mermaid architecture diagram, both screenshots, a Lighthouse row, a GCP cost row, `make up`, the
  coastline source corrected to the US Census (it said Natural Earth), "Left to do" rewritten (M6 + the two v1 cuts;
  "Needs you" points at OWNER_STEPS).
- **`make up`.** `docker-compose.yml`: `ollama` (`ollama/ollama:0.40.4`, named volume or `TP_OLLAMA_DATA`,
  healthcheck), one-shot `ollama-pull`, `api` (the Dockerfile, `${TP_PORT:-8000}:8080`, agent on, `./data` read-only,
  Python healthcheck, waits for the pull). `tasks.py up` + a Makefile `up` target; `tasks.py api` and `up` share
  `_use_local_warehouse()`. `tests/test_compose.py` (default suite) and `tests/compose/test_compose_up.py` (marker
  `docker`, project `tp-compose-smoke`, port 8814, always `down`).
- **`docs/OWNER_STEPS.md`:** 14 ordered steps (0–13) with commands, what to expect and how to verify, including the
  10 phone questions with expected answers computed from the local DuckDB. `test_owner_steps_complete_and_ordered`.
- **Other docs:** IMPLEMENTATION_PLAN markers (F1 style guide, F3 busiest, F4 heatmap cut, F5 map click, F6 history
  + copy, F7 all but the real-device check, M6 deferral note, M7 README and `make up`, §6), CURRENT_STATE, SKILLS_MAP
  (7 line links that had drifted, at HEAD too, re-pointed at their symbols; 3 new rows; `make up` under #18).

**Decided.**
- **gzip in the API** (`GZipMiddleware`, ≥ 1 KB). Lighthouse's first run scored performance 88: observed FCP = LCP =
  369 ms came after every JS module and JSON request, so Lantern charged ~400 KB of uncompressed text to the
  simulated FCP/LCP (2.0 s / 3.8 s). With gzip: 1.5 s / 2.3 s, performance 98. Cloud Run sends what the app sends, so
  live JSON gets smaller too. Starlette 1.7 skips `text/event-stream`, so Ask still streams event by event; a new
  test in `tests/test_ask_api.py` pins that. Rejected: preloading Inter 400 (the LCP paragraph's weight): no clear
  gain over 3 runs, and DESIGN.md §3 says only 700 is preloaded.
- **Lighthouse stays out of CI**: shared-runner performance varies by several points. It is a local gate
  (`--runs 3 --assert`, median run).
- **Copy SQL is an icon button with the toast**, as DESIGN.md §7 specifies (a "Copy" icon button; the toast "used
  only for 'Copied'"), placed under the SQL block (backlog #15).
- **History renders the stored list minus the newest while asking** (that one is on screen), all of it after a
  reload; nothing in static mode.
- **The dashboard picks iframe vs pill with a container query**, not JS, so it follows the card, as DESIGN.md §4 asks.
- **`getKpis()` memoises the request, not the result,** and Retry passes `fresh`: the existing "Retry reloads" test
  still sees exactly 2 `/api/kpis` calls although the map now reads the same response.
- **Tooltips are rewritten only when their HTML changes.** They were rewritten every frame (≤ 250 ms), which would
  swallow a click on the new link (the element under the pointer replaced between pointerdown and click).
- **README screenshots at DPR 1** so the widths are exactly 390 and 1440 (the test pins them).
- **`make up` smoke uses its own compose project** (`tp-compose-smoke`) so it never touches a running `make up`.
- **The manual `tasks.py up` used `qwen2.5-coder:0.5b`, not llama3.1:8b:** 2.5 GB of RAM was free (the orchestrator
  asked for a small model). The model volume was removed afterwards (`down -v`).
- **The phone questions' expected answers** are the gold SQL results (eval k02, s09, o04) or the obvious SQL for the
  chips; question 4 (bikes vs trains "last month") and 7 (the forecast) are worded for BigQuery's data, which
  differs from the local file there.

**Found (design review against DESIGN.md).**
- Fixed in code: the answer panel's question echo was `body` grey at 400 (spec: body-md-strong) and its heading
  `display-md` (spec: `display-lg`); numeric table headers were left-aligned over right-aligned numbers; the footer
  lacked "Data through <date>" and the write-up links (§7 Footer).
- Recorded for v1.1 (DESIGN_BACKLOG 11–19): the placeholder token (`mute` fails AA off white; the code uses `body`),
  the phone answer sheet (built inline), the progress-step list (no chart step), earlier answers, Copy SQL placement,
  the station tooltip wording + link, the dashboard card, the segmented thumb (a fade, not a slide), the stat-tile
  label wording.
- axe found **0** contrast violations on the loaded page at 390 and 1440 px and on the style guide, so no token
  changed and DESIGN.md is untouched. A planted `mute`-on-`canvas-soft` paragraph was caught, so the check works.
- The Mermaid diagram was rendered with Mermaid 11 in Chromium to check its syntax.
- The pinned Ollama image is **9.37 GB** on disk (CUDA/ROCm libraries). The disk went from 50 to 36 GB free.

**Fixed.** The style guide first overflowed at 320 px (a `pre` widened its grid column; a nav button didn't fit),
the OG shot came out 631 px tall (a fractional element box; now a whole-pixel clip), and "DESIGN.md" in a CSS
comment was read as a class by the components test (comments are stripped first).

**Measured.**
- Lighthouse (mobile, local server, 3 runs): performance 98 / 97 / 100 (median 98), accessibility 100, best practices
  100, LCP 2.2–2.3 s, CLS 0. Before gzip: 88, LCP 3.7 s.
- Images: og 104 KB, phone 68 KB, desktop 203 KB.
- `make up` by hand: pull OK, API healthy, `/api/kpis` 200 from the read-only DuckDB on the Windows bind mount,
  "Which station had the most entries on 2025-12-31?" → `thinking, sql, rows, answer` in 8.3 s on CPU. The 0.5B
  model summed all of 2025 while saying "on 2025-12-31": the wiring works, that model's answers don't.
- Tests: pytest default 167 (+8: gzip/SSE, 3 docs deliverables, 4 compose); Playwright 57 (+14); node 37; localdata
  13; Docker 6 (`tests/deploy`) + 3 (`tests/compose`); load-local OK; ruff clean.
- Playwright: one full run (of 8) failed "no horizontal scroll and a correctly sized map at 768px"; it passed alone,
  in 96 targeted repeats and in the other 7 full runs. The error text wasn't kept. No change here touches the map's
  sizing at 768 px, so it is recorded as an unexplained one-off.

**Not done / for the owner.** Everything is in `docs/OWNER_STEPS.md`: commit and push (deploys Cloud Run), re-export
the pages (new web code), the `deploy.yml` decision, the live agent (quota, Gemini key, optional Gemini A/B, Terraform),
Looker Studio (then the meta URL) and Power BI, the CI identity decisions, the real-device check, an optional Locust
run against Cloud Run, the month-end bill, and whether to start M6. `npm install` reported 27 advisories (19
moderate, 8 high) in Lighthouse's dependency tree; dev-only, never in the image, not fixed with `--force`.

## 2026-10-16 · owner steps · site published; Terraform stays manual; quota measured
**Did**
- Committed the loop's work in six commits (`62be844..cdea28f`) and pushed; CI and the deploy passed, the live API
  serves gzip. Re-exported the pages (portfolio `a321d7e`); Pages deployed, `og.png`, `styleguide.html` and CORS
  check out. Removed the empty `tp-compose-smoke_ollama` volume.
- The owner chose to keep Terraform manual. `infra/README.md` now lists when to run `terraform apply`.

**Measured.** BigQuery billed per principal per day (`JOBS_BY_PROJECT`): `sa-pipeline` 49.8 GiB on 2026-10-09 (the
full backfill) and 16.9 GiB on 2026-10-15 (an ingest and rebuild). The runbook's 20 GiB per-user quota would have
failed pipeline runs, so it is now 30 GiB (under the free tier's ≈ 33 GiB/day), raised for the day of a full backfill.
The quota is not set yet: it is the owner's console step.

## 2026-10-16 · site · front-end fixes after the owner's report; Ask on a working Gemini model
**Fixed**
- **List view had no way back.** `.map-list` (absolute, later in the DOM) painted over `.map-top`, so the Map/List
  toggle could not be clicked. `.map-top` now has `z-index: 1`; the zoom buttons hide in list view (nothing to zoom).
- **Now button unreadable on desktop.** `.btn--subtle:hover:not(:disabled)` outranks `.map-now[aria-pressed]`, so a
  hovered, pressed Now turned light grey under white text. The pressed style now covers hover. The replay speeds use
  the same ink pill, and only in replay: Now and a speed are never highlighted together.
- **A straight line across the top of the phone map.** The land polygons were clipped at y = -150, which a square phone
  view with the controls inset reaches; the clipped edge was stroked like a coastline. Clip widened; `land.json`
  12 → 19 KB; network and timetable unchanged.
- **Ask: "The analyst hit a problem (GoogleModelNotFoundError)".** `gemini-2.5-flash` is closed to new API keys.
  Tried with the owner's key (eval arm B): `gemini-3.8-flash` 3/3 at 32 s a question; `gemini-3.5-flash` hit the
  free tier's **20 requests a day** after 4 questions; `gemini-3.5-flash-lite` 3/3 on the first sample at 6 s, then
  5/13 in-scope with 6 in-scope refusals on a 16-question sample (all 3 refusal questions right). Production now runs
  `gemini-3.5-flash-lite` (the only one that fits a public site's free-tier traffic); a quota error (`GoogleRateLimitError`)
  now reads "The analyst is out of free questions for now" instead of a crash.

**Checked, not a bug.** The map's 54-56 trains at 5 PM on a weekday match BART's published GTFS: 55 trips are in
motion then (Yellow 20 = two 10-minute patterns, Antioch and Pittsburg/Bay Point; no two same-line trips within a
minute at any station). The time slider drags and clicks in Playwright Chromium, in the owner's Chrome and in Edge.

**Found.** The live map's timetable comes from the static export and ends **Jan 10, 2027**; the VM's monthly GTFS
refresh never reaches the site. Owner step 3 now says to rebuild `web/data` and re-export before then. The GCP free
trial ends about Jan 6, 2027 (owner step 12) and can't change quotas, so the 30 GiB BigQuery quota waits for the
upgrade.

## 2026-10-16 · site · SQL block wraps; the time slider's track is visible; Ask live
- **Show SQL ran off the page.** The agent's SQL is often one long line, and `pre` grew its card past the screen.
  `.sql-block` now wraps (`pre-wrap`, `overflow-wrap: anywhere`); a Playwright test opens a long query at 390 px.
- **The time slider looked static.** Its 4 px track was `canvas-soft` (#efefef) on the white control bar, about
  1.2:1, so only the thumb showed and nothing said it could move (probably the owner's "can't change the time on the
  PC"). Track is now `mute` (#767676, 4.5:1).
- **Ask is live** on `gemini-3.5-flash-lite` (owner applied Terraform): "average daily BART ridership in 2019" →
  324,958 in 3.3 s; "What's the weather tomorrow?" → refusal with suggestions in 0.8 s.

## 2026-10-16 · Ask · a side panel with a train mascot; suggestions that always work; fewer refusals
**Why.** The owner tapped the chip "Bikes vs. trains last month" and was refused. Two causes: every question first went
to the model's router, and `gemini-3.5-flash-lite` called that one off-topic; and "last month" (Sep 2026) is after
BART's data ends (Dec 2025). A second chip, "Busiest hour on a weekday?", could never work: the only hourly table,
`fct_trips_hourly`, isn't on the agent's allowlist.

**Did**
- `api/agent/suggested.py`: the six suggestions, each with a reviewed BigQuery query (dry runs 0-3.2 MB). A
  suggestion skips the router and the SQL writer and still goes through the guardrails, dry run and byte budget; the
  model only writes the sentence. "Last 12 months" windows, not fixed years, where a year would go stale. Chips now:
  grew most since 2022, most entries in 2025, how close to 2019, bikes vs. trains in the latest month, highest
  peak-hour share, Embarcadero's forecast. `tests/local/test_suggested.py` checks each against the local warehouse
  (the answers in owner step 6); a test checks every chip in `index.html` and every refusal suggestion is reviewed.
- Router: plain data questions (data words, no off-topic or forecast words) skip the model's router; forecast words
  still ask it ("how accurate is the forecast?" is SQL, not a station's forecast: the first version sent those to the
  forecast node and the eval caught it). The router prompt now says to refuse only clear off-topic requests.
  Reviewed queries are off in the eval (`AgentDeps.suggested`), so it still measures the model. The router shortcut
  is on in the eval too (it is production behaviour), so runs from now on differ from the committed A/B summaries,
  which were measured with every question routed by the model.
- Ask moved out of the hero into a panel: a launcher in the bottom-right corner (ink pill, the mascot, "Ask
  TransitPulse"; mascot only on phones) opens a 440 px side panel under the nav, full screen under 768 px. The nav's
  "Ask a question" and a new hero button open it too; ✕ or Esc closes it and focus returns. The mascot is an inline
  SVG train front in its own colours (no BART logo). Answers use `display-md` in the narrower panel; the input clears
  after sending. Tests: launcher/Esc/focus/nav, desktop width and phone full screen at 320 px.

## 2026-10-17 · site · the redesign: five rounds, watched live in the owner's Chrome
**Why.** The owner asked for "a fun user experience that is laid out nicely" with "lots of changes", following along
at http://localhost:8000. The design doc was frozen at v1.0.1 ("the only colour is data"); the owner's request
reopens it, so v1.1 is an additive layer (`fx.css`, `fx.js`) and a dark palette, with tokens and components intact.

**Rounds** (each committed after the 60 Playwright + 37 node tests passed):
1. Pulse stripe under the nav; the hero's live strip (trains moving / % of 2019 / data date); count-ups on tiles and
   Findings figures; sections slide in; nav scroll-spy; the mascot bobs and says hello once per session.
2. The map legend as a line filter; 12-month sparklines in two tiles; a "Surprise me" forecast chip.
3. Station cards in the map tooltip (entries, % of 2019, 28-day weekday average, peak hour); a line-colour dot before
   each section's eyebrow, a line-colour border on the Findings band and a stripe under the headline's last word;
   dark mode with a sun/moon toggle (system preference by default, saved choice, applied before paint).
4. A departure board in the hero's empty second column: the six soonest arrivals anywhere, published by the map
   every 10 s (`tp:arrivals`); the footer greets with the mascot.
5. A crosshair readout on both line charts; busiest/quietest badges on the forecast card; `/` opens Ask; the footer
   mascot hops when poked.

**Caught by the tests.** The first reveal faded opacity in, and axe read the legend's text mid-fade as 1.4:1 contrast;
the reveal is now a slide only. Sparklines first added 35 px to the tiles after load and broke the skeleton
height check; they now sit absolutely in the tile's corner. The local server was killed twice for low memory
(Docker's other project plus Chrome); it was restarted when the owner asked to continue.

**Not done.** The style guide doesn't yet show the v1.1 pieces (board, badge, mascot, legend toggle, readout); the
components test only requires `components.css` blocks, which are unchanged. Dark mode isn't covered by the axe test
(light only). Nothing is published: the owner is reviewing locally.

## 2026-10-17 · analysis · BART station closures: what the ridership says
**Why.** The owner: "I know there is a vote to remove some bart stations, i want this project to add a part that
relates … use the existing technology to add a segment that talks about whether or not they should be removed."
The vote is the Connect Bay Area measure (SB 63) on the November 3, 2026 ballot; if it fails, BART's Alternative
Service Plan (adopted 8–1 on February 26, 2026) allows up to 15 station closures from July 2027. The board hasn't
voted on which stations; the 15 are the ones the press reported from BART staff's February presentation.

**Did**
- dbt: a seed `bart_closure_candidates` (15 stations, group 1 = the first 10, group 2 = the next 5, and the line-end
  segment), and three marts on the core facts: `mart_station_closures` (one row per station: 2025 service-weekday
  trips = entries + exits, rank from the fewest, recovery vs 2019, change vs 2024, nearest station still open if all
  15 close), `mart_closure_destinations` (top 3 destinations of each listed station) and `mart_closure_scenarios`
  (trips touching the first 10 / all 15). Portable SQL (haversine with `asin`/`power`/`acos(-1)`), 11 schema tests.
  Dagster picks them up through dagster-dbt with no code change.
- API: `GET /api/closures`, cached an hour, in the static export. The three rules and the verdict mapping are
  constants in `api/routes/data.py`; the response carries their text, so the page never states a threshold.
- Site: a "Station closures" band after Findings with a "Closures" nav link: static context, not-final and
  no-position notes, "What the data can't see" and 10 sources; from the API, three summary tiles, the rules card and
  15 station cards with a verdict pill ("Case to keep: strong / mixed / weak": ink / outlined / soft, never
  green/red) and each rule as Met / Not met. DESIGN v1.1.2.
- Write-up `docs/STATION_CLOSURES.md`; tests: 7 API unit, 4 localdata (incl. an independent Python recomputation of
  the marts and the write-up's table against the API), 8 node, 9 Playwright (incl. axe in light and dark), 2 docs.

**Decided**
- The verdict is a "case to keep" from three rules fixed in the build plan before the section was built and not
  adjusted afterwards (rough numbers had been seen while checking feasibility, so it isn't called a blind
  pre-registration): **Riders** (not among the 10 least used, BART staff's own cut), **Recovery** (whole-percent
  recovery vs 2019 at or above BART's), **Distance** (nearest open station ≥ 3.0 mi). 3 met = strong, 2 = mixed,
  0–1 = weak. The rules compare the rounded numbers the page shows.
- Neutral on the measure: the copy says TransitPulse doesn't take a position on it, the verdicts weigh ridership
  only, and the list isn't final. The Ask agent is unchanged (its prompt and eval are frozen).
- Top destinations leave out trips back to the same station; their share is of all trips starting there.

**Measured** (local warehouse, 2025 service weekdays)
- Claim checks: 9 of the first 10 are in our 10 least-used stations (San Bruno is 12th; Milpitas, 5th, isn't
  listed); 12.6% of weekday trips start or end at the first 10 (press: ~12%); 24.1% at all 15. South San
  Francisco's 2025 average weekday exits are 1,409 vs BART's 1,538 for January 2026 (ratio 0.92, inside 0.75–1.25).
- Verdicts: strong 2 (Antioch, Pittsburg/Bay Point), mixed 4 (Pittsburg Center, Orinda, San Bruno,
  Dublin/Pleasanton), weak 9. BART's systemwide recovery: 43%.
- Close calls (named in the write-up): San Bruno (43.05% rounds to BART's 43%, Recovery met), South Hayward (rank
  10; 2.94 mi), Oakland Airport (2.88 mi), South San Francisco (3.19 mi, Distance met).
- `/api/closures`: 11,059 bytes, ~140 ms cold, ~3 ms warm (cache). `dbt build --select bart_closure_candidates+`:
  15 nodes in 0.75 s on DuckDB.

**Not done.** The marts haven't run on BigQuery (no access from the loop): the live band says "This data hasn't been
loaded yet." until the VM pulls this code and runs a dbt build (owner step 4). No map overlay, no per-station cost,
equity or travel-time data, and no summary of the arguments for and against the measure. The copy needs a
post-election edit after November 3, 2026.

## 2026-10-17 · analysis · BART station closures: the SFO assumption (revision 2)
**Why.** Final review found that the closures section counts San Francisco International Airport (SFO) as open
without saying so. SFO isn't on the reported list, so under the rule "the nearest open station is any station not in
the seed" it is the nearest open station for San Bruno (2.0 mi) and Millbrae (1.1 mi), and both fail Distance
because of it. The copy also said closing group 2 would end or lose BART service on the three line-end segments,
which contradicts SFO staying open on the Peninsula segment. And the write-up said its whole results table was
checked against the warehouse, when the test only checked the Verdict column.

**Did** (copy and tests only; no change to the rules, marts, API, verdicts or fixture)
- Page: a `[data-closures-sfo]` note in "What the data can't see": SFO isn't on the list, the sources don't say how
  it would be served, the page counts it as still open, so it is the nearest open station for San Bruno and Millbrae,
  and if it lost service both would meet Distance and their case to keep would be stronger (names only, no numbers).
  The group-2 intro now says closing those stations "would close all the listed stations on 3 line-end segments".
- Write-up: the line-ends sentence reworded the same way; a new "The SFO assumption" section after "Close calls"; a
  "What the data can't see" bullet pointing to it. CURRENT_STATE §3 and the §7 limitation updated.
- Tests (localdata, appended to `tests/local/test_closures_local.py`): every column of the write-up's results table
  against the API (group, weekday trips, rank, % of 2019, change vs 2024, nearest open station and miles, rules
  met), and the SFO section recomputed in Python from `dim_station` and the seed with SFO excluded too, re-applying
  `closure_criteria`.

**Decided.** Disclose, don't apply. Changing the nearest-open rule after seeing which verdicts it moves would be
tuning, so the table keeps the plan's rule and the alternative is reported beside it.

**Measured** (local warehouse). Without SFO, the nearest open station for both is Daly City: 5.5 mi from San Bruno
(Riders, Recovery, Distance → strong instead of mixed) and 8.6 mi from Millbrae (Riders, Distance → mixed instead of
weak). No other listed station has SFO as its nearest open station. Alternative counts: strong 3, mixed 4, weak 8
(as applied: strong 2, mixed 4, weak 9). Local closures tests: 6 pass.

## 2026-10-17 · analysis · BART station closures: a fourth rule and the cost of closing (owner's request)
**Why.** The owner asked for the closures band to lean "slightly more in favor of keeping", citing traffic. Their
"traffic would exponentially increase" isn't supported; the evidence is that traffic rises noticeably when rail stops,
so the page cites that instead. Offered three tilts (a fourth rule with 3+ = strong; the same with only 4 = strong; a
facts card only); the owner chose the first.

**Changed.**
- A fourth rule, **Growing**: weekday trips up on the previous year, rounded half up to 0.1% (`closure_criteria`'s new
  `change_pct`, `_change_pct` in `api/routes/data.py`). Verdicts: 3–4 met = strong, 2 = mixed, 0–1 = weak. 14 of the
  15 meet it (only Oakland International Airport fell, −17.9%). Counts went from strong 2 / mixed 4 / weak 9 to
  strong 6 / mixed 7 / weak 2. The page and the write-up say the rule was added afterwards, at the owner's request,
  and the write-up gives the old counts.
- A "What closing would cost" card above the summary tiles: our numbers (24.1% of weekday trips touch the 15; 14
  growing; 8 meet Distance; Antioch 13.6 mi from Concord) and three cited findings (LA 2003 strike +47% peak highway
  delay, Anderson 2014; the 2013 BART strike nearly doubling Bay Bridge travel times on the worst day while regional
  freeways barely changed, Moylan, Foti and Skabardonis 2016; ~$73M a day in lost productivity, Bay Area Council
  Economic Institute), captioned as whole-system shutdowns that didn't measure station closures. Three sources added
  (13 in all).
- The neutral note keeps "doesn't take a position on the measure".
- Tests follow the new rule: the API fixture gains a +0.04% edge (rounds to 0.0, not met); the docs test now requires
  the "added afterwards at the owner's request" disclosure in place of "not adjusted afterwards"; the web fixture was
  regenerated from the local API; a node test covers `costSentence`.

**Not done.** BigQuery still hasn't built the closure marts (owner step 4). The SFO assumption now moves Millbrae from
mixed to strong (strong 7, mixed 6, weak 2 if SFO lost service).

## 2026-10-17 · site · sizes scale across screens (owner: "make sure everything is dynamic")
**Why.** The owner found the text "strict on the sizing". An audit (a Playwright script at 320, 390, 768, 1024,
1440, 1920 and 2560 px, flagging boxes past the viewport, content wider than its box, and text under 12px) found:
- no fixed-size text on phones;
- the map's view/zoom group running 8–35px off a 320px card;
- each legend entry overflowing its row by 8px, and "Blue line" and "Airport connector" breaking mid-name;
- the footer mascot shrinking to ~12px at 320px;
- on large screens the page frozen at a 1200px column of 16px text (1920 and 2560 looked like a strip in the
  middle).

**Changed.**
- A fluid root size: `html { font-size: clamp(1rem, 0.646rem + 0.377vw, 1.25rem) }`, which keeps the reader's own
  default as the floor.
- The spacing tokens, the container (75rem), the nav height and touch targets in rem.
- Every component length above 2px in the six stylesheets converted from px to rem (78 values, mechanically:
  px ÷ 16, outside comments and media/container conditions). Up to 1440px wide every size is identical; at 1920px the
  container is 1318px and body text 17.6px, at 2560px 1499px and 20px.
- The map top bar wraps, with the pill group kept right (`margin-left: auto`).
- Legend toggles wrap the name and description as one span, left-aligned, with the hover pill bleeding left only.
- `.mascot--lg { flex: none }`.

**Checked.** The audit shows no overflow at any of the seven widths. 69 Playwright and 46 node tests pass, including
the styleguide's 320–2560 no-scroll test, the skeleton layout-stability test and axe.

## 2026-10-17 · site · what if stations close?, dark mode throughout, the style guide catches up
**What-if picker (owner's request).** "Show the BART map without the stations that would be removed, with the same
trains but just not stopping." A card under the map closes stations from BART's list (presets for the first 10 and
all 15, or one at a time). Closed stations lose their marker, label and hit target. The trains are the same trips:
`closedStops` + `tripPosition(…, skip)` keep every open station's times and spread the time between two open stops
over the hops by their scheduled running times, so a train runs through a closed station instead of dwelling.
- Termini are never skipped: a trip still starts and ends where BART runs it, even at a closed Antioch or Millbrae.
  The board's plan would close whole segments; this shows "same trains, no stops", as asked.
- Tests: `schedule.test.mjs` checks the maths, and checks on the real timetable (every 7 minutes, 6 AM to 10 PM)
  that the train count is unchanged and none dwells at or heads for a closed stop. `whatif.test.mjs` keeps the list
  equal to the seed. A browser test checks the 50 → 35 → 36 → 50 markers. A first version flagged the map card with
  `data-whatif`, the picker's own selector; removed.

**Dark mode throughout.**
- The contrast tests now run in dark mode as well (whole page at 390 and 1440 px, and the style guide). They passed
  as soon as they were added.
- By eye, the ink surfaces inverted to white blocks on a black page: the Findings band, the footer, the hero's
  departure board and the chart readout. In dark mode they are now `canvas-soft` grey with white text.
- The style guide ignored the theme. It now applies it before paint, has the toggle and loads `fx.css`.
- A browser test checks the dark board colour.

**Style guide.** A "Newer pieces" section shows the pulse stripe, the headline highlight and live strip, the
departure board, the mascot sizes, legend toggles, the dice and what-if chips, the chart readout, forecast badges,
verdict pills, a station card, the cost card and the what-if card. A new test requires every `fx.css` block on the
page; state classes and page furniture are excepted. `.hero h1 .hl` became `.hero .hl` so the sample needs no
second `h1`.

**Docs.** `SKILLS_MAP.md` still said Bay Wheels and the VM weren't on BigQuery; both have been for a while
(`CURRENT_STATE.md`), so it is corrected. 75 Playwright and 52 node tests pass.

## 2026-10-18 · deploy · closures live, the site re-exported, Langfuse wiring for Cloud Run
- Built the closure seed and marts on BigQuery (`dbt build --select bart_closure_candidates+`, dev target): PASS=15.
  `/api/closures` on Cloud Run answers with the same 15 verdicts as local data (strong 6, mixed 7, weak 2; 12.6% and
  24.1% of weekday trips).
- Re-exported the pages to the portfolio (live mode). Checked on braedynthompson.com/transitpulse/: 15 station cards,
  "Close the first 10" leaves 40 of 50 markers, the status line has the live share, no console errors.
- Terraform: optional Langfuse tracing, bound like the Gemini key (`langfuse_public_key`, `langfuse_base_url`, secret
  `transitpulse-langfuse-secret-key`; on only with the agent and a key). Not applied: `terraform plan` shows the new
  secret plus a service-level `scaling` block (`min_instance_count` 0 → null) that `gcloud run deploy` set, which
  Terraform would clear; harmless, left for the owner's next apply.

## 2026-10-18 · docs · the VM's address on record, Langfuse removed, docs brought up to date
- **The VM.** The docs only said `<user>@<vm>`. Earlier sessions used `ssh -i ~/.ssh/oracle_seismic ubuntu@167.234.214.169` (the SeismicSoCal VM,
  `seismicsocal.duckdns.org`); it is now in `OWNER_STEPS.md` §0 and `ORACLE_VM.md`. The key has a passphrase, so
  the bootstrap can't run unattended from here; it is the owner's step 1.
- **Langfuse removed** (owner: "not necessary, it can be removed"). It was wired in since M5 but never had a project
  or keys, so nothing was ever traced. Removed `api/agent/tracing.py`, its test, the `langfuse` dependency (122 lines
  of `uv.lock`) and the Terraform wiring from earlier today (never applied). Skill 5 in `SKILLS_MAP.md` is marked
  dropped; `TRANSITPULSE_PLAN.md` keeps its original lines with a note.
- **Docs.** `OWNER_STEPS.md` steps 0–4 rewritten for today (they still described the 2026-10-14 hand-off): where
  everything runs, the VM update, CI, the re-export and the dated jobs (Nov 3 copy, the VM daemon after New Year,
  the trial upgrade, the timetable), the closures rebuild. README: status, the agent is live, the site's newer parts,
  four closure rules. The real-device checklist gains the what-if picker and dark mode.
