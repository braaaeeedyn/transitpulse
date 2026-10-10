"""GET /api/findings: the eBART causal study's results (docs/FINDINGS.md), as written by `analysis.causal.run`.

The file is read once per process and returned unchanged. It never touches the warehouse, so it answers with
TP_WAREHOUSE=none too. A missing or unreadable file is a 404 with a machine-readable code, which the site shows as
"The analysis is in progress."
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.settings import get_settings

router = APIRouter(prefix="/api", tags=["findings"])

NOT_AVAILABLE = {"code": "findings_not_available", "message": "The analysis is in progress."}
CACHE_CONTROL = "public, max-age=86400"


@lru_cache(maxsize=4)
def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "verdict" in data else None


@router.get("/findings")
def findings() -> JSONResponse:
    data = _load(get_settings().findings_path)
    if data is None:
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
    return JSONResponse(data, headers={"Cache-Control": CACHE_CONTROL})
