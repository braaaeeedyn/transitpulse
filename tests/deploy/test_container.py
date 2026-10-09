"""Smoke tests for the Cloud Run image (Dockerfile at the repo root). Marker `docker`: they need Docker and the built
image, `${TP_TEST_IMAGE:-transitpulse-api:loop}` (`docker build -t transitpulse-api:loop .`). They fail rather than
skip when either is missing. Each container gets a random host port and the Cloud Run memory limit (512 MiB), and is
removed afterwards. Nothing here touches GCP: without TP_WAREHOUSE / TP_GCP_PROJECT the data endpoints answer 503.
"""

import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator

import httpx
import pytest

pytestmark = pytest.mark.docker

IMAGE = os.environ.get("TP_TEST_IMAGE", "transitpulse-api:loop")
UID = "10001"


def docker(*args: str, check: bool = True) -> str:
    res = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)
    if check and res.returncode:
        raise AssertionError(f"docker {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def run_in_image(script: str, user: str | None = None) -> str:
    as_user = ["--user", user] if user else []
    return docker("run", "--rm", *as_user, "--entrypoint", "sh", IMAGE, "-c", script)


def start(env: dict[str, str] | None = None) -> tuple[str, str]:
    """Start the image detached; returns (container name, base URL) once /healthz answers."""
    name = f"tp-smoke-{uuid.uuid4().hex[:8]}"
    env_args = [a for k, v in (env or {}).items() for a in ("-e", f"{k}={v}")]
    docker("run", "-d", "--name", name, "--memory", "512m", "-p", "127.0.0.1::8080", *env_args, IMAGE)
    try:
        host_port = docker("port", name, "8080/tcp").splitlines()[0].rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{host_port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"{base}/healthz", timeout=2).status_code == 200:
                    return name, base
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                logs = docker("logs", name, check=False)
                raise AssertionError(f"container didn't become healthy in 30 s:\n{logs}")
            time.sleep(0.5)
    except BaseException:
        docker("rm", "-f", name, check=False)
        raise


@pytest.fixture(scope="module")
def image() -> str:
    docker("image", "inspect", IMAGE)  # fails (not skips) when the image hasn't been built
    return IMAGE


@pytest.fixture(scope="module")
def server(image) -> Iterator[str]:
    name, base = start()
    try:
        yield base
    finally:
        docker("rm", "-f", name, check=False)


def parse_sse(body: str) -> list[tuple[str, object]]:
    """The browser's rules (web/js/ask.js): blank line ends an event, `data:` lines join with newlines."""
    events = []
    for block in body.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        event, data = "message", []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
        if data:
            events.append((event, json.loads("\n".join(data))))
    return events


def test_image_runs_as_non_root(image):
    config = json.loads(docker("image", "inspect", "-f", "{{json .Config}}", image))
    assert config["User"].split(":")[0] == UID
    assert run_in_image("id -u") == UID
    # the app can't modify its own code
    assert run_in_image("test -w /app/api || test -w /app/web || test -w /app/.venv || echo read-only") == (
        "read-only"
    )
    assert "8080" in " ".join(config.get("Cmd") or []) and "PORT" in " ".join(config.get("Cmd") or [])


def test_container_serves_site_and_health(server):
    assert httpx.get(f"{server}/healthz").json() == {"ok": True}

    home = httpx.get(f"{server}/")
    assert home.status_code == 200
    assert "text/html" in home.headers["content-type"]
    assert "TransitPulse" in home.text
    assert home.headers["cache-control"] == "no-cache"

    data = httpx.get(f"{server}/data/network.json")
    assert data.status_code == 200
    assert data.headers["cache-control"] == "public, max-age=86400"

    font = httpx.get(f"{server}/fonts/inter-400.woff2")
    assert font.status_code == 200
    assert font.headers["cache-control"] == "public, max-age=31536000, immutable"

    assert httpx.get(f"{server}/api/openapi.json").status_code == 200


def test_container_api_answers_503_without_warehouse(server):
    for path in ["/api/kpis", "/api/trends/ridership", "/api/forecast/EMBR"]:
        res = httpx.get(f"{server}{path}")
        assert res.status_code == 503, path
    ask = httpx.post(f"{server}/api/ask", json={"question": "Busiest station?"})
    assert ask.status_code == 503  # the agent is off unless TP_AGENT_ENABLED=true
    assert ask.json()["detail"]["code"] == "agent_unavailable"


def test_container_agent_streams_with_fake_llm(image):
    name, base = start({"TP_AGENT_ENABLED": "true", "TP_AGENT_LLM": "fake"})
    try:
        res = httpx.post(f"{base}/api/ask", json={"question": "What's a good pasta recipe?"}, timeout=30)
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(res.text)
        assert [e for e, _ in events] == ["thinking", "refusal"]
        refusal = events[-1][1]
        assert refusal["message"] and len(refusal["suggestions"]) == 3
    finally:
        docker("rm", "-f", name, check=False)


def test_image_has_no_secrets_or_dev_files(image):
    assert run_in_image("ls -A /app").split() == [".venv", "api", "web"]
    found = run_in_image(
        "find / -xdev \\( -name '*-key.json' -o -name '*.keyfile.json' -o -name '.env' -o -name '.env.*' "
        "-o -name '*.duckdb' -o -name '*.tfstate' -o -name 'terraform.tfvars' -o -name '.git' "
        "-o -name 'node_modules' -o \\( -name credentials -not -path '*/site-packages/*' \\) \\) -print",
        user="0",  # as root, so no directory is skipped for lack of permission
    )
    assert found == ""
    packages = run_in_image("ls /app/.venv/lib/python3.12/site-packages").split()
    lowered = {p.lower() for p in packages}
    for dev in ["pytest", "ruff", "dbt", "dagster", "lightgbm", "pyspark", "pandas", "locust", "pre_commit"]:
        assert not any(p == dev or p.startswith(f"{dev}-") for p in lowered), dev
    # what the API itself needs is there
    for needed in ["fastapi", "uvicorn", "duckdb", "langgraph", "sqlglot"]:
        assert needed in lowered, needed
    assert run_in_image("ls /app/api") and run_in_image("test -d /app/tests || echo absent") == "absent"
