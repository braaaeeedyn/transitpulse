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
