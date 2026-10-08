# TransitPulse: project plan

> **Type:** brand-new project (new repo, e.g. `github.com/braaaeeedyn/transitpulse`)
> **One line:** a Bay Area transit analytics platform. It ingests years of BART and Bay Wheels ridership,
> models it in a cloud warehouse, forecasts it, explains a real policy question with causal inference, and
> lets anyone ask questions in plain English through an AI analyst agent.
> **Effort:** ~11–13 weeks part-time. **Cost target:** $0 (free tiers + your local GPU, with a budget alert as a safety net).

This is the **first** of the two planned projects, and it **introduces most of the new tools**. QuakeOps (the
SeismicSoCal upgrade) reuses Dagster, GitHub Actions and the statistics methods learned here, so each new skill
is only learned once. See [the overlap plan](#overlap-plan-with-quakeops).

---

## 1. What it does

### What a visitor sees
| Feature | Description |
|---|---|
| **Dashboard** | Looker Studio dashboard: ridership trends, busiest stations, rush-hour peaks, 2019 → today recovery, bikes vs. trains. |
| **Power BI report** | A deeper analyst report built on the same marts: DAX KPI measures, time intelligence (YoY, vs. 2019), a station drill-through page and a what-if scenario. Shared as the `.pbix` file in the repo plus a PDF export, screenshots and a short screen recording, because Power BI has no free public hosting. |
| **Forecasts** | Expected daily entries per BART station for the next 14 days, with prediction intervals. |
| **Ask TransitPulse** | An AI analyst agent. You ask *"Which stations grew most since 2022?"*; it writes **read-only SQL** against the warehouse, runs it, can call the forecast, and answers with a table/chart **plus the exact SQL it ran**. |
| **Findings write-up** | A causal analysis answering a real question (see §5.4), with method, assumptions, results and confidence intervals. |

### What runs behind the scenes
1. **Dagster** pulls new monthly ridership files on a schedule. A **PySpark** job cleans and de-duplicates the raw
   CSVs into partitioned **Parquet**, which is loaded into **Google Cloud Storage → BigQuery**.
2. **dbt** cleans and models the raw tables into a **star schema** and runs data tests.
3. A **LightGBM** forecasting job writes predictions back to BigQuery.
4. A **FastAPI** service (agent + forecast API) runs on **Cloud Run**, deployed by **GitHub Actions**, with all cloud resources defined in **Terraform**.
5. **Langfuse** traces every agent run; **Locust** measures latency under load.
6. A small open model is **fine-tuned with QLoRA** on question→SQL pairs and compared against the Gemini agent
   on the same evaluation set.

---

## 2. Gaps this project closes

Numbers refer to the 21-gap table from the skills review.

| # | Gap | How TransitPulse covers it |
|---|---|---|
| 1 | Cloud + Terraform | GCP (BigQuery, GCS, Cloud Run, Artifact Registry) all defined in Terraform |
| 2 | Advanced SQL | dbt models with window functions, CTEs, cohort and period-over-period queries |
| 3 | Load and latency testing | Locust test of the API, with p50/p95 latency reported |
| 4 | Larger datasets | Several years of hourly origin-destination data (multiple GB raw) |
| 5 | Monitoring (**LLM tracing part**) | Langfuse traces for every agent call: tokens, latency, tool calls, errors |
| 6 | A/B testing | Offline A/B test of two agent strategies, with a power analysis |
| 7 | Formal statistics | Bootstrap CIs, McNemar's test, CIs on the causal estimate |
| 8 | Business metrics | KPI definitions (recovery %, peak load, station share) on the dashboard |
| 9 | BI dashboards | Looker Studio dashboard on the dbt marts (live, public) **and** a Power BI report with a DAX data model (the most-requested BI tool in analyst postings) |
| 10 | Warehouse + dbt + modeling | BigQuery + dbt Core star schema, with station history tracked over time (SCD type 2) |
| 11 | Orchestration | Dagster assets and schedules (**learned here, reused in QuakeOps**) |
| 13 | CI/CD | GitHub Actions: lint, test, `dbt build`, Docker build, deploy (**learned here, reused in QuakeOps**) |
| 16 | Fine-tuning | **QLoRA** fine-tune of a small open code model for text-to-SQL, evaluated against Gemini as a third A/B arm |
| 17 | Spark / PySpark | **PySpark** job that turns the multi-GB raw OD files into clean, partitioned Parquet |
| 18 | Reproducible | `make` targets / one-command local run, documented, public evaluation set |
| 19 | Agents and tool use | LangGraph agent with SQL, forecast and chart tools |
| 21 | Causal inference | Difference-in-differences with event-study plots |

**Not covered, on purpose:**
- #12 MLflow (owned by QuakeOps)
- **#5 model drift monitoring** (owned by QuakeOps; TransitPulse only does *LLM* tracing)
- #14 Kubernetes, #15 distributed/multi-GPU training, #20 novel methods (too senior for internship targeting)

---

## 3. Stack: what is and isn't used

### ✅ Used

| Area | Tool | Free tier / notes |
|---|---|---|
| Language | **Python 3.12** | |
| Cloud | **Google Cloud Platform** | Billing account needed even for free-tier use. Set a **$1 budget alert** on day one. |
| Storage | **Google Cloud Storage** (raw files) | 5 GB-month free in `us-west1` / `us-central1` / `us-east1`. Use `us-west1`. |
| Warehouse | **BigQuery** | 10 GB storage + 1 TB queries/month free. Partition by date and cluster by station to keep scans small. |
| Transform | **dbt Core** + `dbt-bigquery` adapter | Free and open source. **Not** dbt Cloud. |
| Orchestration | **Dagster OSS** (`dagster`, `dagster-dbt`, `dagster-gcp`) | Runs on your existing **Oracle Always-Free A1 VM** (the SeismicSoCal box) under systemd. **Not** Dagster+ (the paid cloud). |
| Big-data processing | **PySpark** (Spark 3.5, **local mode**) | Runs on your PC (or the Oracle VM: 24 GB RAM is enough for local mode). Needs **Java 17**. **Not** Dataproc / Databricks / EMR (paid). |
| Forecasting | **LightGBM** (+ `pandas`, `scikit-learn`) | Baseline: seasonal-naive (same weekday last week). |
| Causal / stats | **statsmodels** (OLS with clustered SEs), **numpy** (bootstrap) | |
| Agent | **LangGraph** + `langchain-google-genai` | You know LangChain already; LangGraph is the agent layer on top. |
| LLM | **Gemini API (Google AI Studio free tier)**, a Flash-class model | Free but rate-limited. Free-tier prompts may be used by Google to improve products, so only send public transit data. **Local dev:** Ollama (`llama3.1:8b`) so you don't burn quota. |
| Fine-tuning | **Hugging Face** `transformers` + **PEFT** (LoRA) + **TRL** `SFTTrainer` + **bitsandbytes** (4-bit QLoRA) | Base model: a ~1.5B code/instruct model (e.g. **Qwen2.5-Coder-1.5B-Instruct**). Train on your **RTX 4060 (8 GB)**; **Google Colab's free T4** is the fallback. |
| Serving the fine-tuned model | **llama.cpp** GGUF conversion → **Ollama** (local) | Used for evaluation and a local demo only. The **deployed** agent keeps using Gemini (a CPU-only Cloud Run box would be too slow for a local model). |
| SQL guardrails | **sqlglot** (parse, allow `SELECT` only) + BigQuery **dry run** (reject queries scanning > 1 GB) + a **read-only service account** limited to the `marts` dataset | |
| API | **FastAPI** + Uvicorn | |
| Frontend | **Vanilla HTML/JS** (same style as BearLM) + embedded **Looker Studio** | No React here (nothing new to learn there). |
| Container | **Docker** → **Artifact Registry** | 0.5 GB free; delete old images. |
| Hosting | **Cloud Run** | Free tier: 2M requests/month; `min-instances = 0` (scales to zero). |
| IaC | **Terraform** (`hashicorp/google` provider), state in a GCS bucket | |
| CI/CD | **GitHub Actions** with **Workload Identity Federation** (no JSON keys in GitHub) | Free for public repos. |
| LLM tracing | **Langfuse Cloud** (Hobby plan) | Free tier with a monthly event cap. Self-hosting is the fallback. |
| Load testing | **Locust** | Run from your laptop against Cloud Run. |
| BI | **Looker Studio** | Free, connects straight to BigQuery. The live, public dashboard. |
| BI (analyst report) | **Power BI Desktop** | Free, Windows only. Native BigQuery connector; use **Import** mode on the small `marts` tables so each refresh scans them once (not DirectQuery). Publishing to the Power BI service needs a work/school account + licence, so it is **not** published online. |
| Lint/test | **ruff**, **pytest**, dbt tests | |

### ❌ Not used, and why
| Not used | Why |
|---|---|
| AWS / Azure | One cloud only. GCP has the most generous free warehouse (BigQuery). |
| Snowflake / Redshift / Databricks | Paid. BigQuery covers the warehouse skill. |
| dbt Cloud, Dagster+, Airflow, Prefect | Paid, or a second orchestrator to learn. Dagster OSS only. |
| MLflow, Evidently | Owned by QuakeOps, so they're learned once. |
| Kubernetes / GKE | Too heavy for the goal. Cloud Run covers deployment. |
| Paid LLM APIs (OpenAI, Anthropic) | Gemini free tier + local Ollama cover it at $0. |
| Dataproc / Databricks / EMR | Paid. PySpark runs free in local mode. |
| Tableau | Power BI covers the second BI tool and is asked for more often in analyst postings; one desktop BI tool is enough. Tableau Public (free, public hosting) is the fallback if a public interactive link matters more than DAX. |
| Power BI service / Fabric (paid, or needs a work account) | Desktop + the `.pbix` in the repo is enough to show the skill. |
| React / Next.js | No new front-end framework needed. |
| Paid GPU clouds (Lambda, RunPod, …) / OpenAI fine-tuning | Local GPU or free Colab covers a 1.5B QLoRA. |
| Large base models (7B+) | Won't fit 8 GB VRAM for training. A ~1.5B model is the right size for this task. |

---

## 4. Data sources (all public and free)

> Check each link and its licence before you start. Note the licence/attribution in the README.

| Dataset | Use | Where to get it |
|---|---|---|
| **BART hourly origin-destination ridership** (`date-hour-soo-dest-YYYY.csv.gz`) | Main fact table, multiple years | BART ridership reports page: bart.gov → About → Reports → Ridership (the OD files are linked from there) |
| **BART GTFS** | Station names, coordinates, lines | bart.gov → Schedules → Developers → GTFS |
| **Bay Wheels trip data** (monthly CSVs) | Bike trips for the bike-vs-train comparison | Lyft Bay Wheels "System Data" page (monthly files on S3) |
| **US federal holidays** | Forecast features | `holidays` Python package |

Keep raw files in GCS as-is, partitioned by year/month. Never edit raw data; all cleaning happens in dbt.

---

## 5. Build plan

### Phase 0: setup (week 0)
- [ ] New public repo `transitpulse`, Python 3.12, `uv` for dependencies, `ruff` + `pytest`.
- [ ] GCP project, **billing account with a $1 budget alert**, enable BigQuery / GCS / Run / Artifact Registry / IAM APIs.
- [ ] Terraform: GCS state bucket (create once by hand), then define the BigQuery datasets (`raw`, `staging`, `marts`, `ci`), GCS bucket, Artifact Registry repo, service accounts.

### Phase 1: data platform (weeks 1–3) · gaps #4 #10 #11 #2
- [ ] **Dagster assets:** `bart_od_files` downloads the yearly/monthly gzipped CSVs; likewise `baywheels_files` and `bart_stations`.
- [ ] **PySpark step** (gap #17), as a Dagster asset that runs `spark-submit` in local mode:
  - read all raw CSVs with an **explicit schema** (no inference)
  - clean: trim station codes, cast types, drop malformed rows and count them, **de-duplicate**
  - derive `trip_date`, `hour`, `weekday` and a holiday flag (broadcast join to a holidays table)
  - write **Parquet partitioned by year/month** to GCS
  - log row counts in vs. out and rows dropped per reason to a small `ingest_audit` table
  - Spark concepts to understand and explain: lazy evaluation, partitions, shuffles, `repartition` vs. `coalesce`, broadcast joins, reading the Spark UI
- [ ] Load the Parquet into `raw.bart_od` (partitioned by `trip_date`, clustered by `origin`) with a BigQuery load job.
- [ ] Monthly **schedule** + backfill partitions for historical years.
- [ ] **dbt** layers:
  - `stg_*`: typed, renamed, de-duplicated
  - `dim_station` (**SCD type 2** with dbt snapshots, so station renames and openings are tracked over time), `dim_date`
  - `fct_trips_hourly`, `fct_station_daily`
  - marts: `mart_recovery` (vs. same week 2019), `mart_peak_load`, `mart_od_flows`
- [ ] **Advanced SQL** you must use and be able to explain:
  - window functions (`LAG`, `SUM() OVER (PARTITION BY ... ORDER BY ...)`, `PERCENT_RANK`)
  - CTEs
  - period-over-period and cohort queries
  - `QUALIFY`
- [ ] dbt tests: `not_null`, `unique`, `relationships`, `accepted_values`, plus one custom test (e.g. "no negative ridership").
- [ ] Dagster runs on the **Oracle VM** (systemd unit, like `seismicsocal.service`), authenticated to GCP with a dedicated service account key kept in a gitignored file.
- ✅ **Checkpoint:** you can already show this for **Data Engineer** applications.

### Phase 2: dashboards + metrics (weeks 4–5) · gaps #8 #9
- [ ] Define 5–6 KPIs in a `METRICS.md`, each with a definition, formula and owner question. For example: *Recovery % = weekday entries ÷ same-week-2019 entries*.
- [ ] **Looker Studio** dashboard on the marts: trend, top/bottom stations, hour-of-day heatmap, bike vs. train. This is the live, public one.
- [ ] **Power BI report** (Power BI Desktop, `bi/transitpulse.pbix`):
  - **Get data → Google BigQuery**, **Import** mode, only the `marts` tables + `dim_station` / `dim_date` (keeps refresh scans tiny)
  - **Data model:** rebuild the star schema in the model view (one-to-many relationships, single filter direction), mark `dim_date` as the date table, hide raw key columns
  - **DAX measures** for every KPI in `METRICS.md`, so both dashboards agree on the numbers: `Total Entries`, `Recovery % vs 2019`, `YoY %` (`SAMEPERIODLASTYEAR`), `Rolling 28-day avg` (`DATESINPERIOD`), `Peak-hour share`, `Station rank` (`RANKX`)
  - **Pages:** executive summary (KPI cards + trend), station drill-through (right-click a station → its own page), hour × weekday heatmap (matrix with conditional formatting), bikes vs. trains
  - **Interactivity:** slicers, bookmarks for preset views, a **what-if parameter** (e.g. "if weekday recovery rises N points, how many extra daily riders?")
  - **Check:** pick 3 KPIs and confirm the DAX value equals the dbt mart value for the same period (write the comparison in `METRICS.md`)
  - **Ship:** commit the `.pbix`, export a PDF, add 3–4 screenshots and a 30–60 s screen recording to the README
- ✅ **Checkpoint:** shows **Data Analyst** skills, including the Power BI + DAX that analyst postings ask for most.

### Phase 3: forecasting (week 6) · supports #7
- [ ] Daily entries per station, 14-day horizon, **LightGBM** with lag, rolling, calendar and holiday features.
- [ ] **Walk-forward validation** (you already know this from Berkeley Lab) against a seasonal-naive baseline. Report MAE/RMSE with **bootstrap CIs**.
- [ ] Write predictions to `marts.forecast_station_daily` (Dagster asset, weekly).
- ❌ No MLflow here. Log metrics to a BigQuery table `ml.forecast_runs`. MLflow is learned in QuakeOps.

### Phase 4: causal analysis (week 7) · gaps #21 #7
- [ ] **Question (pick one, verify the dates):** *Did the eBART extension to Pittsburg Center & Antioch (opened 2018) change ridership at the nearby legacy stations, or just move riders between them?* It's pre-COVID, so it's a cleaner natural experiment than the 2020 openings.
- [ ] **Difference-in-differences:** treated = nearby stations, control = comparable stations elsewhere, with station and week fixed effects. Use **statsmodels** OLS with **SEs clustered by station**.
- [ ] **Event-study plot** to check pre-trends (parallel-trends assumption).
- [ ] Write-up: question → design → assumptions → result with 95% CI → limitations.

### Phase 5: the agent (weeks 8–9) · gaps #19 #5 #6 #7
- [ ] **LangGraph** graph:
  - **router:** decides whether the question needs SQL, a forecast, or is out of scope
  - **sql_tool:** generates SQL from a compact schema card of the `marts` tables, then applies the guardrails: `sqlglot` parse, `SELECT`-only, auto-`LIMIT`, BigQuery dry run ≤ 1 GB, read-only service account
  - **forecast_tool:** reads `forecast_station_daily`
  - **chart_tool:** returns a Vega-Lite spec
  - **answer:** cites the SQL it ran
- [ ] **Refuses** if the question isn't about the data, in the same spirit as BearLM's refusal behaviour.
- [ ] **Langfuse** callback on every run: traces, token counts, latency, tool errors.
- [ ] **Evaluation set:** 60–100 questions with **gold SQL**. Metric: *execution accuracy*, i.e. the agent's result equals the gold result.
- [ ] **Offline A/B test**, arm A = schema-card prompt vs. arm B = schema card + 5 retrieved example queries:
  - **power analysis** first: how many questions you need to detect a 10-point difference
  - **McNemar's test**, because each question is answered by both arms (paired)
  - **bootstrap CI** on the accuracy difference
  - write up the decision
- ✅ **Checkpoint:** shows **AI Engineer** and **Data Scientist** skills.

### Phase 6: fine-tune a small text-to-SQL model (week 10) · gap #16
- [ ] **Training data:** 1–3K question→SQL pairs for *your* `marts` schema:
  - generate candidates with templates + Gemini
  - **keep only pairs whose SQL runs and returns rows** (validated against BigQuery with the same guardrails)
  - **no overlap** with the evaluation set: hold the eval questions out by template, not just by wording
- [ ] **QLoRA** fine-tune of **Qwen2.5-Coder-1.5B-Instruct**:
  - TRL `SFTTrainer` + PEFT LoRA (r = 16) + 4-bit bitsandbytes
  - on the RTX 4060, or Colab's free T4 as a fallback
  - log loss curves and hyperparameters to a simple CSV/JSON in the repo (MLflow belongs to QuakeOps)
- [ ] Merge the adapter, convert to **GGUF** with llama.cpp, and run it in **Ollama**.
- [ ] Add it as **arm C** in the evaluation: execution accuracy, latency and cost vs. arms A/B (Gemini).
  - Same paired tests: McNemar's test and a bootstrap CI.
  - Report honestly, including if it loses to Gemini. A small specialised model being *close* at $0 and running locally is still a good result.

### Phase 7: ship it (weeks 11–12) · gaps #1 #13 #3 #18
- [ ] Dockerfile → **Artifact Registry** → **Cloud Run** (`min-instances=0`, `max-instances=2` to cap cost), all in **Terraform**.
- [ ] **GitHub Actions**:
  - On PR: ruff, pytest, `dbt build --target ci` on a small sample in the `ci` dataset, `terraform plan`
  - On merge to `main`: build and push the image, `terraform apply`, deploy
  - Auth via **Workload Identity Federation**: no service-account keys in GitHub
- [ ] **Locust** load test:
  - the forecast endpoint, plus the agent endpoint with the **LLM mocked**, so you measure your own code and don't burn quota
  - report p50/p95/p99 at 1, 10 and 25 concurrent users, and cold-start time
  - put the numbers in the README
- [ ] README: architecture diagram, one-command local run (`make up` with Docker Compose + Ollama), results, costs (target $0), limitations.

---

## 6. Skills you will be able to claim

**Data engineering:** Dagster, **PySpark**, dbt, BigQuery, Parquet, star schema / SCD2, data tests, partitioning and clustering.
**Analytics:** KPI design, Looker Studio, **Power BI (DAX measures, time intelligence, data modeling, drill-through)**, advanced SQL.
**Data science:** walk-forward forecasting, difference-in-differences, event studies, power analysis, McNemar, bootstrap CIs.
**AI engineering:** LangGraph tool-using agent, text-to-SQL with guardrails, **QLoRA fine-tuning** (Hugging Face PEFT/TRL), LLM evaluation sets, Langfuse tracing.
**Platform:** GCP, Terraform, Cloud Run, Docker, GitHub Actions CI/CD with Workload Identity Federation, Locust load testing.

Example résumé bullet (fill in your real numbers once you have them):
> Built TransitPulse, a Bay Area transit analytics platform: Dagster + PySpark + dbt pipelines over **N GB** of BART/Bay Wheels
> ridership in BigQuery, a LangGraph text-to-SQL agent with guardrails (**X% execution accuracy**, +Y pts vs. baseline
> via an offline A/B test, McNemar p = Z; a QLoRA-tuned 1.5B model reached **W%** locally at $0), and a
> difference-in-differences study of the eBART extension; deployed on
> Cloud Run with Terraform and GitHub Actions (p95 **N ms** at 25 concurrent users).

---

## 7. Overlap plan with QuakeOps

| Skill / tool | Learned in TransitPulse | Reused in QuakeOps |
|---|:-:|:-:|
| Dagster OSS on the Oracle VM | ✅ (new) | ✅ reuse for retraining and drift jobs |
| GitHub Actions CI/CD | ✅ (new) | ✅ reuse, adding model-promotion gates |
| Bootstrap CIs / statistical tests | ✅ (new) | ✅ reuse for model comparison |
| GCP, Terraform, BigQuery, dbt, Looker Studio, Power BI | ✅ | ❌ not used |
| LangGraph agent, Langfuse | ✅ | ❌ not used |
| Locust | ✅ | optional quick reuse |
| PySpark | ✅ (new) | ❌ not used |
| QLoRA fine-tuning (PEFT/TRL) | ✅ (new) | ❌ not used |
| MLflow, Evidently drift monitoring | ❌ | ✅ (new) |

## 8. Cost guardrails
- **$1 budget alert** on the billing account, plus a second alert at $5.
- BigQuery: always filter on the partition column; set `maximum_bytes_billed` in the dbt profile and in the agent's query config.
- Cloud Run: `max-instances=2`, scale to zero.
- Delete old Artifact Registry images (cleanup policy in Terraform).
- Gemini: free tier only. Never put billing on the AI Studio key.
- Spark runs locally (free); never start a managed Spark cluster.
- Fine-tuning runs on your GPU or free Colab; if Colab disconnects, save checkpoints to Google Drive every N steps.

## 9. Adding it to the portfolio
See `docs/PORTFOLIO_CONTEXT.md` → "Adding TransitPulse".
