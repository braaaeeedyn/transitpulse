# TransitPulse: skills map

Where each skill from [`TRANSITPULSE_PLAN.md`](TRANSITPULSE_PLAN.md) (§2 gap table, §6 skills list) is implemented,
what it does in this project, and how it works. Links point at exact lines.

**Status:** ✅ implemented and verified · 🟡 partly implemented (what's missing is stated) · ⬜ not started.
Verified = it ran on real data or passed tests; statuses last checked 2026-10-18 (see [`CURRENT_STATE.md`](CURRENT_STATE.md)).

| # | Skill (gap) | Status | Main location |
|---|---|---|---|
| 1 | Cloud + Terraform | ✅ (all applied: M0, Cloud Run, WIF) | [`infra/terraform/`](../infra/terraform/), [`docs/CLOUD_RUN.md`](CLOUD_RUN.md) |
| 2 | Advanced SQL | 🟡 | [`dbt/transitpulse/models/marts/`](../dbt/transitpulse/models/marts/) |
| 3 | Load and latency testing | 🟡 (Locust locally; Cloud Run timed per request, not under load) | [`load/`](../load/) |
| 4 | Larger datasets | ✅ (68M BART rows + 26M Bay Wheels trips in BigQuery) | [`pipeline/spark/clean_bart_od.py`](../pipeline/spark/clean_bart_od.py), [`pipeline/baywheels.py`](../pipeline/baywheels.py) |
| 5 | Monitoring (LLM tracing) | ❌ dropped (2026-10-18) | Langfuse was wired in but never switched on, so it was removed ([`DEVLOG.md`](DEVLOG.md)) |
| 6 | A/B testing | ✅ (llama3.1:8b, local) | [`eval/ab.py`](../eval/ab.py), [`docs/AB_TEST.md`](AB_TEST.md) |
| 7 | Formal statistics | ✅ | [`ml/forecast/evaluate.py`](../ml/forecast/evaluate.py), [`analysis/causal/did.py`](../analysis/causal/did.py), [`eval/ab.py`](../eval/ab.py) |
| 8 | Business metrics | ✅ | [`docs/METRICS.md`](METRICS.md), [`mart_kpis_daily.sql`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql) |
| 9 | BI dashboards | 🟡 (guide and check week only; the reports need the owner's accounts) | [`bi/README.md`](../bi/README.md) |
| 10 | Warehouse + dbt + dimensional modeling | ✅ (local and BigQuery) | [`dbt/transitpulse/`](../dbt/transitpulse/) |
| 11 | Orchestration | ✅ (local, and running on the Oracle VM) | [`pipeline/definitions.py`](../pipeline/definitions.py), [`deploy/oracle/`](../deploy/oracle/) |
| 13 | CI/CD | 🟡 (CI and deploy-on-push live; dbt and Terraform checks in CI wait for a CI identity) | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`deploy.yml`](../.github/workflows/deploy.yml) |
| 16 | Fine-tuning | ⬜ | — |
| 17 | Spark / PySpark | ✅ | [`pipeline/spark/clean_bart_od.py`](../pipeline/spark/clean_bart_od.py) |
| 18 | Reproducibility | 🟡 | [`tasks.py`](../tasks.py), [`uv.lock`](../uv.lock), [`Dockerfile`](../Dockerfile), [`pipeline/spark/Dockerfile`](../pipeline/spark/Dockerfile) |
| 19 | Agents and tool use | ✅ (local, and live on Cloud Run with Gemini) | [`api/agent/`](../api/agent/), [`api/routes/ask.py`](../api/routes/ask.py), [`eval/`](../eval/), [`web/js/ask.js`](../web/js/ask.js) |
| 21 | Causal inference | ✅ | [`analysis/causal/`](../analysis/causal/), [`docs/FINDINGS.md`](FINDINGS.md) |
| — | Forecasting (LightGBM, walk-forward, quantiles) | ✅ (local and BigQuery, retrained weekly on the VM) | [`ml/forecast/`](../ml/forecast/) |
| — | Bay Wheels ingest + cleaning (second data source) | ✅ (local and BigQuery, 2018 → 2026-09) | [`pipeline/baywheels.py`](../pipeline/baywheels.py) |
| — | Data API over the warehouse (DuckDB / BigQuery) | ✅ | [`api/warehouse.py`](../api/warehouse.py), [`api/routes/data.py`](../api/routes/data.py) |
| — | Responsive, accessible web front end (added for the site) | ✅ | [`web/`](../web/) |
| — | Policy analysis: BART station closures (added 2026-10-17) | ✅ | [`docs/STATION_CLOSURES.md`](STATION_CLOSURES.md), [`mart_station_closures.sql`](../dbt/transitpulse/models/marts/mart_station_closures.sql), [`web/js/closures.js`](../web/js/closures.js), [`web/js/map/whatif.js`](../web/js/map/whatif.js) |

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

## ✅ #10 Warehouse + dbt + dimensional modeling (local and BigQuery)

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
| SCD2 point-in-time join | [`fct_trips_hourly.sql:35-42`](../dbt/transitpulse/models/core/fct_trips_hourly.sql#L35) | Each trip joins the station version whose `[valid_from, valid_to)` contains the trip date. All 67.77M local rows matched. |
| Incremental model | [`fct_trips_hourly.sql:1-19`](../dbt/transitpulse/models/core/fct_trips_hourly.sql#L1) | Re-processes the last 35 days, anything newer, and any date not in the table yet ([:18](../dbt/transitpulse/models/core/fct_trips_hourly.sql#L18), an anti-join), so a backfilled older year is loaded instead of skipped. `insert_overwrite` of date partitions on BigQuery, `delete+insert` on DuckDB ([macro](../dbt/transitpulse/macros/schema_and_dates.sql)). A singular test ([`assert_fct_trips_hourly_has_every_od_date.sql`](../dbt/transitpulse/tests/assert_fct_trips_hourly_has_every_od_date.sql)) fails the build if any staged date is missing; [`tests/test_dbt_regressions.py`](../tests/test_dbt_regressions.py) builds Dec 2025 and then backfills 2018/2019 days incrementally. |
| Partitioning + clustering | [`fct_trips_hourly.sql:6-7`](../dbt/transitpulse/models/core/fct_trips_hourly.sql#L6), [`ingest.py:166-167`](../pipeline/assets/ingest.py#L166) | BigQuery tables are partitioned by `trip_date` and clustered by station, so date-filtered queries scan only the days they need. |
| Cross-database macros | [`macros/schema_and_dates.sql`](../dbt/transitpulse/macros/schema_and_dates.sql) | `adapter.dispatch` gives BigQuery and DuckDB their own SQL for ISO week, weekday and the date spine. |
| Tests | `schema.yml` per layer; [`tests/generic/non_negative.sql`](../dbt/transitpulse/tests/generic/non_negative.sql), [`unique_combination.sql`](../dbt/transitpulse/tests/generic/unique_combination.sql) | `not_null`, `unique`, `relationships` (facts → dims), `accepted_values` (hour 0–23, weekday 1–7) and two custom generic tests (no negative ridership, composite-key uniqueness). |
| Cost cap | [`profiles.yml:22`](../dbt/transitpulse/profiles.yml#L22) | `maximum_bytes_billed` (2 GB dev, 500 MB CI) makes BigQuery refuse any query that would scan more. |

**Bay Wheels models (local):** [`stg_baywheels_trips.sql`](../dbt/transitpulse/models/staging/stg_baywheels_trips.sql) → [`fct_bike_trips_daily.sql`](../dbt/transitpulse/models/core/fct_bike_trips_daily.sql) → [`mart_bikes_vs_trains.sql`](../dbt/transitpulse/models/marts/mart_bikes_vs_trains.sql), which is a **full outer join** of the two monthly series ([:32](../dbt/transitpulse/models/marts/mart_bikes_vs_trains.sql#L32)), so a month with only one source still appears, plus an index vs the same month of 2019 ([:35](../dbt/transitpulse/models/marts/mart_bikes_vs_trains.sql#L35)). [`mart_ridership_monthly.sql`](../dbt/transitpulse/models/marts/mart_ridership_monthly.sql) feeds the site's chart. Local build: 83/83 nodes (68 tests). [`tests/test_dbt_fixture.py`](../tests/test_dbt_fixture.py) runs `dbt build` on a generated dataset in CI.

**Missing:** the `ci` target. (Bay Wheels is on BigQuery too: `raw.baywheels_trips` 2018 → 2026-09.)

---

## 🟡 #2 Advanced SQL

**What it does:** the marts answer the analyst questions (recovery, peaks, flows, daily KPIs) with window
functions, CTEs, `QUALIFY` and period-over-period comparisons.

| Technique | Where | Used for |
|---|---|---|
| CTEs | every model, e.g. [`mart_kpis_daily.sql`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql) | Building KPIs in named steps (system totals → hourly peaks → busiest station → baseline → join). |
| `QUALIFY` | [`mart_peak_load.sql:34`](../dbt/transitpulse/models/marts/mart_peak_load.sql#L34), [`mart_kpis_daily.sql:22`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql#L22), [`stg_bart_stations.sql:10`](../dbt/transitpulse/models/staging/stg_bart_stations.sql#L10) | Keeping the top row per group (peak hour per station, busiest station per day, latest observation) without a subquery. |
| `LAG` | [`mart_od_flows.sql:18`](../dbt/transitpulse/models/marts/mart_od_flows.sql#L18), [`mart_recovery.sql:25`](../dbt/transitpulse/models/marts/mart_recovery.sql#L25) | Month-over-month change per OD pair; change vs the previous weekday per station. |
| `SUM/AVG() OVER (… ROWS BETWEEN)` | [`mart_recovery.sql:26`](../dbt/transitpulse/models/marts/mart_recovery.sql#L26), [`mart_peak_load.sql:22`](../dbt/transitpulse/models/marts/mart_peak_load.sql#L22) | 5-weekday average; a station's daily total alongside each hour. |
| Calendar-window range self-join | [`mart_kpis_daily.sql:34`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql#L34) | Rolling 28-day average over the days present in [d − 27, d] plus a count of them, so gaps in the data shorten the window instead of pulling in older days (a `ROWS` window can't; `RANGE` over dates isn't portable between DuckDB and BigQuery). |
| ISO year vs calendar year | [`schema_and_dates.sql:19` `iso_year`](../dbt/transitpulse/macros/schema_and_dates.sql#L19), [`mart_recovery.sql:14`](../dbt/transitpulse/models/marts/mart_recovery.sql#L14) | A dispatched macro (`extract(isoyear …)` on BigQuery, `isoyear()` on DuckDB); baselines match ISO weeks of ISO year 2019, so Dec 30–31, 2019 (ISO 2020) aren't mixed into week 1. |
| `PERCENT_RANK`, `RANK` | [`mart_peak_load.sql:32`](../dbt/transitpulse/models/marts/mart_peak_load.sql#L32), [`mart_od_flows.sql:23`](../dbt/transitpulse/models/marts/mart_od_flows.sql#L23) | Station busyness percentile; destination rank from each origin. |
| Period-over-period self-joins | [`mart_kpis_daily.sql:81`](../dbt/transitpulse/models/marts/mart_kpis_daily.sql#L81), [`mart_od_flows.sql:28`](../dbt/transitpulse/models/marts/mart_od_flows.sql#L28), [`mart_recovery.sql:30`](../dbt/transitpulse/models/marts/mart_recovery.sql#L30) | YoY vs the same weekday 364 days earlier; same month last year; same ISO week of ISO year 2019. |

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

## ✅ #11 Orchestration (local and the Oracle VM)

**What it does:** Dagster knows every step from download to marts as an **asset** with lineage. It runs yearly
partitions, keeps monthly schedules, and records metadata (row counts, drops, file hashes) on every run.

| Concept | Where | How |
|---|---|---|
| Software-defined assets | [`pipeline/assets/ingest.py`](../pipeline/assets/ingest.py) | `bart_gtfs`, `bart_stations_raw`, `web_map_data`, `bart_od_files` → `bart_od_parquet` → `raw/bart_od`. Each returns `MaterializeResult` metadata. |
| Partitions + backfills | [`ingest.py:27-28`](../pipeline/assets/ingest.py#L27) | Static yearly partitions 2018 → now; historical years are a UI backfill and the current year is re-run monthly. |
| Idempotent downloads | [`ingest.py:31`](../pipeline/assets/ingest.py#L31) | SHA-256 before/after; metadata records whether the file changed. |
| dbt integration | [`pipeline/assets/dbt.py:23-38`](../pipeline/assets/dbt.py#L23) | `@dbt_assets` turns every model/snapshot/test into an asset; the translator maps dbt sources onto the ingest assets so lineage is one graph. |
| Schedules + sensors | [`pipeline/definitions.py`](../pipeline/definitions.py) | BART ingest is a sensor (`bart_od_updates`): every 6 hours it HEADs BART's files and reloads a year when `Last-Modified` changes, with the stamps in the sensor cursor. A run-status sensor (`models_after_ingest`) rebuilds dbt after each successful ingest. Pacific-time schedules: Bay Wheels on the 7th at 06:30 (previous month's year, so January picks up December), models on the 6th at 08:00, forecast every Monday at 09:00. |
| Bay Wheels assets | [`pipeline/assets/baywheels.py:26`, `:55`, `:84`](../pipeline/assets/baywheels.py#L26) | `baywheels_files[year]` → `baywheels_parquet[year]` → `raw/baywheels_trips[year]`; the dbt source maps onto the last one, so lineage runs through to the marts. |
| ML asset | [`pipeline/assets/forecast.py:21`](../pipeline/assets/forecast.py#L21) | `forecast_station_daily` (group `ml`) depends on `marts/fct_station_daily` and records MAE, the CI and coverage as metadata. |
| VM deployment | [`deploy/oracle/`](../deploy/oracle/), [`docs/ORACLE_VM.md`](ORACLE_VM.md) | systemd daemon + web units (non-root, venv on `PATH`, `MemoryMax`, `Nice`, UI on 127.0.0.1 only); an idempotent [`bootstrap.sh`](../deploy/oracle/bootstrap.sh) (apt/dnf, Java 17, `uv sync --frozen`, `dbt parse`, key-file checks at [:123](../deploy/oracle/bootstrap.sh#L123)). |
| Swappable resources | [`pipeline/resources.py`](../pipeline/resources.py) | `Storage` (`local` files vs `gcp` GCS+BigQuery) and `SparkRunner` (in-process vs Docker), chosen by environment variables. |

**Running** on the Oracle VM in `gcp` mode (last updated 2026-10-18 at `6671168`), Bay Wheels, the forecast and the
closures models included.

---

## ✅ #4 Larger datasets

**What it does now:** BART 2018–2025 (67.8M rows, 4.2 GB) cleaned with Spark and loaded into partitioned,
clustered BigQuery tables. Bay Wheels 2018 → Sep 2026 (25,989,969 trips) in BigQuery; locally, 2019 + 2025 (6.9M trips from 24 irregularly
named monthly zips) clean with DuckDB in 56 s into partitioned Parquet.

---

## ✅ #1 Cloud + Terraform (all applied)

**What it does:** defines the whole GCP footprint as code. The M0 resources are applied (BigQuery, bucket, registry,
service accounts, budgets). The Cloud Run service and GitHub federation are applied too (live since 2026-10-14);
[`docs/CLOUD_RUN.md`](CLOUD_RUN.md) is the runbook.

| Resource | Where | Why |
|---|---|---|
| Budget alerts $1 / $5 | [`main.tf:30`](../infra/terraform/main.tf#L30) | Cost guardrail as code (TRANSITPULSE_PLAN §8); a test keeps them at $1/$5. |
| Enabled APIs | [`main.tf:4`](../infra/terraform/main.tf#L4) | BigQuery, GCS, Run, Artifact Registry, IAM, STS, billing budgets, Secret Manager. |
| Raw bucket | [`storage.tf`](../infra/terraform/storage.tf) | Uniform access, public access blocked, temp files expire. |
| BigQuery datasets | [`bigquery.tf`](../infra/terraform/bigquery.tf) | `raw/staging/marts/ml/ci`; CI tables auto-expire after 3 days ([:19](../infra/terraform/bigquery.tf#L19)). |
| Artifact Registry | [`registry.tf`](../infra/terraform/registry.tf) | Keeps the last 3 images to stay in the free 0.5 GB (the image is 119 MB compressed). |
| Least-privilege IAM | [`iam.tf`](../infra/terraform/iam.tf) | `sa-pipeline` writes; `sa-agent` is **read-only on marts/ml** ([:37](../infra/terraform/iam.tf#L37)), the base of the agent's SQL guardrails. |
| Cloud Run, scale to zero | [`cloudrun.tf:48`](../infra/terraform/cloudrun.tf#L48) | 0–2 instances, 1 vCPU / 512 MiB, `cpu_idle` ([:66](../infra/terraform/cloudrun.tf#L66)) so CPU is billed only during requests; runs as `sa-agent` ([:44](../infra/terraform/cloudrun.tf#L44)). |
| Feature flag + secret | [`cloudrun.tf:9`](../infra/terraform/cloudrun.tf#L9), [:31](../infra/terraform/cloudrun.tf#L31) | `TP_AGENT_ENABLED` from `var.agent_enabled` (default false); the Gemini key's secret access and env var exist only when it's on, and the secret version is added by hand so the key never enters state. |
| CI owns the image | [`cloudrun.tf:103`](../infra/terraform/cloudrun.tf#L103) | `ignore_changes` on the image: a later `terraform apply` never rolls back a deploy. |
| Public only where needed | [`cloudrun.tf:117`](../infra/terraform/cloudrun.tf#L117) | `run.invoker` for `allUsers` on this one service; nothing else in the project is public (tested). |
| Workload Identity Federation | [`wif.tf:13`](../infra/terraform/wif.tf#L13) | GitHub OIDC; the `attribute_condition` ([:25](../infra/terraform/wif.tf#L25)) accepts only `braaaeeedyn/transitpulse` on `refs/heads/main`. No JSON key exists. |
| Narrow deployer | [`wif.tf:39`](../infra/terraform/wif.tf#L39) | `sa-deploy`: registry writer on one repo, `run.developer` on one service, actAs on `sa-agent` only; no owner/editor. |
| Static tests | [`tests/test_infra_cloudrun.py`](../tests/test_infra_cloudrun.py) | Parses the HCL (python-hcl2) and the workflow YAML: scaling, IAM, WIF pin, budgets, the deploy gate. |

**Missing:** `terraform plan` in CI (it needs a CI identity; owner step 9).

---

## 🟡 #13 CI/CD

**What it does:** [`ci.yml`](../.github/workflows/ci.yml) runs on every PR and push to `main` in five jobs:
1. Python: ruff, `dbt parse`, pytest (incl. a DuckDB `dbt build` on a generated fixture, forecast, agent and Bay Wheels tests), shellcheck
2. Spark tests on Java 17 ([:30](../.github/workflows/ci.yml#L30))
3. Web: node tests + Playwright ([:42](../.github/workflows/ci.yml#L42))
4. Container ([:61](../.github/workflows/ci.yml#L61)): builds the Cloud Run image and runs [`tests/deploy/`](../tests/deploy/test_container.py) against it (non-root, site + cache headers, 503 without a warehouse, agent refusal with the fake LLM, no secrets or dev files in the image)
5. `terraform fmt/validate`

[`deploy.yml`](../.github/workflows/deploy.yml) is continuous deployment. It is gated by
`if: vars.DEPLOY_ENABLED == 'true'` ([:27](../.github/workflows/deploy.yml#L27)) and authenticates with
`id-token: write` ([:31](../.github/workflows/deploy.yml#L31)) through Workload Identity Federation
([:53](../.github/workflows/deploy.yml#L53)), with no stored key. It builds an image tagged with the commit SHA, runs the
container smoke tests on it before pushing ([:47](../.github/workflows/deploy.yml#L47)), since it doesn't wait for
`ci.yml`, then runs `gcloud run deploy --image` ([:67](../.github/workflows/deploy.yml#L67)) and curls the new revision.
Terraform is deliberately not run in Actions. Both workflows pass actionlint.

Deploys are on (`DEPLOY_ENABLED=true`) since 2026-10-14. **Missing:** `dbt build --target ci` and `terraform plan` in
CI (they need a CI identity; owner step 9).

---

## 🟡 #18 Reproducibility

**What it does:**
- `uv.lock` and `package-lock.json` pin every dependency.
- [`tasks.py`](../tasks.py) gives the same commands on Windows and Linux.
- Spark's runtime is a Dockerfile.
- The API's runtime is a Dockerfile ([`Dockerfile:22`](../Dockerfile#L22)). It runs `uv sync --frozen` from the same
  lock file with only the runtime groups, so the image runs exactly the tested versions. Runtime stage: non-root
  uid 10001 ([:42](../Dockerfile#L42)), `api/` + `web/` + the venv only (`.dockerignore` is an allowlist).
- The map data build is deterministic: two builds produce byte-identical files (checked with hashes).
- The dbt `local` target rebuilds the warehouse with no cloud account.
- `make up` ([`docker-compose.yml`](../docker-compose.yml), [`tasks.py`](../tasks.py) `up`) starts the site, API and
  agent on a pinned Ollama image from a fresh clone, with the warehouse mounted read-only; a no-Docker test reads
  the YAML and a `docker` test starts the `api` service and always takes it down.

**Missing:** a public evaluation set.

---

## ✅ Responsive, accessible web front end (added for the site)

**What it does:** a single-page site that fits any screen from 320 px to 2560 px, with a live map of every
scheduled BART train drawn as small pills that scale with the map.

| Concept | Where | How |
|---|---|---|
| Design tokens | [`web/css/tokens.css`](../web/css/tokens.css) | 1:1 with `DESIGN.md`; no raw values elsewhere. |
| Fluid sizing | [`tokens.css:70-124`](../web/css/tokens.css#L70) | `clamp()` type and spacing scale continuously; breakpoints only rearrange layout. |
| Container queries | [`map.css:99`, `:157`, `:177`, `:237`](../web/css/map.css#L99) | The map hides minor labels, shortens the clock and floats/stacks its controls based on **its own width**. |
| Schedule interpolation | [`schedule.js:62` `tripPosition`, `:101` `trainsAt`](../web/js/map/schedule.js#L62) | Picks the services running on a Pacific date (holiday exceptions included) and interpolates each trip between departure and arrival; after-midnight trips belong to the previous service day. |
| Parallel lanes | [`geometry.js:49` `offsetPolyline`](../web/js/map/geometry.js#L49) | Offsets each line sideways by lane index, with a consistent west/south side and a miter limit. |
| Small trains that scale | [`trains.js:6` `trainSize`](../web/js/map/trains.js#L6) | Length `clamp(6, 1.2% of map width, 14)` px; drawn on a DPR-sized canvas so they're sharp. |
| Resize handling | [`map.js:168` `layout`, `:589`](../web/js/map/map.js#L168) | `ResizeObserver` → re-fit, re-render, resize canvas × `devicePixelRatio`. |
| Label collision avoidance | [`network.js:149` `placeLabels`](../web/js/map/network.js#L149) | Greedy placement (hubs first), skipping labels that would overlap labels, stations or track. |
| Battery/perf | [`map.js:590`](../web/js/map/map.js#L590) |
| Timetable expiry | [`schedule.js:17` `timetableRange`, `:28` `isOutsideTimetable`](../web/js/map/schedule.js#L17), [`map.js:264` `updateNotice`](../web/js/map/map.js#L264) | Outside the bundled feed's dates the notice says the timetable ended (with the date) instead of "No trains running right now". | Pauses off-screen/hidden; redraw rate follows replay speed. |
| Accessibility | [`index.html:207`](../web/index.html#L207), [`map.js:578` `updateSummary`](../web/js/map/map.js#L578) | Live-region summary, List view, reduced motion, focus-trapped menu, skip link, 44 px touch targets. |
| Chart helpers | [`chart.js:22` `niceTicks`, `:56` `linePath`, `:80` `bandPath`](../web/js/chart.js#L22) | Pure functions (node-tested): nice 1/2/2.5/5 ticks, fewer below 600 px, and paths that **break at missing months** instead of bridging gaps. |
| No layout shift | [`charts.css:20-45`](../web/css/charts.css#L20), [`index.html:219`](../web/index.html#L219) | Skeleton heights are the same `font-size × line-height` calcs as the loaded text, and charts have fixed aspect ratios; Playwright checks the Trends height changes by ≤ 2 px. |
| Trends band | [`trends.js:193` `initTrends`](../web/js/trends.js#L193) | KPI tiles with ⓘ definitions and ink ▲/▼ deltas, the ridership chart and the bikes-vs-trains chart; 503 / error + Retry / empty states; the bike chart fails on its own. |
| ARIA combobox | [`forecast.js:28` `matchStations`, `:182` `initForecast`](../web/js/forecast.js#L28) | Focus stays in the input; `aria-activedescendant` tracks the option; ↑/↓, Enter, Esc; ranked matches by name or code. |
| Audits in the test suite | [`a11y.spec.js`](../tests/web/a11y.spec.js), [`lighthouse.mjs`](../tests/web/lighthouse.mjs) | axe's colour-contrast rule on the loaded page (390 and 1440 px) and the style guide: 0 violations. Lighthouse mobile (median of 3, local): 98 / 100 / 100 after adding gzip, gated at 90 / 95 / 95. |
| Style guide from the source | [`styleguide.js:21` `rootTokens`](../web/js/styleguide.js#L21) | Token tables are read from `tokens.css`'s own `:root` rules (media overrides too), so the page can't drift; a Playwright test checks every token and component block is on it. |
| Untrusted client storage | [`ask.js:27` `readHistory`](../web/js/ask.js#L27) | The last 5 Q&As in `sessionStorage` are reshaped on read and escaped on render; a Playwright test plants an `<img onerror>` entry and checks it renders as text. |
| Tests | [`tests/web/site.spec.js`](../tests/web/site.spec.js), [`data.spec.js`](../tests/web/data.spec.js), [`chart.test.mjs`](../tests/web/chart.test.mjs), [`forecast.test.mjs`](../tests/web/forecast.test.mjs), [`forecast-caption.test.mjs`](../tests/web/forecast-caption.test.mjs) | 29 Playwright (data endpoints mocked with JSON fixtures) + 19 node tests. |

---

## ✅ Forecasting (local and BigQuery)

**What it does:** forecasts daily entries at every BART station for the 14 days after the latest data, with a
calibrated band, and checks it honestly against a seasonal-naive baseline. Latest local run (same data as
production): MAE 283.1 vs 548.5, improvement 265.4 [199.6, 339.9].

| Concept | Where | How |
|---|---|---|
| Direct multi-horizon rows | [`features.py:51` `make_rows`](../ml/forecast/features.py#L51) | One row per (station, origin t, horizon h); one global model learns all 14 horizons, with `horizon` as a feature. |
| No leakage | [`features.py:69`](../ml/forecast/features.py#L69), [`:102`](../ml/forecast/features.py#L102) | Every feature comes from data at or before t (rolling windows at t, the same weekday at t−k with k ≤ 6). A test wrecks all data after t and checks the features don't change. |
| Gaps are never bridged | [`features.py:137`](../ml/forecast/features.py#L137) | Calendar-based windows: a missing day makes the 28-day stats NaN and the row is dropped. |
| Scale-free target | [`model.py:41` `fit`](../ml/forecast/model.py#L41) | Targets are divided by the station's 28-day mean, so busy and quiet stations share one model; predictions are multiplied back. |
| Quantile regression | [`model.py:48`](../ml/forecast/model.py#L48), [`:63`](../ml/forecast/model.py#L63) | LightGBM `objective="quantile"` at α = 0.1/0.5/0.9; outputs are sorted and clipped at 0 so p10 ≤ p50 ≤ p90. |
| Baseline | [`model.py:23` `seasonal_naive`](../ml/forecast/model.py#L23) | The last observed value on the target's weekday at or before the origin. |
| Walk-forward validation | [`evaluate.py:24`, `:30`, `:38`](../ml/forecast/evaluate.py#L24) | 6 warm-up + 6 test origins 14 days apart; each fold trains only on targets ≤ its origin (730-day window) and is scored on the next 14 days. Metrics come from the 6 test folds only. |
| Interval calibration (split-conformal) | [`evaluate.py:69` `conformal_scores`, `:77` `conformal_quantile`, `:98` `calibrate`, `:128` `final_conformal_q`](../ml/forecast/evaluate.py#L69) | CQR scores (how far the actual fell outside p10–p90, in units of the station's level); each test fold moves both band edges by the finite-sample ⌈(n+1)·0.8⌉-th score of the 6 folds before it (asserted: all their targets ≤ its origin). p50 untouched, so MAE is identical (283.147 both ways locally). |
| Run log + outputs | [`run.py:32` `run_forecast`](../ml/forecast/run.py#L32), [`io.py:52`](../ml/forecast/io.py#L52) | `marts.forecast_station_daily` (raw p10/p50/p90 + published `lower`/`upper`) is replaced and `ml.forecast_runs` appended (metrics, CIs, raw and calibrated coverage, widths, per-fold JSON, params); DuckDB locally, BigQuery in gcp mode. |
| Schema evolution of the run log | [`io.py:38` `_add_missing_columns`](../ml/forecast/io.py#L38) | DuckDB adds new columns before `insert … by name`; BigQuery appends with `ALLOW_FIELD_ADDITION`, so adding a metric doesn't break the weekly VM run. |
| Tests | [`tests/test_forecast.py`](../tests/test_forecast.py) | Leakage, baseline, fold boundaries, bootstrap determinism, quantile order, an end-to-end run into a temp DuckDB, the finite-sample quantile, no use of later folds in calibration, unchanged p50/MAE, the calibrated columns, and schema evolution on DuckDB and (fake) BigQuery. |

**Honest limits:** trained on 2024-01-02 → 2025-12-31 (the 730-day window over 2018–2025 data). The raw p10–p90
held 70.5% of back-test days and the calibrated band 73.0% [71.7, 74.4], against 80%: calibration helps a little but
the Christmas fold (44%) drags it down, so the site calls it the "model range", not an 80% range.

---

## ✅ #21 Causal inference

**What it does:** a pre-registered difference-in-differences study of the 2018 eBART extension (did it bring new
riders to the Concord–Antioch line, or only move them?), served by `GET /api/findings` and the site's Findings band.
Result: verdict **new** under the pre-registered rule. The corridor is +4.2% [+1.6%, +7.1%] and the old stations
−23.9% [−25.8%, −21.8%] (95% placebo intervals), with a caveat about a monthly pre-trend. Details in
[`FINDINGS.md`](FINDINGS.md).

| Concept | Where | How |
|---|---|---|
| Pre-registration + amendment | [`design.py:256` `load`](../analysis/causal/design.py#L256), [`design.py:238` `apply_amendment`](../analysis/causal/design.py#L238) | Every set, window, bin, draw count and the seed is parsed from `preregistration.json` (sha256 pinned by a check), with Amendment 1 applied only if its `amends_sha256` and every `was` match. No station code is written in the code (a test enforces it). |
| Design validation | [`design.py:194` `validate`](../analysis/causal/design.py#L194), [`:218`](../analysis/causal/design.py#L218) | Sets are disjoint and cover every station, there are 34 controls, and each placebo set has the size of what it stands in for. For the corridor that is its 3 pre-opening stations. |
| Two-way fixed effects | [`did.py:119` `twfe`](../analysis/causal/did.py#L119) | ln(entries) on station and week dummies plus D = treated × post, statsmodels OLS, CR1 by station. |
| Exact double differences | [`did.py:208` `dd`](../analysis/causal/did.py#L208), [`did.py:214` `dd_bins`](../analysis/causal/did.py#L214) | On a balanced panel the TWFE coefficient is a weighted gap of means; tests and [`run.py:82`](../analysis/causal/run.py#L82) assert equality with statsmodels to 1e-8, so thousands of placebos cost one matrix product. |
| Aggregate unit (corridor) | [`did.py:63` `aggregate_unit`](../analysis/causal/did.py#L63) | Sums levels across stations before the log, with a missing station-week counted as 0, so a rider moving from PITT to ANTC leaves the unit unchanged. |
| Event study | [`did.py:135` `event_study`](../analysis/causal/did.py#L135), [`did.py:188` `bin_weights`](../analysis/causal/did.py#L188) | 4-week bins relative to e ∈ [−5, −2] (monthly: 3-month bins), with per-bin placebo bands. |
| Placebo (Conley–Taber) intervals | [`did.py:225` `draw_sets`](../analysis/causal/did.py#L225), [`did.py:258` `placebo`](../analysis/causal/did.py#L258), [`did.py:304`](../analysis/causal/did.py#L304) | Treatment is reassigned to sets of control stations only (all C(34,3) = 5,984 for legacy and corridor). The interval is [b − q97.5, b − q2.5] of the placebo estimates. All placebos are computed at once with a one-hot (draws × stations) matrix. |
| Decision rules | [`did.py:355` `verdict`](../analysis/causal/did.py#L355), [`did.py:367` `caution`](../analysis/causal/did.py#L367) | The pre-registered new / moved / fewer / inconclusive rule and caution flag, applied to the placebo intervals. |
| One reproducible run | [`run.py:114` `compute`](../analysis/causal/run.py#L114), [`run.py:305` `main`](../analysis/causal/run.py#L305) | Reads only committed CSVs and writes `api/data/findings.json` with sorted keys, 6-decimal floats and data-derived dates; `--check` recomputes byte-for-byte. |
| Validation before the real run | [`synthetic.py:40` `generate`](../analysis/causal/synthetic.py#L40), [`synthetic.py:89` `study`](../analysis/causal/synthetic.py#L89) | Known-effect panels. The 0.90 coverage bar caught the original corridor placebo, which led to Amendment 1. |
| Post-hoc trend adjustment (not pre-registered) | [`trend_adjusted.py:47` `trend_weights`](../analysis/causal/trend_adjusted.py#L47), [`:62` `gaps`](../analysis/causal/trend_adjusted.py#L62), [`:99` `compute`](../analysis/causal/trend_adjusted.py#L99) | OLS of the treated-minus-control gap on time over the pre-period, written as one weight vector so the adjusted effect of every one of the 5,984 placebo draws is a single matrix product; the same placebo interval and RI p as the pre-registered analysis. Labelled post-hoc and kept out of `findings.json` and the site. |
| Serving | [`api/routes/findings.py:33`](../api/routes/findings.py#L33), [`web/js/findings.js:101` `renderEventStudy`](../web/js/findings.js#L101) | `GET /api/findings` without a warehouse; the ink band renders the verdict, the figures and two event-study panels from the JSON. |
| Tests | [`tests/test_causal.py`](../tests/test_causal.py), [`tests/test_api_findings.py`](../tests/test_api_findings.py), [`tests/local/test_causal_local.py`](../tests/local/test_causal_local.py) | Prereg and amendment hashes, recovery of synthetic effects, inference formulas, the monthly parser, the FINDINGS.md numbers against the JSON, the API, and the inputs against the warehouse. |

**Honest limits:**
- There are 3 treated stations and 1 corridor unit, so per-station placebo p-values bottom out at 1/35.
- The daily data has only 20 pre weeks.
- The monthly pre-period shows the corridor drifting up against the controls, which the pre-registered caution rule
  doesn't test.

---

## ✅ #6 A/B testing

**What it does:** an offline A/B test of two prompt strategies for the Ask agent on the fixed 66-question eval set
([`AB_TEST.md`](AB_TEST.md)): arm A is today's prompt, arm B adds 5 retrieved example queries. The design and the
ship rule were fixed first, the power analysis was written from arm A before arm B ran, and the default setting
follows the rule. Result: 18/66 → 33/66, McNemar p = 0.0041, so B ships (`TP_AGENT_EXAMPLES_K` = 5).

| Concept | Where | How |
|---|---|---|
| Treatment as one setting | [`settings.py:43` `agent_examples_k`](../api/settings.py#L43), [`graph.py:174`](../api/agent/graph.py#L174) | One integer selects the arm everywhere (API, eval, Cloud Run); with 0 the prompts are byte-identical to the control (a sha256 fingerprint check). |
| Retrieval (the treatment) | [`prompts.py:108` `retrieve_examples`](../api/agent/prompts.py#L108), [`prompts.py:83` `sql_prompt`](../api/agent/prompts.py#L83) | BM25 (k1 1.2, b 0.75) in the standard library over the pool's question text; deterministic, ties in pool order, no network, so it runs the same on Cloud Run. |
| Leave-one-out | [`run_eval.py:70` `evaluate`](../eval/run_eval.py#L70), [`graph.py:292` `run_agent`](../api/agent/graph.py#L292) | The question being scored passes its own id as `exclude_examples`, so B never sees its own gold SQL. |
| Pool kept in sync | [`examples.py:16` `build`](../eval/examples.py#L16) | The eval's in-scope SQL questions exported to `api/agent/examples.json`; a test fails if the file drifts from `questions.yaml`. |
| Paired comparison | [`ab.py:145` `compare`](../eval/ab.py#L145) | Both arms joined by question id: accuracies, discordant counts b/c, McNemar p, bootstrap CI, and the three-part ship rule with its reasons. |
| Results can't drift from the write-up | [`ab.py:219` `check`](../eval/ab.py#L219) | Fails if an arm is missing, a summary doesn't cover all 76 ids, the eval set's hash changed, AB_TEST.md's numbers differ from a recomputation, or the default setting isn't what the rule gives. |
| Tests | [`tests/test_ab.py`](../tests/test_ab.py) | McNemar against scipy and exhaustive enumeration, seeded bootstrap, power monotone in the effect, deterministic leave-one-out retrieval, both arms' prompts through the real graph, the pool, the default, the doc. |

**Honest limits:** the pool is the eval set itself, so many questions have a near-twin (8 of the 20 that B fixed);
one model (llama3.1:8b), one run per arm (deterministic at temperature 0); production would run Gemini.

---

## ✅ #7 Formal statistics

**What it does now:** confidence intervals for model comparison, (M4) cluster-robust standard errors, Wald tests,
randomization inference and a simulation study of interval coverage, and (M5) an exact McNemar test, a paired
bootstrap and a simulation power analysis.

| Technique | Where | How |
|---|---|---|
| Paired bootstrap over stations | [`evaluate.py:162` `paired_bootstrap`](../ml/forecast/evaluate.py#L162) | Resamples stations with replacement (B = 1000, fixed seed) and recomputes MAE/RMSE for both models on the **same** resample, so the CI of the difference accounts for the pairing. Stations are the resampling unit because errors within a station are correlated across days. |
| Vectorised resampling | [`evaluate.py:180-184`](../ml/forecast/evaluate.py#L180) | Per-station error sums, then a (B × stations) count matrix times the sums: 1000 resamples in milliseconds. |
| Percentile CIs | [`evaluate.py:206`](../ml/forecast/evaluate.py#L206) | 2.5th/97.5th percentiles for every metric, the MAE difference and the raw and calibrated interval coverage. |
| Walk-forward (time-series CV) | [`evaluate.py:30` `fold_split`](../ml/forecast/evaluate.py#L30) | Out-of-time evaluation only; no random splits. |
| Cluster-robust (CR1) SEs | [`did.py:105` `_fit`](../analysis/causal/did.py#L105), [`did.py:119` `twfe`](../analysis/causal/did.py#L119) | statsmodels OLS with `cov_type="cluster"` by station and `use_t=True` (t with G−1 df). A test checks it against a hand-computed sandwich with the G/(G−1)·(N−1)/(N−K) correction. |
| Joint Wald test | [`did.py:135` `event_study`](../analysis/causal/did.py#L135) | F test that every pre-period event-study bin is zero (the reference bin excluded). |
| Exact McNemar test | [`ab.py:44` `mcnemar_exact`](../eval/ab.py#L44) | Two-sided exact binomial test on the discordant pairs, min(1, 2 × lower tail) with `math.comb`; matches scipy's `binomtest` and a brute-force enumeration in the tests. |
| Paired bootstrap over questions | [`ab.py:60` `bootstrap_ci`](../eval/ab.py#L60) | Resamples the 66 questions with replacement (10,000, seed 0) and takes the linear 2.5th/97.5th percentiles of acc_B − acc_A, so the pairing is kept. |
| Power by simulation | [`ab.py:71` `power`](../eval/ab.py#L71), [`ab.py:91` `power_analysis`](../eval/ab.py#L91) | From arm A's accuracy: B fixes each wrong question with f and breaks each right one with g = 0.05; power = share of 10,000 simulations with B ahead and p < 0.05; the minimum detectable improvement at 80% (+14 points) was written down before arm B ran. |
| Randomization inference | [`did.py:258` `placebo`](../analysis/causal/did.py#L258), [`did.py:314`](../analysis/causal/did.py#L314) | Two-sided RI p = (1 + #{\|b_p\| ≥ \|b\|}) / (1 + N) over every placebo assignment; the pre-trend RI p uses the sum of squared pre-bin coefficients ([`did.py:332`](../analysis/causal/did.py#L332)). |
| Coverage simulation | [`synthetic.py:89` `study`](../analysis/causal/synthetic.py#L89) | 200 panels per scenario (null / moved / new) with AR(1) noise: bias, RMSE and coverage of the CR1 and placebo intervals. CR1 covers 0.79–0.83 with 3 treated clusters, the placebo intervals 0.925–0.965. |

---

## ✅ Bay Wheels ingest + cleaning (local and BigQuery)

**What it does:** finds, downloads and cleans Lyft's monthly Bay Wheels files (two schemas, irregular names) into
one Parquet dataset: 6.9M trips for 2019 + 2025, with every dropped row counted by reason.

| Concept | Where | How |
|---|---|---|
| Discovery, not templates | [`baywheels.py:91` `parse_listing`, `:106` `monthly_files`](../pipeline/baywheels.py#L91) | Parses the S3 ListObjects XML (paginated) and keys files by their `YYYYMM-` prefix, so typos (`baywheeels`), `.zip` vs `.csv.zip`, `lyftbikes` and missing months just work. |
| Idempotent downloads | [`baywheels.py:137` `download`](../pipeline/baywheels.py#L137) | Skips files whose ETag + size match the manifest; records sha256. |
| Untrusted archives | [`baywheels.py:169` `extract_csv`](../pipeline/baywheels.py#L169) | Extracts exactly one CSV by basename (no path traversal), skipping `__MACOSX/`. |
| Explicit schema + rejects | [`baywheels.py:260`](../pipeline/baywheels.py#L260) | DuckDB `read_csv` with all-VARCHAR columns from the (validated) header and `store_rejects`, so malformed lines are counted, not fatal. |
| Schema normalisation + drop reasons | [`baywheels.py:269`](../pipeline/baywheels.py#L269), [`:283`](../pipeline/baywheels.py#L283) | Legacy and Lyft rows map to one schema; a `CASE` gives each bad row one reason; `row_number()` de-duplicates on `ride_id`. |
| Partitioned output | [`baywheels.py:314`](../pipeline/baywheels.py#L314) | `COPY … TO` Parquet (zstd) per `year=/month=`, replacing only the months processed. |
| Tests | [`tests/test_baywheels.py`](../tests/test_baywheels.py) | Listing with irregular names + pagination, both schemas, every drop reason counted once. |

**Why DuckDB, not Spark:** 2–5M rows a year fits one machine, and DuckDB runs natively on Windows, CI and the ARM
VM without a JVM. BigQuery has 2018 → Sep 2026 (loaded by the VM); locally the default is 2019 and 2025
(`tasks.py baywheels --years …` for more).

---

## ✅ Data API over the warehouse

**What it does:** serves the site's numbers from the dbt marts, from either the local DuckDB file or BigQuery,
with the same SQL.

| Concept | Where | How |
|---|---|---|
| One interface, two backends | [`warehouse.py:57` `Warehouse`, `:66` DuckDB, `:153` BigQuery](../api/warehouse.py#L57) | `query(sql, params)` and `table(name)`. Endpoint SQL is dialect-neutral; anything dialect-specific lives in dbt. |
| Short-lived DuckDB connections | [`warehouse.py:77`](../api/warehouse.py#L77) | Read-only, opened and closed per query, so the API doesn't hold the file lock that blocks dbt on Windows. |
| Typed BigQuery parameters + cost cap | [`warehouse.py:179-182`](../api/warehouse.py#L179) | `ScalarQueryParameter` with INT64/DATE/… types (BigQuery won't compare INT64 to strings) and a 100 MB `maximum_bytes_billed`. |
| TTL cache | [`cache.py:18`](../api/cache.py#L18) | `time.monotonic` expiry per warehouse + endpoint + arguments; failures aren't stored. |
| Endpoints | [`data.py:74` `_kpis`, `:254` summary, `:331` forecast](../api/routes/data.py#L74) | KPI windows computed by date; the peak-share baseline matches (ISO year, ISO week) pairs in Python ([`:114`](../api/routes/data.py#L114)); 503 without a warehouse; 404 codes for unknown stations or missing forecasts. |
| Two schemas, one endpoint | [`data.py:301` `_interval`](../api/routes/data.py#L301) | The forecast endpoint reads `select *` and serves either run-log schema: the calibrated band when it exists and came closer to 80% than the raw one, else p10/p90, with `model.interval` saying which. |
| Data-driven wording | [`forecast.js:63` `rangeLabel`, `:119` `forecastCaption`, `:134` `sourceLine`](../web/js/forecast.js#L63) | "80% range" only when calibrated and within 5 points of 80%, "calibrated model range" when calibrated but off target, the 10th–90th percentile only when uncalibrated; the caption has the year; the source line gives the window and says "narrower"/"wider" only when coverage is below 75% / above 85%. |
| Tests | [`tests/test_api_data.py`](../tests/test_api_data.py), [`tests/local/test_local_warehouse.py`](../tests/local/test_local_warehouse.py) | A fixture DuckDB built in `tmp_path`, a fake BigQuery client, and checks that the API equals direct mart queries on the real file. |

---

## ✅ #19 Agents and tool use (local, and live on Cloud Run)

**What it does:** "Ask TransitPulse" answers a ridership question by writing one guarded SQL query over the published
marts, running it and summarising the rows, streamed to the site as Server-Sent Events. Off unless
`TP_AGENT_ENABLED=true`; the LLM is a deterministic fake (tests), llama3.1:8b via Ollama (local) or Gemini.

| Concept | Where | How |
|---|---|---|
| LangGraph state machine | [`graph.py:138` `build_graph`](../api/agent/graph.py#L138) | `route` → `refuse` / `forecast` / `generate` → `execute` → `answer`, with a conditional edge back to `generate` for **one** repair attempt carrying the error; a second failure raises an `error` event. |
| Streaming progress | [`graph.py:145` `run`, `:292` `run_agent`](../api/agent/graph.py#L145) | Nodes emit `(event, payload)` through LangGraph's custom stream writer; `run_agent` guarantees the stream ends with exactly one answer / refusal / error. |
| SSE endpoint | [`ask.py:68` `admit`, `:95` `ask`](../api/routes/ask.py#L68) | A FastAPI dependency does the 503 / rate-limit / budget checks so they're real HTTP statuses before streaming; the handler yields `fastapi.sse.ServerSentEvent`s. |
| SQL guardrails | [`guardrails.py:136` `check_sql`](../api/agent/guardrails.py#L136) | sqlglot AST: one SELECT, no DML/DDL/INTO, table allowlist (CTE-aware), no file readers or table functions, LIMIT added/clamped, transpiled BigQuery → DuckDB and qualified for the target. |
| Defence in depth | [`warehouse.py:94` `agent_connection`, `:195` BigQuery dry run](../api/warehouse.py#L94) | DuckDB: read-only, `enable_external_access=false`, locked config, `EXPLAIN` + interrupt timeout. BigQuery: a free dry run refuses > 1 GB, then `maximum_bytes_billed` = 1 GB and `job_timeout_ms` (cancelled on a client-side timeout); a per-process daily byte budget. |
| Rate limiting behind a proxy | [`ask.py:29` `RateLimiter`, `:58` `client_ip`](../api/routes/ask.py#L29) | Sliding one-minute window per IP; above 10,000 IPs, idle ones are forgotten; `X-Forwarded-For` is read (right-most entry) only when `TP_TRUST_PROXY=true`, since otherwise it's client-controlled. |
| Swappable LLMs + test double | [`llm.py:134` `make_llm`, `:80` `FakeLLM`](../api/agent/llm.py#L134) | One `complete(prompt)` interface over ChatOllama / ChatGoogleGenerativeAI; the fake is scripted per question (incl. failing first attempts) so graph tests are deterministic and offline. |
| Execution-accuracy eval | [`eval/questions.yaml`](../eval/questions.yaml), [`scoring.py:66` `execution_match`](../eval/scoring.py#L66), [`run_eval.py:70` `evaluate`](../eval/run_eval.py#L70) | 66 gold-SQL questions + 10 refusals; rows compared as multisets (ordered for top-N), column-permutation-insensitive, floats at 1e-4. The gold SQL itself passes the guardrails and runs on the CI fixture and the real warehouse. |
| Streaming client | [`ask.js:69` `createEventParser`](../web/js/ask.js#L69) | Spec-compliant SSE parsing (LF/CRLF/CR, multi-line data, comments, split chunks) and distinct messages for 4xx, 5xx, dropped streams and streams that end without an answer. |
| Tests | [`test_agent_guardrails.py`](../tests/test_agent_guardrails.py), [`test_agent_graph.py`](../tests/test_agent_graph.py), [`test_ask_api.py`](../tests/test_ask_api.py), [`test_agent_eval.py`](../tests/test_agent_eval.py), [`ask.test.mjs`](../tests/web/ask.test.mjs), [`ask.spec.js`](../tests/web/ask.spec.js) | Every rejection path, the repair loop, refusals, forecast tool, SSE wire format parsed like the browser, rate limit and proxy trust, byte budget, scoring rules, mocked streams in Chromium. |

**Honest limits:** llama3.1:8b scores **0.50** execution accuracy (33/66) with 5 retrieved examples and **0.27**
(18/66) without, and 1.0 refusal accuracy, on the local DuckDB; it still often picks the wrong table or adds/omits
a column. The live agent runs Gemini (since 2026-10-16), which hasn't been A/B-tested.

---

## 🟡 #3 Load and latency testing (local)

**What it does:** [`load/locustfile.py`](../load/locustfile.py) models a site visitor ([:40](../load/locustfile.py#L40)):
KPIs and forecasts 3:3, and a question 1 in 7 (an SQL question or an off-topic one). The question is posted to
`/api/ask`, and the SSE stream is parsed and must end in `answer` or `refusal`, otherwise the request counts as
failed ([:60](../load/locustfile.py#L60)). Each user hits every endpoint once on start.
[`load/run_local.py`](../load/run_local.py) does the rest:
- builds the dbt fixture warehouse in a child process ([:57](../load/run_local.py#L57))
- starts uvicorn with the fake LLM and the per-IP rate limit lifted ([:82](../load/run_local.py#L82))
- runs Locust headless at 1/10/25 users and reads its CSV percentiles ([:119](../load/run_local.py#L119))
- stops the server, prints p50/p95/p99, RPS and failures per endpoint, and exits non-zero on any failure

Results are in the README (25 users: ~30 req/s, forecast p95 14 ms, ask p95 140 ms, 0 failures).

Cloud Run itself: cold start about 4.4 s, warm requests 0.09–0.17 s (2026-10-15). **Missing:** a Locust run against
Cloud Run (owner step 11).

---

## ✅ Policy analysis: BART station closures (added 2026-10-17)

**What it does:** checks the 15 stations BART staff named in February 2026 (if the Nov 3 measure fails) against the
ridership data, gives each a "case to keep" verdict from four stated rules, and lets a visitor close them on the live
map. It takes no position on the measure. Write-up with the results, claim checks and 13 sources:
[`STATION_CLOSURES.md`](STATION_CLOSURES.md).

| Concept | Where | How |
|---|---|---|
| The list as data | [`bart_closure_candidates.csv`](../dbt/transitpulse/seeds/bart_closure_candidates.csv) | A dbt seed: station, group (the first 10 or the next 5) and the segment it sits on. |
| Marts | [`mart_station_closures.sql`](../dbt/transitpulse/models/marts/mart_station_closures.sql), [`mart_closure_destinations.sql`](../dbt/transitpulse/models/marts/mart_closure_destinations.sql), [`mart_closure_scenarios.sql`](../dbt/transitpulse/models/marts/mart_closure_scenarios.sql) | Per station: 2025 weekday trips, rank from the fewest, recovery vs 2019, distance to the nearest open station, change on the year; top 3 destinations; each scenario's share of weekday trips. Data tests on all three. |
| Rules and verdicts | [`data.py:416` `CLOSURE_RULES`, `:461` `closure_criteria`](../api/routes/data.py#L416) | Four rules on the rounded numbers the page shows (riders, recovery, distance, growing); 3–4 met = strong, 2 = mixed, 0–1 = weak. `GET /api/closures` is cached for an hour. |
| The band | [`closures.js:174` `initClosures`](../web/js/closures.js#L174) | Summary tiles, the cost card, one card per station; every number from the API, strings escaped. |
| What-if map | [`schedule.js:71` `closedStops`, `:62` `tripPosition`](../web/js/map/schedule.js#L62), [`whatif.js:51`](../web/js/map/whatif.js#L51) | Closed stations lose their marker; each trip keeps its times at open stations and runs through closed ones, the time between two open stops spread over the hops by their scheduled running times. Termini are never skipped. |
| Tests | [`test_api_closures.py`](../tests/test_api_closures.py), [`test_closures_local.py`](../tests/local/test_closures_local.py), [`closures.spec.js`](../tests/web/closures.spec.js), [`whatif.test.mjs`](../tests/web/whatif.test.mjs), [`schedule.test.mjs`](../tests/web/schedule.test.mjs) | Rule edges and rounding, the numbers against the warehouse, the band in a browser, the picker's list equal to the seed, and on the real timetable no train dwelling at a closed station. |

---

## ⬜ Not started (planned milestone)
| # | Skill | Milestone | Planned location |
|---|---|---|---|
| 9 | BI dashboards (Looker Studio, Power BI + DAX) | M2 | `bi/` (the build guide, DAX and check week are written; the reports need the owner's accounts) |
| 16 | Fine-tuning (QLoRA) | M6 | `ml/finetune/` |
