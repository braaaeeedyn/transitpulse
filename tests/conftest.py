"""Shared fixtures."""

import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def fixture_warehouse(tmp_path_factory) -> Path:
    """The dbt fixture warehouse (tests/dbt_fixture_data.py), built once per session; the DuckDB file's path.

    Built in a child process: dbt-duckdb keeps its connection open in the process that ran it, and DuckDB refuses a
    second connection to the same file with a different configuration (the agent's locked-down read-only one)."""
    tmp = tmp_path_factory.mktemp("fixture_warehouse")
    code = "import sys; from dbt_fixture_data import build_fixture_warehouse; build_fixture_warehouse(__import__('pathlib').Path(sys.argv[1]))"
    out = subprocess.run(
        [sys.executable, "-c", code, str(tmp)], cwd=TESTS, capture_output=True, text=True, timeout=600
    )
    assert out.returncode == 0, (out.stdout + out.stderr)[-4000:]
    return tmp / "fixture.duckdb"
