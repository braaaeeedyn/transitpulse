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
    run("uv", "run", "pytest", "-m", "not spark and not gcp")
    run("node", "--test", "tests/web/")


def web_data(*args: str) -> None:
    """Build web/data/*.json from the BART GTFS feed (downloads it unless --gtfs PATH is given)."""
    run("uv", "run", "python", "-m", "pipeline.webdata.build", *args)


def api() -> None:
    """Serve the API and the static site on http://localhost:8000."""
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
    run("uv", "run", "--group", "pipeline", "--group", "dbt", "dagster", "dev", "-m", "pipeline.definitions")


TASKS = {
    "lint": lint,
    "fmt": fmt,
    "test": test,
    "web-data": web_data,
    "api": api,
    "web-test": web_test,
    "spark": spark,
    "stations": stations,
    "dbt": dbt,
    "dagster": dagster,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print("tasks:", ", ".join(TASKS))
        sys.exit(1)
    TASKS[sys.argv[1]](*sys.argv[2:])
