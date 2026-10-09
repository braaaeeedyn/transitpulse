"""Wires the agent to the API's settings and warehouse: one compiled graph and one daily byte budget per process.
Imported by api/routes/ask.py only when TP_AGENT_ENABLED=true."""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from api.agent.graph import AgentDeps, ByteBudget, build_graph, run_agent
from api.agent.llm import make_llm
from api.settings import get_settings
from api.warehouse import get_warehouse


@dataclass
class Agent:
    deps: AgentDeps
    graph: Any

    def stream(self, question: str) -> Iterator[tuple[str, dict]]:
        return run_agent(question, self.deps, self.graph)


@lru_cache
def get_agent() -> Agent:
    s = get_settings()
    deps = AgentDeps(
        llm=make_llm(s),
        warehouse=get_warehouse(),
        budget=ByteBudget(s.agent_daily_bytes),
        max_bytes=s.agent_max_bytes,
        row_limit=s.agent_row_limit,
        timeout_s=s.agent_timeout_s,
    )
    return Agent(deps, build_graph(deps))


def reset() -> None:
    get_agent.cache_clear()
