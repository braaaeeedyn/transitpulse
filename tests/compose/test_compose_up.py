"""`make up` smoke test (marker `docker`): builds and starts only the `api` service of docker-compose.yml, with the
fake LLM and no Ollama (`--no-deps`, so nothing is downloaded), on port 8814 under its own compose project, and
always takes it down again. Like `tasks.py up`, it reads data/transitpulse.duckdb when it exists (mounted
read-only); from a fresh clone the data endpoints answer 503."""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "tp-compose-smoke"  # not `transitpulse`, so a running `make up` stack is left alone
PORT = "8814"
HAS_WAREHOUSE = (ROOT / "data" / "transitpulse.duckdb").exists()


def compose(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-p", PROJECT, *args]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)


@pytest.fixture(scope="module")
def base() -> Iterator[str]:
    env = {**os.environ, "TP_AGENT_LLM": "fake", "TP_PORT": PORT}
    if HAS_WAREHOUSE:
        env.setdefault("TP_WAREHOUSE", "duckdb")
    try:
        up = compose("up", "-d", "--build", "--no-deps", "--wait", "api", env=env)
        logs = compose("logs", "api", env=env).stdout if up.returncode else ""
        assert up.returncode == 0, f"{up.stderr}\n{logs}"
        yield f"http://127.0.0.1:{PORT}"
    finally:
        compose("down", "--remove-orphans", env=env)


def test_health_and_site(base):
    assert httpx.get(f"{base}/api/health").status_code == 200
    home = httpx.get(f"{base}/")
    assert home.status_code == 200 and "TransitPulse" in home.text


def test_kpis_follow_the_warehouse(base):
    res = httpx.get(f"{base}/api/kpis", timeout=30)
    assert res.status_code == (200 if HAS_WAREHOUSE else 503), res.text
    if HAS_WAREHOUSE:
        assert len(res.json()["tiles"]) == 4  # the read-only DuckDB on a bind mount opens and answers


def test_ask_streams_to_exactly_one_terminal_event(base):
    res = httpx.post(f"{base}/api/ask", json={"question": "Which station had the most entries?"}, timeout=60)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    events = [line.split(":", 1)[1].strip() for line in res.text.splitlines() if line.startswith("event:")]
    terminal = [e for e in events if e in {"answer", "refusal", "error"}]
    assert len(terminal) == 1 and events[-1] == terminal[0], events
