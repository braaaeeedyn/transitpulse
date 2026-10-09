"""The agent eval set's gold SQL on the real local warehouse (data/transitpulse.duckdb): every question has an
answer there (marker `localdata`; fails rather than skips when the file is missing)."""

from pathlib import Path

import pytest

from api.warehouse import DuckDBWarehouse
from eval.gold import load_questions, run_gold

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "transitpulse.duckdb"

pytestmark = pytest.mark.localdata


def test_gold_sql_returns_rows_on_local_warehouse():
    assert DB.exists(), f"{DB} not found: build it with tasks.py dbt / forecast"
    wh = DuckDBWarehouse(DB)
    empty = []
    for q in load_questions():
        if q.get("expect") == "refusal":
            continue
        _, rows = run_gold(wh, q["sql"])
        if not rows or all(v is None for v in rows[0]):
            empty.append(q["id"])
    assert not empty, f"gold SQL with no answer on the local warehouse: {empty}"
