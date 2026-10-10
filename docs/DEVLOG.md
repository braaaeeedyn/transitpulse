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
