"""The M5 A/B test (docs/AB_TEST.md): the statistics in eval/ab.py, the example retrieval and prompt of arm B, the
examples pool and the doc."""

import itertools
import re
from types import SimpleNamespace

import pytest

from api.agent import prompts
from api.agent.graph import AgentDeps, ByteBudget, run_agent
from api.agent.llm import FakeLLM
from api.settings import Settings
from eval import ab, examples
from eval.gold import load_questions
from eval.run_eval import ARMS

QUESTIONS = load_questions()


def test_mcnemar_exact_matches_binomial():
    # scipy.stats.binomtest(b, b + c, 0.5).pvalue, computed once (scipy isn't in the agent group)
    for (b, c), want in {(5, 20): 0.004077315330505371, (3, 10): 0.09228515625, (0, 6): 0.03125}.items():
        assert ab.mcnemar_exact(b, c) == pytest.approx(want, rel=1e-12)
        assert ab.mcnemar_exact(c, b) == pytest.approx(want, rel=1e-12)
    # and by enumerating every outcome: P(|X - n/2| >= |b - n/2|) for X ~ Binomial(n, 1/2)
    for b, c in [(2, 7), (4, 4), (1, 9)]:
        n = b + c
        extreme = sum(abs(sum(o) - n / 2) >= abs(b - n / 2) for o in itertools.product((0, 1), repeat=n))
        assert ab.mcnemar_exact(b, c) == pytest.approx(extreme / 2**n, rel=1e-12)
    assert ab.mcnemar_exact(0, 0) == 1.0 and ab.mcnemar_exact(7, 7) == 1.0


def test_bootstrap_ci_is_seeded():
    a = [i % 3 == 0 for i in range(66)]
    b = [i % 2 == 0 for i in range(66)]
    lo, hi = ab.bootstrap_ci(a, b)
    assert (lo, hi) == ab.bootstrap_ci(a, b)  # seed 0, the same every time
    assert ab.bootstrap_ci(a, b, resamples=50) != ab.bootstrap_ci(
        a, b, resamples=50, seed=1
    )  # the seed matters
    diff = (sum(b) - sum(a)) / 66
    assert lo < diff < hi
    assert ab.bootstrap_ci(a, a) == (0.0, 0.0)  # identical arms: every resample's difference is 0


def test_power_increases_with_effect():
    powers = [ab.power(66, 18 / 66, e) for e in (0.0, *ab.EFFECTS)]
    assert powers == sorted(powers) and powers[0] < 0.05 < 0.8 < powers[-1]
    assert ab.power(66, 18 / 66, 0.10) == ab.power(66, 18 / 66, 0.10)  # seeded
    assert ab.power(66, 18 / 66, 0.80) is None  # more than fixing every wrong answer can give
    out = ab.power_analysis(66, 18 / 66)
    mde = out["mde_points_at_80"]
    assert ab.power(66, 18 / 66, mde / 100) >= 0.8 > ab.power(66, 18 / 66, (mde - 1) / 100)


def test_bm25_retrieval_is_deterministic_and_leave_one_out():
    q = next(x for x in QUESTIONS if x["id"] == "k05")
    first = prompts.retrieve_examples(q["question"], 5, exclude=[q["id"]])
    assert [x["id"] for x in first] == [
        x["id"] for x in prompts.retrieve_examples(q["question"], 5, [q["id"]])
    ]
    assert len(first) == 5 and q["id"] not in {x["id"] for x in first}
    assert prompts.retrieve_examples(q["question"], 5)[0]["id"] == q["id"]  # production: no exclusion
    assert first[0]["id"] == "k06"  # the near-twin ("fewest" for "most")
    assert prompts.retrieve_examples(q["question"], 0) == []
    # ties go to pool order
    pool = [{"id": i, "question": "same words", "sql": "select 1"} for i in ("x1", "x2", "x3")]
    assert [x["id"] for x in prompts.retrieve_examples("same words", 2, pool=pool)] == ["x1", "x2"]


class _Warehouse:
    """Just enough warehouse for the graph to run a query."""

    dialect = "duckdb"

    def agent_dry_run(self, sql, max_bytes):
        return 0

    def agent_query(self, sql, max_bytes, timeout_s):
        return SimpleNamespace(columns=["x"], rows=[[1]], bytes_processed=0)


def test_arm_b_prompt_has_five_examples_and_arm_a_none():
    q = next(x for x in QUESTIONS if x["id"] == "t04")
    sent = {}
    for arm, k in ARMS.items():
        llm = FakeLLM(
            sql={q["question"]: "select max(trip_date) as x from marts.mart_kpis_daily"},
            route=lambda _: "sql",
        )
        deps = AgentDeps(llm=llm, warehouse=_Warehouse(), budget=ByteBudget(10**10), examples_k=k)
        events = list(run_agent(q["question"], deps, exclude_examples=[q["id"]]))
        assert events[-1][0] == "answer", events
        sent[arm] = next(p for p in llm.prompts if p.task == "sql")
        assert next(p for p in llm.prompts if p.task == "route") == prompts.route_prompt(q["question"])
    assert sent["A"] == prompts.sql_prompt(q["question"])  # arm A: exactly today's prompt
    assert sent["B"].system == sent["A"].system
    shown = re.findall(r"^SQL: (.+)$", sent["B"].user, flags=re.M)
    assert len(shown) == 5 and " ".join(q["sql"].split()) not in shown  # leave-one-out
    assert sent["B"].user.endswith(f"Question: {q['question']}")


def test_examples_json_matches_questions_yaml():
    assert prompts.EXAMPLES_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") == examples.render()
    pool = prompts.example_pool()
    sql_ids = [x["id"] for x in QUESTIONS if x.get("expect") != "refusal" and x.get("route", "sql") == "sql"]
    assert [x["id"] for x in pool] == sql_ids and len(pool) == 63
    assert examples.main([]) == 0


def test_default_examples_k_follows_the_decision():
    a, b = ab.newest("ollama:llama3.1:8b", "A"), ab.newest("ollama:llama3.1:8b", "B")
    assert a is not None and b is not None, "commit both arms' summaries"
    result = ab.compare(a, b, QUESTIONS)
    assert Settings.model_fields["agent_examples_k"].default == result["default_examples_k"]
    assert result["default_examples_k"] in (ARMS["A"], ARMS["B"])


def test_ab_doc_has_power_design_results_decision_limitations():
    text = ab.DOC.read_text(encoding="utf-8")
    heads = re.findall(r"^## (.+)$", text, flags=re.M)
    assert heads == [
        "Question",
        "Power analysis",
        "Design (pre-registered, fixed before any arm-B run)",
        "Results",
        "Decision",
        "Limitations",
        "Arm C (M6, not run)",
    ]
    assert "Not run yet" not in text and "Not decided yet" not in text
    power = text.split("## Power analysis\n", 1)[1].split("\n## ", 1)[0]
    a = ab.newest("ollama:llama3.1:8b", "A")
    in_scope = [q["id"] for q in QUESTIONS if q.get("expect") != "refusal"]
    acc = sum(a["per_question"][i]["correct"] for i in in_scope) / len(in_scope)
    out = ab.power_analysis(len(in_scope), acc)
    assert f"{acc:.4f}" in power and f"+{out['mde_points_at_80']} points" in power
    for effect, pw in out["power"].items():
        assert f"| {effect} points | " in power and f"| {pw:.3f} |" in power, effect
    limits = text.split("## Limitations\n", 1)[1].split("\n## ", 1)[0].lower()
    assert "near-twin" in limits and "gemini" in limits
