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
