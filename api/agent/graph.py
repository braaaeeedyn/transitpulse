"""The Ask TransitPulse agent: a LangGraph StateGraph that turns a question into one guarded SQL query and a short
answer, emitting progress events as it goes (the SSE stream POST /api/ask sends).

    route ─┬─ refuse ──────────────────────────────────────────────► (refusal)
           ├─ forecast: fixed query on forecast_station_daily ─────► answer
           └─ generate ─► check (guardrails + dry run) ─► execute ─► answer
                 ▲              │ rejected / failed once        │
                 └──────────────┴───────────────────────────────┘   (a second failure ends with an error event)

Events (name, JSON payload), in order: thinking, sql {sql}, rows {count, columns}, then exactly one of
answer {text, columns, rows, sql}, refusal {message, suggestions} or error {code, message}.
"""

import datetime as dt
import math
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from api.agent import prompts, tracing
from api.agent.guardrails import GuardrailError, check_sql
from api.agent.llm import LLM
from api.warehouse import AgentQueryError, QueryTooExpensive

SUGGESTIONS = [
    "Which stations had the most entries in 2025?",
    "How close is weekday ridership to 2019?",
    "What's the 14-day forecast for Embarcadero?",
]
REFUSAL = (
    "I can only answer questions about BART ridership, Bay Wheels trips and the station forecast in this "
    "site's data. Try one of these:"
)
# cheap pre-filter before the router: obvious attempts to change data or reach outside the published tables
BLOCKED_QUESTION = re.compile(
    r"\b(drop|delete|truncate|insert|update|alter|grant)\b.*\b(table|tables|data|rows?|database)\b|"
    r"\bignore (all |your |the )?(previous |prior )?instructions\b|\bsystem prompt\b|\binformation_schema\b|"
    r"\b(password|api key|credentials?|secret)\b",
    re.I,
)
MAX_ATTEMPTS = 2  # the first SQL plus one repair


@dataclass
class ByteBudget:
    """Per-process daily budget of warehouse bytes for agent queries (resets at UTC midnight)."""

    limit: int
    used: int = 0
    day: dt.date = field(default_factory=lambda: dt.datetime.now(dt.UTC).date())
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _roll(self) -> None:
        today = dt.datetime.now(dt.UTC).date()
        if today != self.day:
            self.day, self.used = today, 0

    def exhausted(self) -> bool:
        with self._lock:
            self._roll()
            return self.used >= self.limit

    def allows(self, n: int) -> bool:
        with self._lock:
            self._roll()
            return self.used + n <= self.limit

    def add(self, n: int) -> None:
        with self._lock:
            self._roll()
            self.used += n


@dataclass
class AgentDeps:
    llm: LLM
    warehouse: Any  # api.warehouse.DuckDBWarehouse | BigQueryWarehouse
    budget: ByteBudget
    max_bytes: int = 1_000_000_000
    row_limit: int = 200
    timeout_s: float = 20.0


class AgentState(TypedDict, total=False):
    question: str
    route: str
    raw_sql: str
    sql: str
    attempts: int
    error: str | None
    error_code: str | None
    columns: list[str]
    rows: list[list]
    station: str | None


class AgentStop(Exception):
    """Ends the run with an error event."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _clean_sql(text: str) -> str:
    """Models sometimes wrap SQL in Markdown fences or add a sentence; keep the statement."""
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if m:
        text = m.group(1)
    m = re.search(r"\b(with|select)\b", text, re.I)
    return text[m.start() :].strip() if m else text.strip()


def build_graph(deps: AgentDeps):
    wh = deps.warehouse
    project = getattr(wh, "project", None)

    def guard(sql: str) -> str:
        return check_sql(sql, dialect=wh.dialect, project=project, row_limit=deps.row_limit).sql

    def run(sql: str) -> tuple[list[str], list[list]]:
        estimate = wh.agent_dry_run(sql, deps.max_bytes)
        if not deps.budget.allows(estimate):
            raise AgentStop("agent_busy", "The analyst has used today's query budget. Try again tomorrow.")
        writer = get_stream_writer()
        writer(("sql", {"sql": sql}))
        result = wh.agent_query(sql, deps.max_bytes, deps.timeout_s)
        deps.budget.add(result.bytes_processed)
        rows = [[json_safe(v) for v in r] for r in result.rows]
        writer(("rows", {"count": len(rows), "columns": result.columns}))
        return result.columns, rows

    def route(state: AgentState, config) -> AgentState:
        get_stream_writer()(("thinking", {"message": "Understanding the question"}))
        q = state["question"]
        if BLOCKED_QUESTION.search(q):
            return {"route": "refuse"}
        word = deps.llm.complete(prompts.route_prompt(q), config).strip().lower()
        choice = next((w for w in ("forecast", "refuse", "sql") if w in word), "sql")
        if choice != "refuse" and wh is None:
            raise AgentStop("agent_unavailable", "The analyst isn't connected to the data right now.")
        return {"route": choice, "attempts": 0}

    def refuse(state: AgentState) -> AgentState:
        get_stream_writer()(("refusal", {"message": REFUSAL, "suggestions": SUGGESTIONS}))
        return {}

    def generate(state: AgentState, config) -> AgentState:
        prompt = prompts.sql_prompt(state["question"], state.get("raw_sql"), state.get("error"))
        raw = _clean_sql(deps.llm.complete(prompt, config))
        return {"raw_sql": raw, "attempts": state.get("attempts", 0) + 1, "error": None, "error_code": None}

    def execute(state: AgentState) -> AgentState:
        try:
            sql = guard(state["raw_sql"])
            columns, rows = run(sql)
        except GuardrailError as e:
            return {"error": e.message, "error_code": "sql_rejected"}
        except QueryTooExpensive as e:
            return {
                "error": f"{e} Filter to fewer days or use a monthly table.",
                "error_code": "too_expensive",
            }
        except AgentQueryError as e:
            return {"error": str(e), "error_code": "query_failed"}
        return {"sql": sql, "columns": columns, "rows": rows}

    def after_execute(state: AgentState) -> str:
        if not state.get("error"):
            return "answer"
        return "generate" if state.get("attempts", 0) < MAX_ATTEMPTS else "fail"

    def fail(state: AgentState) -> AgentState:
        messages = {
            "sql_rejected": "I couldn't write a safe query for that. Try asking it a different way.",
            "too_expensive": "That question needs more data than one query is allowed to read. Try a narrower one.",
            "query_failed": "The query for that question didn't run. Try asking it a different way.",
        }
        code = state.get("error_code") or "query_failed"
        raise AgentStop(code, messages.get(code, messages["query_failed"]))

    def forecast(state: AgentState) -> AgentState:
        stations = wh.agent_query(
            check_sql(
                "select station_code, station_name from marts.dim_station where is_current",
                dialect=wh.dialect,
                project=project,
                row_limit=500,
            ).sql,
            deps.max_bytes,
            deps.timeout_s,
        ).rows
        code = find_station(state["question"], stations)
        if code is None:
            get_stream_writer()(
                (
                    "refusal",
                    {
                        "message": "Which station? The forecast is per BART station, e.g. Embarcadero or MONT.",
                        "suggestions": [
                            "What's the 14-day forecast for Embarcadero?",
                            "Forecast for Powell Street",
                            "Expected entries at MacArthur next two weeks",
                        ],
                    },
                )
            )
            return {"station": None}
        sql = (
            "select forecast_date, round(p50) as expected_entries, round(p10) as low, round(p90) as high "
            f"from marts.forecast_station_daily where station_code = '{code}' and generated_at = "
            f"(select max(generated_at) from marts.forecast_station_daily where station_code = '{code}') "
            "order by forecast_date"
        )
        try:
            columns, rows = run(guard(sql))
        except (AgentQueryError, QueryTooExpensive) as e:
            raise AgentStop("forecast_unavailable", "The forecast isn't available right now.") from e
        return {"station": code, "sql": guard(sql), "columns": columns, "rows": rows}

    def after_forecast(state: AgentState) -> str:
        return "answer" if state.get("station") else END

    def answer(state: AgentState, config) -> AgentState:
        columns, rows, sql = state["columns"], state["rows"], state["sql"]
        text = deps.llm.complete(prompts.answer_prompt(state["question"], columns, rows, sql), config)
        get_stream_writer()(("answer", {"text": text, "columns": columns, "rows": rows, "sql": sql}))
        return {}

    g = StateGraph(AgentState)
    g.add_node("route", route)
    g.add_node("refuse", refuse)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("fail", fail)
    g.add_node("forecast", forecast)
    g.add_node("answer", answer)
    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route", lambda s: s["route"], {"sql": "generate", "forecast": "forecast", "refuse": "refuse"}
    )
    g.add_edge("refuse", END)
    g.add_edge("generate", "execute")
    g.add_conditional_edges("execute", after_execute, ["answer", "generate", "fail"])
    g.add_edge("fail", END)
    g.add_conditional_edges("forecast", after_forecast, ["answer", END])
    g.add_edge("answer", END)
    return g.compile()


def find_station(question: str, stations: list[tuple]) -> str | None:
    """The station a question names: a 4-letter code (EMBR) or the longest station name it contains."""
    codes = {str(c).upper(): c for c, _ in stations}
    for token in re.findall(r"\b[A-Z0-9]{4}\b", question):
        if token in codes:
            return codes[token]
    q = question.lower()
    best = None
    for code, name in stations:
        for variant in {str(name).lower(), str(name).lower().split(" / ")[0]}:
            if variant and variant in q and (best is None or len(variant) > best[1]):
                best = (code, len(variant))
    return best[0] if best else None


def run_agent(question: str, deps: AgentDeps, graph=None) -> Iterator[tuple[str, dict]]:
    """Run the graph and yield (event, payload) pairs; always ends with answer, refusal or error."""
    graph = graph or build_graph(deps)
    config = {"callbacks": tracing.callbacks(), "run_name": "ask-transitpulse"}
    final = False
    try:
        for event, data in graph.stream({"question": question}, config, stream_mode="custom"):
            final = final or event in ("answer", "refusal", "error")
            yield event, data
    except AgentStop as e:
        final = True
        yield "error", {"code": e.code, "message": e.message}
    except Exception as e:  # an LLM or warehouse outage: report it instead of a broken stream
        final = True
        yield "error", {"code": "agent_error", "message": f"The analyst hit a problem ({type(e).__name__})."}
    if not final:
        yield "error", {"code": "no_answer", "message": "The analyst stopped without an answer."}


def timed(it: Iterator[tuple[str, dict]]) -> tuple[list[tuple[str, dict]], float]:
    """Collect a run's events and its wall time in seconds (the eval harness uses this)."""
    t0 = time.perf_counter()
    events = list(it)
    return events, time.perf_counter() - t0
