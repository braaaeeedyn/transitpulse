"""The eval set and its gold SQL runner. No LangGraph/LLM imports, so the gold SQL can be checked on its own."""

from pathlib import Path
from typing import Any

import yaml

from api.agent.guardrails import check_sql
from api.warehouse import DuckDBWarehouse

QUESTIONS = Path(__file__).with_name("questions.yaml")


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def _json_safe(value: Any) -> Any:
    import datetime as dt
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


def run_gold(wh: DuckDBWarehouse, sql: str, row_limit: int = 200) -> tuple[list[str], list[list]]:
    """Run gold SQL exactly as the agent's SQL runs: guardrails (BigQuery dialect in, the warehouse's out), then the
    warehouse's locked-down agent connection."""
    checked = check_sql(sql, dialect=wh.dialect, row_limit=row_limit)
    result = wh.agent_query(checked.sql, 0, 60)
    return result.columns, [[_json_safe(v) for v in r] for r in result.rows]
