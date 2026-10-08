"""POST /api/ask — the AI analyst (M5). Streams Server-Sent Events: thinking → sql → rows → answer.

Until the agent is built (TP_AGENT_ENABLED unset) it answers 503 so the site can show a friendly message.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.settings import get_settings

router = APIRouter(prefix="/api", tags=["agent"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)


@router.post("/ask")
def ask(req: AskRequest):
    if not get_settings().agent_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "agent_unavailable", "message": "The analyst isn't connected yet."},
        )
    raise HTTPException(status_code=501, detail={"code": "not_implemented", "message": "Coming in M5."})
