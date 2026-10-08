# TransitPulse

A Bay Area transit analytics platform: BART and Bay Wheels ridership pipelines (Dagster + PySpark + dbt on BigQuery),
station forecasts, a causal study of the eBART extension, an AI analyst agent that answers questions with SQL, and a
responsive website with a live map of scheduled BART trains.

> **Status:** in development. See [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) for what works today.

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
uv run python tasks.py forecast          # 14-day station forecast (LightGBM) -> marts.forecast_station_daily
```

With `data/transitpulse.duckdb` built, `uv run python tasks.py api` serves real numbers on the site
(it sets `TP_WAREHOUSE=duckdb`; set `TP_WAREHOUSE=bigquery` + `TP_GCP_PROJECT` to read BigQuery instead).
Checks on the real local data: `uv run --group dbt --group ml pytest -m localdata tests/local`.

Running the scheduled pipeline on the Oracle VM: [`docs/ORACLE_VM.md`](docs/ORACLE_VM.md).

## Docs
| File | What it is |
|---|---|
| [`docs/TRANSITPULSE_PLAN.md`](docs/TRANSITPULSE_PLAN.md) | Goals, stack and the skills this project demonstrates |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Ordered build checklist (M0–M7, F1–F7) |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Design system (frozen v1.0) |
| [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) | How the application works right now |
| [`docs/DEVLOG.md`](docs/DEVLOG.md) | Running log of changes and decisions |
| [`docs/SKILLS_MAP.md`](docs/SKILLS_MAP.md) | Where each skill is implemented, and how it works |
| [`docs/METRICS.md`](docs/METRICS.md) | KPI definitions, the website tile windows, bikes vs trains |
| [`docs/ORACLE_VM.md`](docs/ORACLE_VM.md) | Runbook: Dagster on the Oracle VM (systemd) |

## Data sources and licences
| Data | Source | Licence / terms |
|---|---|---|
| BART GTFS schedule | bart.gov → Developers → GTFS | BART developer license agreement (attribution: "Data provided by BART") |
| BART hourly origin-destination ridership | bart.gov → About → Reports → Ridership | Public BART data; same developer terms |
| Bay Wheels trip data | [Lyft Bay Wheels System Data](https://www.lyft.com/bikes/bay-wheels/system-data) (bucket `s3.amazonaws.com/baywheels-data`) | [Bay Wheels Data License Agreement](https://baywheels-assets.s3.amazonaws.com/data-license-agreement.html) (verified 2026-10-08) |
| Bay Area coastline | Natural Earth | Public domain |

*(Verify each licence before publishing; see `docs/IMPLEMENTATION_PLAN.md` M0.)*
