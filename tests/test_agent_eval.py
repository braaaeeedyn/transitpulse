"""The agent eval set (eval/questions.yaml), its gold SQL and the execution-accuracy scoring (eval/scoring.py)."""

import datetime as dt

import pytest

from api.agent.graph import AgentDeps, ByteBudget
from api.agent.guardrails import check_sql
from api.warehouse import DuckDBWarehouse
from eval.gold import load_questions, run_gold
from eval.run_eval import evaluate, main, oracle_llm
from eval.scoring import execution_match, is_ordered

TAGS = {"kpi", "station", "trend", "bikes", "forecast", "od"}


def test_eval_set_is_well_formed():
    questions = load_questions()
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "ids must be unique"
    assert len({q["question"] for q in questions}) == len(questions), "questions must be unique"
    in_scope = [q for q in questions if q.get("expect") != "refusal"]
    refusals = [q for q in questions if q.get("expect") == "refusal"]
    assert len(in_scope) >= 60
    assert len(refusals) >= 8
    for q in in_scope:
        assert q["sql"].strip() and q["question"].strip(), q["id"]
        assert set(q["tags"]) <= TAGS and q["tags"], q["id"]
        assert q.get("route", "sql") in ("sql", "forecast"), q["id"]
    assert {t for q in in_scope for t in q["tags"]} >= TAGS  # every tag is covered
    for q in refusals:
        assert "sql" not in q, q["id"]


def test_gold_sql_passes_guardrails_and_runs_on_fixture(fixture_warehouse):
    wh = DuckDBWarehouse(fixture_warehouse)
    for q in load_questions():
        if q.get("expect") == "refusal":
            continue
        check_sql(q["sql"], dialect="bigquery", project="transitpulse-511002")  # the production dialect too
        columns, _rows = run_gold(wh, q["sql"])  # raises on any guardrail or warehouse error
        assert columns, q["id"]
    # and the oracle run of the whole set through the agent scores 1.0 on the fixture
    questions = load_questions()
    deps = AgentDeps(llm=oracle_llm(questions), warehouse=wh, budget=ByteBudget(10**10))
    report = evaluate(questions, deps)
    wrong = [r for r in report["results"] if not r["correct"]]
    assert not wrong
    assert report["execution_accuracy"] == 1.0 and report["refusal_accuracy"] == 1.0
    assert report["guardrail_rejections"] == 0


def test_eval_writes_summary_only_when_asked(fixture_warehouse, tmp_path):
    questions = load_questions()
    answer = next(q["id"] for q in questions if q.get("expect") != "refusal")
    refusal = next(q["id"] for q in questions if q.get("expect") == "refusal")
    base = [
        "--llm",
        "fake",
        "--duckdb-path",
        str(fixture_warehouse),
        "--ids",
        f"{answer},{refusal}",
        "--json",
    ]

    plain = tmp_path / "plain"
    assert main([*base, "--results-dir", str(plain)]) == 0
    assert len(list(plain.glob("fake-*.json"))) == 1  # the per-question detail is still written
    assert not list(plain.glob("summary-*.json"))

    saved = tmp_path / "saved"
    assert main([*base, "--results-dir", str(saved), "--save-summary"]) == 0
    assert len(list(saved.glob("summary-fake-*.json"))) == 1


def test_execution_accuracy_scoring():
    gold_cols, gold = ["station", "entries"], [["EMBR", 420], ["MONT", 410.0]]
    assert execution_match(gold_cols, gold, gold_cols, gold)  # oracle
    # row order, column order and names don't matter without ORDER BY ... LIMIT
    assert execution_match(gold_cols, gold, ["n", "s"], [[410, "MONT"], [420.00001, "EMBR"]])
    # ... but they do with it
    assert not execution_match(gold_cols, gold, gold_cols, [["MONT", 410], ["EMBR", 420]], ordered=True)
    # wrong values, missing or extra rows, a different column count
    assert not execution_match(gold_cols, gold, gold_cols, [["EMBR", 421], ["MONT", 410]])
    assert not execution_match(gold_cols, gold, gold_cols, gold[:1])
    assert not execution_match(gold_cols, gold, gold_cols, [*gold, ["POWL", 1]])
    assert not execution_match(gold_cols, gold, ["station"], [["EMBR"], ["MONT"]])
    # duplicates are a multiset, not a set
    assert not execution_match(["a"], [[1], [1]], ["a"], [[1], [2]])
    # floats at relative 1e-4; dates as ISO; Decimal as float
    from decimal import Decimal

    assert execution_match(["x"], [[0.123456]], ["x"], [[0.12346]])
    assert not execution_match(["x"], [[0.1234]], ["x"], [[0.1236]])
    assert execution_match(["d"], [[dt.date(2025, 1, 6)]], ["d"], [["2025-01-06"]])
    assert execution_match(["v"], [[Decimal("2.50")]], ["v"], [[2.5]])
    assert execution_match(["v"], [[None]], ["v"], [[None]])
    # which gold queries are order-sensitive
    assert is_ordered("select a from marts.t order by a desc limit 5")
    assert not is_ordered("select a from marts.t order by a")
    assert not is_ordered("select a from (select a from marts.t order by a limit 3)")


@pytest.mark.parametrize("bad", ["select 1", "select * from raw.bart_od"])
def test_gold_sql_runner_uses_the_guardrails(fixture_warehouse, bad):
    from api.agent.guardrails import GuardrailError

    with pytest.raises(GuardrailError):
        run_gold(DuckDBWarehouse(fixture_warehouse), bad)
