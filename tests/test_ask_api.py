"""POST /api/ask (api/routes/ask.py) end to end with the FakeLLM on the dbt fixture warehouse."""

import json

import pytest
from fastapi.testclient import TestClient

from api import warehouse as warehouse_mod
from api.main import app
from api.routes import ask as ask_routes
from api.settings import get_settings


def _reset() -> None:
    get_settings.cache_clear()
    warehouse_mod._make.cache_clear()
    ask_routes.limiter.clear()
    try:
        from api.agent import service

        service.reset()
    except ImportError:
        pass


@pytest.fixture
def client(fixture_warehouse, monkeypatch):
    """A TestClient with the agent on (fake LLM) over the fixture warehouse; env overrides via the returned setter."""
    monkeypatch.delenv("TP_GCP_PROJECT", raising=False)
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "TP_TRUST_PROXY", "TP_AGENT_RATE_PER_MIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TP_WAREHOUSE", "duckdb")
    monkeypatch.setenv("TP_DUCKDB_PATH", str(fixture_warehouse))
    monkeypatch.setenv("TP_AGENT_ENABLED", "true")
    monkeypatch.setenv("TP_AGENT_LLM", "fake")

    def make(**env) -> TestClient:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        _reset()
        return TestClient(app)

    yield make
    _reset()


def parse_sse(body: str) -> list[tuple[str, object]]:
    """The same rules as the browser's parser in web/js/ask.js: events end at a blank line, `data:` lines join
    with newlines, lines starting with ':' are comments."""
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


def test_ask_503_when_disabled(client):
    res = client(TP_AGENT_ENABLED="false").post("/api/ask", json={"question": "Busiest station?"})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "agent_unavailable"


def test_ask_streams_sse_with_fake_llm(client):
    c = client()
    res = c.post("/api/ask", json={"question": "Which station is busiest?"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert "\r" not in res.text  # LF-delimited
    events = parse_sse(res.text)
    assert [e for e, _ in events] == ["thinking", "sql", "rows", "answer"]
    answer = events[-1][1]
    assert set(answer) == {"text", "columns", "rows", "sql"}
    assert answer["columns"] == ["station", "entries"]
    assert all(isinstance(r, list) for r in answer["rows"])
    assert answer["sql"] == events[1][1]["sql"]
    assert events[2][1]["count"] == len(answer["rows"])

    refused = parse_sse(c.post("/api/ask", json={"question": "Tell me a joke"}).text)
    assert [e for e, _ in refused] == ["thinking", "refusal"]
    assert len(refused[-1][1]["suggestions"]) == 3

    assert c.post("/api/ask", json={"question": ""}).status_code == 422
    assert c.post("/api/ask", json={"question": "x" * 301}).status_code == 422


def test_ask_rate_limited_per_ip(client):
    c = client(TP_AGENT_RATE_PER_MIN="2")
    q = {"question": "Tell me a joke"}
    assert c.post("/api/ask", json=q).status_code == 200
    assert c.post("/api/ask", json=q).status_code == 200
    res = c.post("/api/ask", json=q)
    assert res.status_code == 429
    assert res.json()["detail"]["code"] == "rate_limited"
    assert res.headers["retry-after"] == "60"


def test_ask_uses_forwarded_ip_only_when_trusted(client):
    q = {"question": "Tell me a joke"}
    # untrusted: a spoofed X-Forwarded-For doesn't give a fresh allowance
    c = client(TP_AGENT_RATE_PER_MIN="1", TP_TRUST_PROXY="false")
    assert c.post("/api/ask", json=q, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.post("/api/ask", json=q, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429

    # trusted (Cloud Run): the right-most entry, which the proxy appended, is the client
    c = client(TP_AGENT_RATE_PER_MIN="1", TP_TRUST_PROXY="true")
    assert c.post("/api/ask", json=q, headers={"X-Forwarded-For": "9.9.9.9, 1.1.1.1"}).status_code == 200
    assert c.post("/api/ask", json=q, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    assert c.post("/api/ask", json=q, headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"}).status_code == 200


def test_ask_daily_byte_budget_returns_busy(client):
    res = client(TP_AGENT_DAILY_BYTES="0").post("/api/ask", json={"question": "Which station is busiest?"})
    assert res.status_code == 429
    assert res.json()["detail"]["code"] == "agent_busy"


def test_rate_limiter_forgets_idle_clients():
    limiter = ask_routes.RateLimiter()
    for i in range(10_001):
        assert limiter.allow(f"10.0.{i // 256}.{i % 256}", per_minute=5, now=0.0)
    assert len(limiter._hits) == 10_001
    # a minute later every earlier client is idle: the next request past the cap forgets them all
    assert limiter.allow("192.0.2.1", per_minute=5, now=61.0)
    assert len(limiter._hits) <= 2
