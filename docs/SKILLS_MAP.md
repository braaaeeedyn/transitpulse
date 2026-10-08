# TransitPulse: skills map

Where each skill from [`TRANSITPULSE_PLAN.md`](TRANSITPULSE_PLAN.md) (§2 gap table, §6 skills list) is implemented,
what it does in this project, and how it works. Links point at exact lines.

**Status:** ✅ implemented and verified · 🟡 partly implemented (what's missing is stated) · ⬜ not started.
Verified = it ran on real data or passed tests on 2026-10-07 (see [`CURRENT_STATE.md`](CURRENT_STATE.md)).

| # | Skill (gap) | Status | Main location |
|---|---|---|---|
| 1 | Cloud + Terraform | 🟡 | [`infra/terraform/`](../infra/terraform/) |
| 2 | Advanced SQL | 🟡 | [`dbt/transitpulse/models/marts/`](../dbt/transitpulse/models/marts/) |
| 3 | Load and latency testing | ⬜ | — |
| 4 | Larger datasets | 🟡 | [`pipeline/spark/clean_bart_od.py`](../pipeline/spark/clean_bart_od.py) |
| 5 | Monitoring (LLM tracing) | ⬜ | — |
| 6 | A/B testing | ⬜ | — |
| 7 | Formal statistics | ⬜ | — |
| 8 | Business metrics | ✅ | [`docs/METRICS.md`](METRICS.md), [`mart_kpis_daily.sql`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql) |
| 9 | BI dashboards | ⬜ | — |
| 10 | Warehouse + dbt + dimensional modeling | ✅ (local) / 🟡 (BigQuery) | [`dbt/transitpulse/`](../dbt/transitpulse/) |
| 11 | Orchestration | ✅ (local) / 🟡 (VM) | [`pipeline/definitions.py`](../pipeline/definitions.py) |
| 13 | CI/CD | 🟡 | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |
| 16 | Fine-tuning | ⬜ | — |
| 17 | Spark / PySpark | ✅ | [`pipeline/spark/clean_bart_od.py`](../pipeline/spark/clean_bart_od.py) |
| 18 | Reproducibility | 🟡 | [`tasks.py`](../tasks.py), [`uv.lock`](../uv.lock), [`pipeline/spark/Dockerfile`](../pipeline/spark/Dockerfile) |
| 19 | Agents and tool use | ⬜ | (API contract + UI only: [`api/routes/ask.py`](../api/routes/ask.py), [`web/js/ask.js`](../web/js/ask.js)) |
| 21 | Causal inference | ⬜ | — |
| — | Responsive, accessible web front end (added for the site) | ✅ | [`web/`](../web/) |

---

## ✅ #17 Spark / PySpark

**What it does:** turns the raw BART origin-destination CSVs (no header, gzip, ~9M rows per year) into clean,
de-duplicated, holiday-tagged Parquet partitioned by year/month. Verified on 2019 + 2025: 19,257,542 rows in 84 s.

**How it works**
| Concept | Where | How |
|---|---|---|
| Explicit schema | [`clean_bart_od.py:28`](../pipeline/spark/clean_bart_od.py#L28) | Every column is read as a string with a fixed `StructType`. No inference pass: gzip isn't splittable, so inference would be an extra full read. |
| Corrupt-record handling | [`clean_bart_od.py:46-47`](../pipeline/spark/clean_bart_od.py#L46) | `PERMISSIVE` mode routes unparseable lines into `_corrupt` instead of failing the job. |
| Validation with reasons | [`classify()` :54](../pipeline/spark/clean_bart_od.py#L54) | Trims/casts columns, then a `when` chain tags each bad row with exactly one reason, so the audit can count drops per reason. |
| De-duplication (shuffle) | [`deduplicate()` :77](../pipeline/spark/clean_bart_od.py#L77) | `row_number()` over a window partitioned by (date, hour, origin, destination), ordered by source file desc. This is the job's one wide (shuffle) stage; a corrected re-published file wins. |
| Broadcast join | [`enrich()` :103](../pipeline/spark/clean_bart_od.py#L103) | The ~11-rows-per-year holidays table is broadcast to every executor instead of shuffling 9M rows to join it. |
| Lazy evaluation + caching | [`run()` :119](../pipeline/spark/clean_bart_od.py#L119) | The parsed frame is `cache()`d once and reused for the output, the year list and the audit. Without that, each action would re-read and re-shuffle. |
| repartition vs coalesce | [`:129-132`](../pipeline/spark/clean_bart_od.py#L129) | `repartition("year","month")` groups rows by partition key (a shuffle) so each month gets one file; `coalesce` would only merge partitions without regrouping. Dynamic partition overwrite replaces only the months in this run. |
| Memory tuning | [`:161`, `:167`](../pipeline/spark/clean_bart_od.py#L161) | In local mode executors live inside the driver JVM; the 1 GB default ran out during the de-dup sort, so driver memory is a parameter (default 4 GB). |
| Runtime | [`pipeline/spark/Dockerfile`](../pipeline/spark/Dockerfile) | Linux + OpenJDK 17 + PySpark 3.5, the same as the Oracle VM and CI. |
| Tests | [`tests/spark/test_clean_bart_od.py`](../tests/spark/test_clean_bart_od.py) | Fixture with every failure type + a conflicting re-publish; asserts drop counts, trimming, latest-file-wins, holiday flag, weekday, partition layout. |

---

## ✅ #10 Warehouse + dbt + dimensional modeling (local target) · 🟡 BigQuery

**What it does:** models the cleaned trips into a star schema (dimensions + facts) and analytics marts, with
41 data tests. Runs today on DuckDB (`local` target, 52/52 pass in 7.5 s); the same models target BigQuery
(`dev` / `ci`), which hasn't run yet because the GCP project doesn't exist.

**How it works**
| Concept | Where | How |
|---|---|---|
| Layers | [`dbt_project.yml`](../dbt/transitpulse/dbt_project.yml) | `staging` (typed views) → `core` (dims/facts) → `marts`, each in its own dataset/schema. |
| Sources | [`models/sources.yml`](../dbt/transitpulse/models/sources.yml) | `raw.bart_od`, `raw.bart_stations`. On DuckDB the same source reads the Spark Parquet directly (`external_location`). |
| Star schema | [`models/core/`](../dbt/transitpulse/models/core/) | `fct_trips_hourly` (grain: date × hour × origin × destination) and `fct_station_daily`, keyed to `dim_date` and `dim_station`. |
| **SCD type 2** | [`snap_bart_stations.sql`](../dbt/transitpulse/snapshots/snap_bart_stations.sql), [`dim_station.sql:18`](../dbt/transitpulse/models/core/dim_station.sql#L18) | A dbt snapshot (check strategy on name/lat/lon) closes a station row and opens a new one when it changes. `dim_station` back-dates each first version to 1900 so older trips still join. |
| SCD2 point-in-time join | [`fct_trips_hourly.sql:33-40`](../dbt/transitpulse/models/core/fct_trips_hourly.sql#L33) | Each trip joins the station version whose `[valid_from, valid_to)` contains the trip date. All 19.26M rows matched. |
| Incremental model | [`fct_trips_hourly.sql:1-17`](../dbt/transitpulse/models/core/fct_trips_hourly.sql#L1) | Re-processes only the last 35 days plus new data. `insert_overwrite` of date partitions on BigQuery, `delete+insert` on DuckDB ([macro](../dbt/transitpulse/macros/schema_and_dates.sql)). |
| Partitioning + clustering | [`fct_trips_hourly.sql:6-7`](../dbt/transitpulse/models/core/fct_trips_hourly.sql#L6), [`ingest.py:166-167`](../pipeline/assets/ingest.py#L166) | BigQuery tables are partitioned by `trip_date` and clustered by station, so date-filtered queries scan only the days they need. |
| Cross-database macros | [`macros/schema_and_dates.sql`](../dbt/transitpulse/macros/schema_and_dates.sql) | `adapter.dispatch` gives BigQuery and DuckDB their own SQL for ISO week, weekday and the date spine. |
| Tests | `schema.yml` per layer; [`tests/generic/non_negative.sql`](../dbt/transitpulse/tests/generic/non_negative.sql), [`unique_combination.sql`](../dbt/transitpulse/tests/generic/unique_combination.sql) | `not_null`, `unique`, `relationships` (facts → dims), `accepted_values` (hour 0–23, weekday 1–7) and two custom generic tests (no negative ridership, composite-key uniqueness). |
| Cost cap | [`profiles.yml:22`](../dbt/transitpulse/profiles.yml#L22) | `maximum_bytes_billed` (2 GB dev, 500 MB CI) makes BigQuery refuse any query that would scan more. |

**Missing:** running against BigQuery (`dev`/`ci` targets), and Bay Wheels models.

---

## 🟡 #2 Advanced SQL

**What it does:** the marts answer the analyst questions (recovery, peaks, flows, daily KPIs) with window
functions, CTEs, `QUALIFY` and period-over-period comparisons.

| Technique | Where | Used for |
|---|---|---|
| CTEs | every model, e.g. [`mart_kpis_daily.sql`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql) | Building KPIs in named steps (system totals → hourly peaks → busiest station → baseline → join). |
| `QUALIFY` | [`mart_peak_load.sql:34`](../dbt/transitpulse/models/marts/mart_peak_load.sql#L34), [`mart_kpis_daily.sql:22`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql#L22), [`stg_bart_stations.sql:10`](../dbt/transitpulse/models/staging/stg_bart_stations.sql#L10) | Keeping the top row per group (peak hour per station, busiest station per day, latest observation) without a subquery. |
| `LAG` | [`mart_od_flows.sql:18`](../dbt/transitpulse/models/marts/mart_od_flows.sql#L18), [`mart_recovery.sql:24`](../dbt/transitpulse/models/marts/mart_recovery.sql#L24) | Month-over-month change per OD pair; change vs the previous weekday per station. |
| `SUM/AVG() OVER (… ROWS BETWEEN)` | [`mart_kpis_daily.sql:64`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql#L64), [`mart_recovery.sql:25`](../dbt/transitpulse/models/marts/mart_recovery.sql#L25), [`mart_peak_load.sql:22`](../dbt/transitpulse/models/marts/mart_peak_load.sql#L22) | Rolling 28-day average; 5-weekday average; a station's daily total alongside each hour. |
| `PERCENT_RANK`, `RANK` | [`mart_peak_load.sql:32`](../dbt/transitpulse/models/marts/mart_peak_load.sql#L32), [`mart_od_flows.sql:23`](../dbt/transitpulse/models/marts/mart_od_flows.sql#L23) | Station busyness percentile; destination rank from each origin. |
| Period-over-period self-joins | [`mart_kpis_daily.sql:69`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql#L69), [`mart_od_flows.sql:28`](../dbt/transitpulse/models/marts/mart_od_flows.sql#L28), [`mart_recovery.sql:30`](../dbt/transitpulse/models/marts/mart_recovery.sql#L30) | YoY vs the same weekday 364 days earlier; same month last year; same ISO week of 2019. |

**Missing:** an explicit **cohort** query (planned: stations grouped by opening year or by 2019 size band, tracked over time).

---

## ✅ #8 Business metrics

**What it does:** defines six KPIs once and computes them in one place, so the website, Looker Studio and Power BI
can't disagree.

**How it works:** [`docs/METRICS.md`](METRICS.md) gives each KPI's definition, formula, column and the question it
answers. [`mart_kpis_daily.sql`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql) computes them per day:
- recovery % (vs the same ISO week of 2019)
- daily entries
- rolling 28-day average
- YoY change
- peak-hour share
- busiest station and its share

Verified values: 2025 weekday recovery = 43.1% of 2019; Embarcadero is busiest; the peak hour is 5 PM.

---

## ✅ #11 Orchestration (local) · 🟡 Oracle VM

**What it does:** Dagster knows every step from download to marts as an **asset** with lineage. It runs yearly
partitions, keeps monthly schedules, and records metadata (row counts, drops, file hashes) on every run.

| Concept | Where | How |
|---|---|---|
| Software-defined assets | [`pipeline/assets/ingest.py`](../pipeline/assets/ingest.py) | `bart_gtfs`, `bart_stations_raw`, `web_map_data`, `bart_od_files` → `bart_od_parquet` → `raw/bart_od`. Each returns `MaterializeResult` metadata. |
| Partitions + backfills | [`ingest.py:27-28`](../pipeline/assets/ingest.py#L27) | Static yearly partitions 2018 → now; historical years are a UI backfill and the current year is re-run monthly. |
| Idempotent downloads | [`ingest.py:31`](../pipeline/assets/ingest.py#L31) | SHA-256 before/after; metadata records whether the file changed. |
| dbt integration | [`pipeline/assets/dbt.py:23-38`](../pipeline/assets/dbt.py#L23) | `@dbt_assets` turns every model/snapshot/test into an asset; the translator maps dbt sources onto the ingest assets so lineage is one graph. |
| Schedules | [`definitions.py:42`, `:48`](../pipeline/definitions.py#L42) | 6th of each month 06:00 Pacific: ingest the current year; 08:00: stations, map data, `dbt build`. |
| Swappable resources | [`pipeline/resources.py`](../pipeline/resources.py) | `Storage` (`local` files vs `gcp` GCS+BigQuery) and `SparkRunner` (in-process vs Docker), chosen by environment variables. |

**Missing:** deployment on the Oracle VM (systemd unit), and the GCP mode exercised for real.

---

## 🟡 #4 Larger datasets

**What it does now:** 19.3M rows (2019 + 2025) processed with Spark, partitioned Parquet, and BigQuery partitioning
and clustering configured. **Missing:** the full 2018–2025 backfill (~70M rows) and Bay Wheels.

---

## 🟡 #1 Cloud + Terraform

**What it does:** defines the whole GCP footprint as code. It's validated, but not yet applied.

| Resource | Where | Why |
|---|---|---|
| Budget alerts $1 / $5 | [`main.tf:27`](../infra/terraform/main.tf#L27) | Cost guardrail as code (TRANSITPULSE_PLAN §8). |
| Enabled APIs | [`main.tf:14`](../infra/terraform/main.tf#L14) | BigQuery, GCS, Run, Artifact Registry, IAM, STS, billing budgets. |
| Raw bucket | [`storage.tf`](../infra/terraform/storage.tf) | Uniform access, public access blocked, temp files expire. |
| BigQuery datasets | [`bigquery.tf`](../infra/terraform/bigquery.tf) | `raw/staging/marts/ml/ci`; CI tables auto-expire after 3 days ([:19](../infra/terraform/bigquery.tf#L19)). |
| Artifact Registry | [`registry.tf`](../infra/terraform/registry.tf) | Keeps the last 3 images to stay in the free 0.5 GB. |
| Least-privilege IAM | [`iam.tf`](../infra/terraform/iam.tf) | `sa-pipeline` writes; `sa-agent` is **read-only on marts/ml** ([:37](../infra/terraform/iam.tf#L37)), the base of the agent's SQL guardrails. |

**Missing:** `terraform apply` (needs the GCP project), Cloud Run, Workload Identity Federation.

---

## 🟡 #13 CI/CD

**What it does:** [`ci.yml`](../.github/workflows/ci.yml) runs on every PR in four jobs:
1. Python: ruff, pytest, `dbt parse`
2. Spark tests on Java 17 ([:30](../.github/workflows/ci.yml#L30))
3. Web: node schedule tests + Playwright ([:42](../.github/workflows/ci.yml#L42))
4. `terraform fmt/validate` ([:58](../.github/workflows/ci.yml#L58))

Every command in it passes locally. **Missing:** a GitHub remote (so it has never run in Actions),
`dbt build --target ci`, `terraform plan`, and the deploy workflow.

---

## 🟡 #18 Reproducibility

**What it does:**
- `uv.lock` and `package-lock.json` pin every dependency.
- [`tasks.py`](../tasks.py) gives the same commands on Windows and Linux.
- Spark's runtime is a Dockerfile.
- The map data build is deterministic: two builds produce byte-identical files (checked with hashes).
- The dbt `local` target rebuilds the warehouse with no cloud account.

**Missing:** a one-command `make up` (Docker Compose with the API + Ollama) and a public evaluation set.

---

## ✅ Responsive, accessible web front end (added for the site)

**What it does:** a single-page site that fits any screen from 320 px to 2560 px, with a live map of every
scheduled BART train drawn as small pills that scale with the map.

| Concept | Where | How |
|---|---|---|
| Design tokens | [`web/css/tokens.css`](../web/css/tokens.css) | 1:1 with `DESIGN.md`; no raw values elsewhere. |
| Fluid sizing | [`tokens.css:70-124`](../web/css/tokens.css#L70) | `clamp()` type and spacing scale continuously; breakpoints only rearrange layout. |
| Container queries | [`map.css:99`, `:157`, `:177`, `:237`](../web/css/map.css#L99) | The map hides minor labels, shortens the clock and floats/stacks its controls based on **its own width**. |
| Schedule interpolation | [`schedule.js:42` `tripPosition`, `:81` `trainsAt`](../web/js/map/schedule.js#L42) | Picks the services running on a Pacific date (holiday exceptions included) and interpolates each trip between departure and arrival; after-midnight trips belong to the previous service day. |
| Parallel lanes | [`geometry.js:49` `offsetPolyline`](../web/js/map/geometry.js#L49) | Offsets each line sideways by lane index, with a consistent west/south side and a miter limit. |
| Small trains that scale | [`trains.js:6` `trainSize`](../web/js/map/trains.js#L6) | Length `clamp(6, 1.2% of map width, 14)` px; drawn on a DPR-sized canvas so they're sharp. |
| Resize handling | [`map.js:166`, `:526`](../web/js/map/map.js#L166) | `ResizeObserver` → re-fit, re-render, resize canvas × `devicePixelRatio`. |
| Label collision avoidance | [`network.js:149` `placeLabels`](../web/js/map/network.js#L149) | Greedy placement (hubs first), skipping labels that would overlap labels, stations or track. |
| Battery/perf | [`map.js:527`](../web/js/map/map.js#L527) | Pauses off-screen/hidden; redraw rate follows replay speed. |
| Accessibility | [`index.html:193`](../web/index.html#L193), [`map.js:77`](../web/js/map/map.js#L77) | Live-region summary, List view, reduced motion, focus-trapped menu, skip link, 44 px touch targets. |
| Tests | [`tests/web/site.spec.js`](../tests/web/site.spec.js), [`schedule.test.mjs`](../tests/web/schedule.test.mjs) | 17 Playwright + 5 node tests. |

---

## ⬜ Not started (planned milestone)
| # | Skill | Milestone | Planned location |
|---|---|---|---|
| 3 | Load and latency testing (Locust) | M7 | `tests/load/` |
| 5 | LLM tracing (Langfuse) | M5 | `api/agent/` |
| 6 | A/B testing (power analysis, offline A/B) | M5 | `eval/`, `docs/AB_TEST.md` |
| 7 | Formal statistics (bootstrap CIs, McNemar, clustered SEs) | M3–M5 | `ml/forecast/`, `analysis/causal/`, `eval/` |
| 9 | BI dashboards (Looker Studio, Power BI + DAX) | M2 | `bi/` |
| 16 | Fine-tuning (QLoRA) | M6 | `ml/finetune/` |
| 19 | Agents and tool use (LangGraph text-to-SQL) | M5 | `api/agent/` (the API contract and the streaming UI already exist) |
| 21 | Causal inference (difference-in-differences) | M4 | `analysis/causal/`, `docs/FINDINGS.md` |
| — | Forecasting (LightGBM, walk-forward) | M3 | `ml/forecast/` |
