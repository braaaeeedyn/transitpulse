"""Read-only data endpoints for the site (IMPLEMENTATION_PLAN §5).

They read the dbt marts in BigQuery. Until the warehouse is connected (TP_GCP_PROJECT unset) they answer
503 with a machine-readable reason, which the site shows as an empty state.
"""

from fastapi import APIRouter, HTTPException

from api.settings import get_settings

router = APIRouter(prefix="/api", tags=["data"])

NOT_CONNECTED = {"code": "warehouse_not_connected", "message": "Ridership data isn't connected yet."}


def _require_warehouse() -> None:
    if not get_settings().gcp_project:
        raise HTTPException(status_code=503, detail=NOT_CONNECTED)


@router.get("/kpis")
def kpis() -> dict:
    _require_warehouse()
    raise HTTPException(status_code=501, detail={"code": "not_implemented", "message": "Coming in M2."})


@router.get("/stations/{code}/summary")
def station_summary(code: str) -> dict:
    _require_warehouse()
    raise HTTPException(status_code=501, detail={"code": "not_implemented", "message": "Coming in M2."})


@router.get("/forecast/{code}")
def forecast(code: str) -> dict:
    _require_warehouse()
    raise HTTPException(status_code=501, detail={"code": "not_implemented", "message": "Coming in M3."})
