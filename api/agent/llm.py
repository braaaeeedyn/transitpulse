"""LLM backends for the agent, picked by TP_AGENT_LLM:

  fake   - FakeLLM, deterministic and offline: a test double (and the eval harness's oracle), not a model
  ollama - ChatOllama (TP_OLLAMA_MODEL, default llama3.1:8b, at TP_OLLAMA_URL)
  gemini - ChatGoogleGenerativeAI (TP_GEMINI_MODEL; the key comes from GOOGLE_API_KEY)

Every backend has the same one-method interface, complete(prompt, config) -> str.
"""

import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from api.agent.prompts import Prompt
from api.settings import Settings


class LLM(Protocol):
    name: str

    def complete(self, prompt: Prompt, config: Any = None) -> str: ...


class ChatLLM:
    """A LangChain chat model behind the agent's interface."""

    def __init__(self, model: Any, name: str):
        self.model = model
        self.name = name

    def complete(self, prompt: Prompt, config: Any = None) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        msg = self.model.invoke([SystemMessage(prompt.system), HumanMessage(prompt.user)], config=config)
        content = msg.content
        if isinstance(content, list):  # some providers return content blocks
            content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
        return str(content).strip()


# --- the fake ------------------------------------------------------------------------------------------

DOMAIN = re.compile(
    r"\b(bart|station|stations|ridership|riders?|entries|entry|exits?|trips?|bikes?|bay wheels|bike-share|"
    r"commut\w*|train|trains|recovery|recovered|peak|busiest|busy|forecast|weekday|weekend|2019|202\d)\b",
    re.I,
)
FORECAST = re.compile(r"\b(forecast|predict\w*|expected|next (two|2|14) (weeks|days))\b", re.I)

# a few canned queries so `TP_AGENT_LLM=fake` gives a working demo (container smoke test, load test)
DEFAULT_SQL = [
    (
        re.compile(r"busiest|most entries|most riders", re.I),
        "select s.station_name as station, sum(f.entries) as entries from marts.fct_station_daily as f "
        "join marts.dim_station as s on s.station_code = f.station_code and s.is_current "
        "where f.trip_date > (select date_sub(max(trip_date), interval 28 day) from marts.fct_station_daily) "
        "group by 1 order by entries desc limit 5",
    ),
    (
        re.compile(r"recover|2019|close", re.I),
        "select month_start as month, avg_service_weekday_recovery as recovery from marts.mart_ridership_monthly "
        "order by month_start desc limit 12",
    ),
    (
        re.compile(r"bike", re.I),
        "select month_start as month, bart_avg_daily_entries as bart_per_day, bike_avg_daily_trips as bikes_per_day "
        "from marts.mart_bikes_vs_trains order by month_start desc limit 12",
    ),
    (
        re.compile(r"hour", re.I),
        "select s.station_name as station, p.peak_hour, p.peak_hour_share from marts.mart_peak_load as p "
        "join marts.dim_station as s on s.station_code = p.station_code and s.is_current "
        "order by p.avg_weekday_entries desc limit 10",
    ),
]
FALLBACK_SQL = "select max(trip_date) as data_through, count(*) as days from marts.mart_kpis_daily"


class FakeLLM:
    """Deterministic stand-in for a model. `sql` maps a question to the SQL to return, or to a list of SQL strings
    returned on successive attempts (to script a failed first try and its repair)."""

    name = "fake"

    def __init__(
        self,
        sql: Mapping[str, str | Sequence[str]] | None = None,
        route: Callable[[str], str] | None = None,
    ):
        self.sql = dict(sql or {})
        self._route = route
        self.calls: dict[str, int] = defaultdict(int)
        self.prompts: list[Prompt] = []

    def complete(self, prompt: Prompt, config: Any = None) -> str:
        self.prompts.append(prompt)
        if prompt.task == "route":
            return self._route(prompt.question) if self._route else self.route(prompt.question)
        if prompt.task == "sql":
            return self._sql(prompt.question)
        return self._answer(prompt)

    @staticmethod
    def route(question: str) -> str:
        if not DOMAIN.search(question):
            return "refuse"
        return "forecast" if FORECAST.search(question) else "sql"

    def _sql(self, question: str) -> str:
        n = self.calls[question]
        self.calls[question] += 1
        scripted = self.sql.get(question)
        if isinstance(scripted, str):
            return scripted
        if scripted:
            return scripted[min(n, len(scripted) - 1)]
        for pattern, sql in DEFAULT_SQL:
            if pattern.search(question):
                return sql
        return FALLBACK_SQL

    @staticmethod
    def _answer(prompt: Prompt) -> str:
        lines = prompt.user.split("Result:\n", 1)[-1].splitlines()
        if len(lines) < 2:
            return "The data doesn't cover that."
        header = lines[0].split(" | ")
        first = lines[1].split(" | ")
        pairs = ", ".join(f"{c} {v}" for c, v in zip(header, first, strict=False))
        return f"The first of {len(lines) - 1} rows shows {pairs}."


def make_llm(settings: Settings) -> LLM:
    """The backend TP_AGENT_LLM names. Constructing one never touches the network."""
    if settings.agent_llm == "ollama":
        from langchain_ollama import ChatOllama

        model = ChatOllama(model=settings.ollama_model, base_url=settings.ollama_url, temperature=0)
        return ChatLLM(model, f"ollama:{settings.ollama_model}")
    if settings.agent_llm == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(model=settings.gemini_model, temperature=0)
        return ChatLLM(model, f"gemini:{settings.gemini_model}")
    return FakeLLM()
