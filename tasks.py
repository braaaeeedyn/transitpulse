"""Cross-platform task runner (Windows has no `make`). The Makefile forwards here.

Usage: uv run python tasks.py <task> [args...]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def run(*cmd: str) -> None:
    print("$", " ".join(cmd), flush=True)
    code = subprocess.call(list(cmd), cwd=ROOT)
    if code:
        sys.exit(code)


def lint() -> None:
    run("uv", "run", "ruff", "check", ".")
    run("uv", "run", "ruff", "format", "--check", ".")


def fmt() -> None:
    run("uv", "run", "ruff", "format", ".")
    run("uv", "run", "ruff", "check", "--fix", ".")


def test() -> None:
    run("uv", "run", "--group", "dbt", "--group", "ml", "--group", "pipeline", "--group", "agent",
        "pytest", "-m", "not spark and not gcp and not localdata and not docker")  # fmt: skip
    run("node", "--test", "tests/web/")


def web_data(*args: str) -> None:
    """Build web/data/*.json from the BART GTFS feed (downloads it unless --gtfs PATH is given)."""
    run("uv", "run", "python", "-m", "pipeline.webdata.build", *args)


def api() -> None:
    """Serve the API and the static site on http://localhost:8000.

    Reads the local warehouse (data/transitpulse.duckdb) when it exists, unless TP_WAREHOUSE says otherwise.
    The API itself never guesses: without TP_WAREHOUSE (or TP_GCP_PROJECT) its data endpoints answer 503.
    """
    if (ROOT / "data" / "transitpulse.duckdb").exists() and not os.environ.get("TP_GCP_PROJECT"):
        os.environ.setdefault("TP_WAREHOUSE", "duckdb")
    run("uv", "run", "uvicorn", "api.main:app", "--reload", "--port", "8000")


def web_test() -> None:
    run("npx", "playwright", "test")


SPARK_DEFAULT_ARGS = (
    "--input", "data/raw/bart_od/*.csv.gz",
    "--output", "data/parquet/bart_od",
    "--audit", "data/parquet/ingest_audit",
)  # fmt: skip


def spark(*args: str) -> None:
    """Clean raw OD files into Parquet. On Windows this runs in Docker (Spark 3.5 needs Linux + Java 17)."""
    args = args or SPARK_DEFAULT_ARGS
    if sys.platform == "win32":
        run("docker", "build", "-q", "-t", "transitpulse-spark", "-f", "pipeline/spark/Dockerfile", ".")
        run("docker", "run", "--rm", "-v", f"{ROOT}:/app", "transitpulse-spark",
            "python", "-m", "pipeline.spark.clean_bart_od", *args)  # fmt: skip
    else:
        run("uv", "run", "--group", "spark", "python", "-m", "pipeline.spark.clean_bart_od", *args)


def stations(*args: str) -> None:
    """Write the GTFS station list for dbt's SCD2 snapshot (data/parquet/bart_stations/)."""
    run("uv", "run", "python", "-m", "pipeline.stations", *args)


def baywheels(*args: str) -> None:
    """Download + clean Bay Wheels trips into data/parquet/baywheels_trips (default: the two local years)."""
    run("uv", "run", "python", "-m", "pipeline.baywheels", *(args or ("--years", "2019", "2025")))


def dbt(*args: str) -> None:
    run(
        "uv",
        "run",
        "--group",
        "dbt",
        "dbt",
        *(args or ("build",)),
        "--project-dir",
        "dbt/transitpulse",
        "--profiles-dir",
        "dbt/transitpulse",
    )


def dagster() -> None:
    """Dagster UI on http://localhost:3000 (assets, schedules, backfills)."""
    home = ROOT / ".dagster_home"
    home.mkdir(exist_ok=True)
    # instance settings (run queue limits) live in the repo; copied in on every start so edits take effect
    (home / "dagster.yaml").write_text((ROOT / "pipeline" / "dagster.yaml").read_text())
    os.environ.setdefault("DAGSTER_HOME", str(home))
    if sys.platform == "win32":
        os.environ.setdefault("TP_SPARK_RUNNER", "docker")
    run("uv", "run", "--group", "pipeline", "--group", "dbt", "--group", "ml",
        "dagster", "dev", "-m", "pipeline.definitions")  # fmt: skip


def forecast(*args: str) -> None:
    """Train, validate and publish the 14-day station forecast (local DuckDB unless TP_WAREHOUSE=bigquery)."""
    run("uv", "run", "--group", "ml", "python", "-m", "ml.forecast.run", *args)


def eval_agent(*args: str) -> None:
    """Score Ask TransitPulse on eval/questions.yaml (default: fake LLM on the local DuckDB; --llm ollama for real)."""
    run("uv", "run", "--group", "agent", "python", "-m", "eval.run_eval", *args)


def load(*args: str) -> None:
    """Locust load test on a fixture warehouse with the fake LLM (1/10/25 users unless --users N)."""
    run("uv", "run", "--group", "load", "--group", "agent", "python", "load/run_local.py", *args)


def image() -> None:
    """Build the Cloud Run image and run its smoke tests (tests/deploy). Builds locally only; pushes nothing."""
    run("docker", "build", "-t", "transitpulse-api:loop", ".")
    run("uv", "run", "pytest", "-m", "docker", "tests/deploy")


TASKS = {
    "lint": lint,
    "fmt": fmt,
    "test": test,
    "web-data": web_data,
    "api": api,
    "web-test": web_test,
    "spark": spark,
    "stations": stations,
    "baywheels": baywheels,
    "dbt": dbt,
    "dagster": dagster,
    "forecast": forecast,
    "eval": eval_agent,
    "load": load,
    "image": image,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print("tasks:", ", ".join(TASKS))
        sys.exit(1)
    TASKS[sys.argv[1]](*sys.argv[2:])
