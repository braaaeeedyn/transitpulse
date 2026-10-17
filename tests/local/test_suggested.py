"""Every suggested question's reviewed query (api/agent/suggested.py) passes the guardrails and answers from the local
warehouse, with the answers the owner's phone check expects (docs/OWNER_STEPS.md step 6). Marker `localdata`."""

from pathlib import Path

import duckdb
import pytest

from api.agent.guardrails import check_sql
from api.agent.suggested import SUGGESTED_SQL

DB = Path(__file__).resolve().parents[2] / "data" / "transitpulse.duckdb"
pytestmark = pytest.mark.localdata

FIRST_ROW = {
    "Which stations grew most since 2022?": ("Orinda", 749.0, 1159.0, 54.7),
    "Which stations had the most entries in 2025?": ("Embarcadero", 4787378),
    "How close is ridership to 2019?": (149335.0, 324958.0, 46.0),
    "How close is weekday ridership to 2019?": (43.0,),
    "Bikes vs. trains in the latest month?": ("2025-12-01", 42.8, 190.9),
    "Which station has the highest peak-hour share?": ("Montgomery Street", 17, 22.3),
}


@pytest.mark.parametrize("question", sorted(SUGGESTED_SQL))
def test_reviewed_query_answers_from_the_local_warehouse(question):
    assert DB.exists(), f"{DB} not found: build it with tasks.py dbt"
    sql = check_sql(SUGGESTED_SQL[question], dialect="duckdb", project=None, row_limit=200).sql
    row = duckdb.connect(str(DB), read_only=True).execute(sql).fetchone()
    want = FIRST_ROW[question]
    got = tuple(str(v) if hasattr(v, "isoformat") else v for v in row[: len(want)])
    assert got == want
