# TransitPulse

A Bay Area transit analytics platform: BART and Bay Wheels ridership pipelines (Dagster + PySpark + dbt on BigQuery),
station forecasts, a causal study of the eBART extension, an AI analyst agent that answers questions with SQL, and a
responsive website with a live map of scheduled BART trains.

> **Status (2026-10-14):** live. The site is at **[braedynthompson.com/transitpulse](https://braedynthompson.com/transitpulse/)**,
> the API on Cloud Run, and the pipeline runs itself on an Oracle VM. What's left is under [Left to do](#left-to-do).
> How each part works today: [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md).

## Progress
| Milestone | Status |
|---|---|
| M0 setup (GCP, Terraform, repo) | ✅ Done |
| M1 data platform (Dagster, PySpark, dbt, BigQuery) | ✅ Done. Runs itself on the VM: BART is checked every 6 hours and reloaded when it changes, then dbt rebuilds |
| M2 KPIs + BI | 🟡 KPIs done (`mart_kpis_daily`, on the site). Looker Studio and Power BI not started |
| M3 forecasting (LightGBM) | ✅ Done. Beats the baseline; retrains every Monday |
| M4 eBART causal study | ✅ Done. Live in the site's Findings band |
| M5 AI analyst agent + eval | 🟡 Agent and eval set built (27% execution accuracy locally). A/B test not started; the agent is off on the live site |
| M6 QLoRA fine-tune | ⬜ Not started |
| M7 ship | 🟡 Live, and every push to `main` deploys itself. Architecture diagram, screenshots, `make up` and dbt/Terraform checks in CI left |
| F1–F7 website | 🟡 Built and live (map, trends, forecast explorer, Findings, Ask). Style guide, Lighthouse/axe audits, Open Graph image and real-device checks left |

## Results
| What | Number |
|---|---|
| BART ridership in BigQuery | 67,770,440 hourly origin-destination rows, 2018–2025, 4.2 GB |
| Bay Wheels trips | 25,989,969 trips, 2018 → Sep 2026 |
| Forecast (14-day, per station, 6 walk-forward folds) | MAE **283.1** vs **548.5** for the seasonal-naive baseline; improvement 265.4 entries/day, 95% CI [199.6, 339.9]. The p10–p90 band holds 73% of days (nominal 80%), so the site calls it the "model range" |
| Ask agent (llama3.1:8b, local) | Execution accuracy **0.27** (18/66 gold-SQL questions), refusal accuracy 1.0 (10 off-topic questions), p50 2.4 s |
| eBART study | See [Findings](#findings-the-ebart-causal-study) below |
| Cloud Run | Cold start about **4.4 s** to the first byte; warm requests 0.09–0.17 s (measured 2026-10-15) |

## Run locally

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). On Windows there is no `make`; use `uv run python tasks.py <task>`.

```sh
uv sync                                  # install
uv run python tasks.py api               # site + API on http://localhost:8000 (map data is committed)
uv run python tasks.py test              # Python + browser-maths unit tests
npm ci && npx playwright install chromium && npx playwright test   # browser tests
```

Data pipeline, fully local (no cloud account needed; Spark runs in Docker on Windows):

```sh
uv sync --group pipeline --group dbt --group spark
uv run python tasks.py dagster           # Dagster UI on http://localhost:3000: materialize assets / backfill years
# or step by step:
uv run python tasks.py web-data          # GTFS -> web/data/*.json
uv run python tasks.py stations          # GTFS -> station list for the SCD2 snapshot
uv run python tasks.py spark             # data/raw/bart_od/*.csv.gz -> partitioned Parquet
uv run python tasks.py baywheels         # Bay Wheels 2019 + 2025: download (~250 MB) + clean -> Parquet
uv run python tasks.py dbt               # dbt build on DuckDB (data/transitpulse.duckdb)
uv run python tasks.py forecast          # 14-day station forecast (LightGBM + calibrated band) -> marts.forecast_station_daily
uv run python tasks.py eval --llm ollama # score the Ask agent on eval/questions.yaml (needs Ollama + llama3.1:8b)
```

The Ask card's agent is off by default (the site says it isn't connected). To try it locally:
`TP_AGENT_ENABLED=true TP_AGENT_LLM=ollama uv run --group agent python tasks.py api` (`TP_AGENT_LLM=fake` needs no
model and answers a few canned queries).

With `data/transitpulse.duckdb` built, `uv run python tasks.py api` serves real numbers on the site
(it sets `TP_WAREHOUSE=duckdb`; set `TP_WAREHOUSE=bigquery` + `TP_GCP_PROJECT` to read BigQuery instead).
Checks on the real local data: `uv run --group dbt --group ml --group agent pytest -m localdata tests/local`.

The production pipeline runs on the Oracle VM ([`docs/ORACLE_VM.md`](docs/ORACLE_VM.md)), and every automation
starts on by default:
- BART is checked every 6 hours and reloaded when its file changes; dbt rebuilds after every ingest.
- Bay Wheels reloads on the 7th of each month.
- A full model rebuild runs on the 6th.
- The forecast retrains every Monday.

After changing pipeline code, update the VM with `sudo bash /opt/transitpulse/deploy/oracle/bootstrap.sh`. Wait for
running jobs to finish first: the restart kills them.

## Findings: the eBART causal study

Did the 2018 eBART extension to Antioch bring new riders, or just move them between stations? This is a
pre-registered difference-in-differences study against 34 BART stations far from the line, with 95% placebo
intervals. It uses weekly data from 2018 to Feb 2020 and monthly data from 2016. The write-up is
[`docs/FINDINGS.md`](docs/FINDINGS.md), served on the site from `GET /api/findings`.

| Estimate | Effect | 95% placebo interval |
|---|---|---|
| Whole line, Concord → Antioch (incl. new stations) | **+4.2%** (about 500 entries a day) | +1.6% to +7.1% |
| Pittsburg/Bay Point, North Concord, Concord | **−23.9%** | −25.8% to −21.8% |
| Rest of the yellow line (spillover check) | +0.5% | −1.7% to +3.0% |

- **Verdict (pre-registered rule): new.** Most riders at the new stations moved from the old ones; the line as a
  whole is consistent with a small net gain, not a firm finding.
- **Caveats.** The gain fades after the first year. The longer monthly series also shows the corridor already
  rising against the controls before the opening, so part of the +4.2% may be trend.

```sh
uv run python tasks.py causal            # recompute api/data/findings.json + docs/img/ plots from the committed CSVs
```

## Deploy (Cloud Run) and load test

The site and API ship as one container ([`Dockerfile`](Dockerfile): multi-stage, non-root, **119 MB compressed**, so
the 3 images Artifact Registry keeps fit its 0.5 GB free tier). Terraform for the service and for GitHub's keyless
Workload Identity Federation is in [`infra/terraform/`](infra/terraform/). [`deploy.yml`](.github/workflows/deploy.yml)
builds, pushes and deploys on every push to `main`. All of it is applied and switched on (`DEPLOY_ENABLED=true`);
the steps are in [`docs/CLOUD_RUN.md`](docs/CLOUD_RUN.md).

```sh
uv run python tasks.py image             # docker build + container smoke tests (tests/deploy)
uv run python tasks.py load              # Locust, 1/10/25 users, on a fixture warehouse with the fake LLM
```

Local load test (this PC, a 3-station DuckDB fixture, fake LLM, 20 s per step, 0 failures). These are not Cloud Run
numbers:

| Users | Requests/s | `/api/forecast` p50 / p95 / p99 | `/api/kpis` p50 / p95 / p99 | `/api/ask` p50 / p95 / p99 |
|---|---|---|---|---|
| 1 | 1.2 | 54 / 62 / 62 ms | 5 / 540 / 540 ms | 42 / 870 / 870 ms |
| 10 | 11.8 | 4 / 8 / 17 ms | 4 / 11 / 17 ms | 43 / 58 / 58 ms |
| 25 | 29.7 | 5 / 14 / 30 ms | 4 / 22 / 29 ms | 37 / 140 / 140 ms |

The slow 1-user p95s are the first requests, before the API's cache and the agent graph are warm. The container
starts in about 1.5 s locally and uses about 76 MiB of its 512 MiB. On Cloud Run, the first request after scaling to
zero takes about 4.4 s; warm requests take 0.09–0.17 s. A Locust run against Cloud Run hasn't been done yet.

## Docs
| File | What it is |
|---|---|
| [`docs/TRANSITPULSE_PLAN.md`](docs/TRANSITPULSE_PLAN.md) | Goals, stack and the skills this project demonstrates |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Ordered build checklist (M0–M7, F1–F7) |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Design system (frozen v1.0) |
| [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) | How the application works right now |
| [`docs/DEVLOG.md`](docs/DEVLOG.md) | Running log of changes and decisions |
| [`docs/SKILLS_MAP.md`](docs/SKILLS_MAP.md) | Where each skill is implemented, and how it works |
| [`docs/METRICS.md`](docs/METRICS.md) | KPI definitions, the website tile windows, bikes vs trains, forecast coverage, agent eval, causal estimates |
| [`docs/FINDINGS.md`](docs/FINDINGS.md) | The eBART causal study: pre-registration, design, results, limitations |
| [`docs/ORACLE_VM.md`](docs/ORACLE_VM.md) | Runbook: Dagster on the Oracle VM (systemd) |
| [`docs/CLOUD_RUN.md`](docs/CLOUD_RUN.md) | Runbook: the site + API on Cloud Run (Terraform, WIF, deploy workflow, costs) |

## Data sources and licences
| Data | Source | Licence / terms |
|---|---|---|
| BART GTFS schedule | bart.gov → Developers → GTFS | BART developer license agreement (attribution: "Data provided by BART") |
| BART hourly origin-destination ridership | bart.gov → About → Reports → Ridership | Public BART data; same developer terms |
| BART monthly ridership reports (2016–2020, eBART study) | bart.gov → About → Reports → Ridership (`ridership_YYYY.zip`) | Public BART data; same developer terms (derived station-month averages committed in `analysis/causal/data/`) |
| Bay Wheels trip data | [Lyft Bay Wheels System Data](https://www.lyft.com/bikes/bay-wheels/system-data) (bucket `s3.amazonaws.com/baywheels-data`) | [Bay Wheels Data License Agreement](https://baywheels-assets.s3.amazonaws.com/data-license-agreement.html) (verified 2026-10-08) |
| Bay Area coastline | Natural Earth | Public domain |

BART's terms were checked on 2026-10-14. They allow the derived data with attribution, and "Data provided by BART"
appears in `analysis/causal/data/README.md`, `docs/FINDINGS.md`, the Findings band and the site footer.

## Left to do
Ordered by what finishes the project soonest (see [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) §6,
"Definition of done").

**Code (no accounts needed)**
1. **M5 A/B test.** Power analysis, then arm A (schema card) vs arm B (schema card + 5 retrieved example queries),
   with McNemar and a bootstrap CI, written up in `docs/AB_TEST.md`. At 27% accuracy, the few-shot arm is the
   obvious next try.
2. **Website gaps.**
   - Keep the last 5 Q&As across a refresh (`sessionStorage`) and add a copy button for answers.
   - Clicking a station on the map selects it in the forecast explorer.
   - Name the busiest station in the map's text alternative.
3. **Polish (F1/F7).**
   - `web/styleguide.html` and a design review against `DESIGN.md`.
   - A Lighthouse mobile audit (≥ 90 / 95 / 95) and an axe contrast check in Playwright.
   - An Open Graph image.
4. **README.** An architecture diagram and screenshots at phone and desktop width.
5. **`make up`.** One command that starts API + web + Ollama from a fresh clone.
6. **M6 QLoRA fine-tune.** 1–3K question→SQL pairs, QLoRA of Qwen2.5-Coder-1.5B on the RTX 4060, GGUF → Ollama, then
   scored as arm C in `docs/AB_TEST.md`.
7. **Optional eBART trend-adjusted estimate.** Extrapolate the monthly pre-period trend (about 0.27 pts/month), which
   could absorb most of the +4.2%. It wasn't pre-registered, so label it that way and report it next to the
   pre-registered result.

**Needs you (accounts, GUI tools or devices)**
1. **Turn on the live agent.** Add a Gemini API key to Secret Manager and apply Terraform with `agent_enabled=true`
   ([`docs/CLOUD_RUN.md`](docs/CLOUD_RUN.md) §4). Then the 10 sample questions on the live site need checking on a phone.
2. **M2 BI.** A public Looker Studio dashboard on the marts, then a Power BI report (`.pbix`, PDF, screenshots) whose
   KPIs match dbt for one chosen week. After that, embed the dashboard on the site.
3. **dbt build + `terraform plan` in CI.** These need a read-only GCP identity for CI, an IAM change that needs
   owner rights.
4. **Real-device check.** iPhone Safari, Android Chrome, a tablet in both orientations, desktop at 125% and 200% zoom.
5. **Month-end GCP bill.** Confirm it is $0 in the billing console.
