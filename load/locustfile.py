"""Locust load test for the API: the forecast, the KPI strip and Ask TransitPulse (POST /api/ask, SSE).

Run it through load/run_local.py, which starts the API on a generated fixture warehouse with the fake LLM and runs
1/10/25 users headless. To point it at another server by hand (never at production without a reason: every /api/ask
there costs BigQuery bytes and Gemini tokens):

    uv run --group load locust -f load/locustfile.py --host http://127.0.0.1:8000
"""

import json
import random

from locust import HttpUser, between, task

STATIONS = ["EMBR", "MONT", "POWL"]  # the fixture warehouse's stations (tests/dbt_fixture_data.py)
QUESTIONS = [
    "Which stations are busiest?",  # sql path: generate, guard, EXPLAIN, run, answer
    "How close is ridership to 2019?",
    "What's a good pasta recipe?",  # refused by the keyword pre-filter
]
FINAL_EVENTS = {"answer", "refusal"}


def sse_events(body: str) -> list[str]:
    """Event names in a text/event-stream body (the client's rules: a blank line ends an event)."""
    names = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, has_data = "message", False
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                json.loads(line[5:])
                has_data = True
        if has_data:
            names.append(name)
    return names


class SiteVisitor(HttpUser):
    """A visitor reading the dashboard: mostly KPIs and forecasts, sometimes a question."""

    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        # every endpoint is measured at least once per user, even in a short run
        self.kpis()
        self.forecast()
        self.ask()

    @task(3)
    def kpis(self) -> None:
        self.client.get("/api/kpis", name="kpis")

    @task(3)
    def forecast(self) -> None:
        self.client.get(f"/api/forecast/{random.choice(STATIONS)}", name="forecast")

    @task(1)
    def ask(self) -> None:
        question = random.choice(QUESTIONS)
        with self.client.post(
            "/api/ask", json={"question": question}, name="ask", catch_response=True
        ) as res:
            if res.status_code != 200:
                res.failure(f"HTTP {res.status_code}: {res.text[:200]}")
                return
            try:
                events = sse_events(res.text)
            except ValueError as e:
                res.failure(f"bad SSE data: {e}")
                return
            if not events or events[-1] not in FINAL_EVENTS:
                res.failure(f"stream ended with {events[-1:] or 'nothing'}: {res.text[-200:]}")
            else:
                res.success()
