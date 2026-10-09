"""POST /api/ask: Ask TransitPulse (M5). Streams Server-Sent Events (LF-delimited, `event:` + one JSON `data:` line):
thinking, sql, rows, then answer, refusal or error. See api/agent/graph.py.

Off unless TP_AGENT_ENABLED=true (503, so the site shows a friendly message); the agent packages are imported only
when it is on, so the rest of the API runs without the `agent` dependency group. Before streaming starts it answers
429 when the client IP has asked more than TP_AGENT_RATE_PER_MIN questions in the last minute (`rate_limited`) or
the process's daily byte budget is spent (`agent_busy`).
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from api.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["agent"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class RateLimiter:
    """Sliding one-minute window per client IP, in memory (per process; Cloud Run runs at most 2)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, per_minute: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - 60:
                hits.popleft()
            if len(hits) >= per_minute:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # forget clients with no hit in the last minute
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - 60]:
                    del self._hits[k]
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's IP. X-Forwarded-For is client-controlled except for the entry the trusted proxy appended (the
    right-most), so it is read only with TP_TRUST_PROXY=true."""
    if settings.trust_proxy:
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if forwarded:
            return forwarded[-1]
    return request.client.host if request.client else "unknown"


def admit(request: Request):
    """Runs before the stream starts, so refusals to serve are plain HTTP errors: 503 when the agent is off, 429 when
    rate-limited or out of budget. Returns the agent."""
    s = get_settings()
    if not s.agent_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "agent_unavailable", "message": "The analyst isn't connected yet."},
        )
    if not limiter.allow(client_ip(request, s), s.agent_rate_per_min):
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": "Too many questions. Try again in a minute."},
            headers={"Retry-After": "60"},
        )
    from api.agent.service import get_agent

    agent = get_agent()
    if agent.deps.budget.exhausted():
        raise HTTPException(
            status_code=429,
            detail={"code": "agent_busy", "message": "The analyst has used today's query budget."},
        )
    return agent


@router.post("/ask", response_class=EventSourceResponse)
def ask(req: AskRequest, agent: Annotated[Any, Depends(admit)]) -> Iterator[ServerSentEvent]:
    for event, data in agent.stream(req.question.strip()):
        yield ServerSentEvent(event=event, data=data)
