"""Run the Ask TransitPulse eval set (eval/questions.yaml) through the agent and score it.

    uv run --group agent python -m eval.run_eval --llm fake|ollama|gemini --warehouse duckdb [--arm A|B]
        [--duckdb-path data/transitpulse.duckdb] [--ids k01,s02] [--json] [--save-summary] [--results-dir DIR]

Reports execution accuracy (in-scope questions whose answer rows match the gold rows, see eval/scoring.py), refusal
accuracy (out-of-scope questions refused; in-scope ones that were refused count as wrong), guardrail rejections
(questions that ended because every SQL attempt was rejected) and latency p50/p95. Writes
eval/results/<llm>-<arm>-<timestamp>.json with every question's outcome (gitignored). Only with `--save-summary` does
it also write summary-<llm>-<arm>-<timestamp>.json, the file that is committed when a run is worth citing; routine
runs don't add one.

`--arm` is the M5 A/B arm (docs/AB_TEST.md): A = today's prompts, B = A plus 5 retrieved question + SQL examples in
the SQL prompt, each question's own example left out. `python -m eval.ab` compares the two arms' summaries.

`--llm fake` is the FakeLLM scripted with the gold SQL and routes: an oracle that checks the harness, the guardrails
and the warehouse path end to end. It should score 1.0; it says nothing about a model.
"""

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from api.agent.graph import AgentDeps, ByteBudget, build_graph, run_agent, timed
from api.agent.guardrails import GuardrailError
from api.agent.llm import FakeLLM, make_llm
from api.settings import ROOT, Settings
from api.warehouse import DuckDBWarehouse
from eval.gold import QUESTIONS, load_questions, run_gold
from eval.scoring import execution_match, is_ordered

RESULTS = Path(__file__).with_name("results")
ARMS = {"A": 0, "B": 5}  # retrieved examples in the SQL prompt


class PromptMeter:
    """Passes prompts through to the LLM and records the length of every SQL prompt sent."""

    def __init__(self, llm):
        self.llm, self.name, self.sql_chars = llm, llm.name, []

    def complete(self, prompt, config=None):
        if prompt.task == "sql":
            self.sql_chars.append(len(prompt.system) + len(prompt.user))
        return self.llm.complete(prompt, config)


def oracle_llm(questions: list[dict]) -> FakeLLM:
    routes = {
        q["question"]: q.get("route", "refuse" if q.get("expect") == "refusal" else "sql") for q in questions
    }
    gold = {q["question"]: q["sql"] for q in questions if q.get("sql")}
    return FakeLLM(sql=gold, route=lambda question: routes.get(question, "refuse"))


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]


def evaluate(questions: list[dict], deps: AgentDeps) -> dict[str, Any]:
    meter = PromptMeter(deps.llm)
    deps = dataclasses.replace(deps, llm=meter)
    graph = build_graph(deps)
    results = []
    for q in questions:
        # leave-one-out: a question's own example is never retrieved for it
        events, secs = timed(run_agent(q["question"], deps, graph, exclude_examples=[q["id"]]))
        final_event, final = events[-1] if events else ("error", {"code": "no_events"})
        row: dict[str, Any] = {
            "id": q["id"],
            "tags": q.get("tags", []),
            "expect": q.get("expect", "answer"),
            "outcome": final_event,
            "seconds": round(secs, 3),
        }
        if final_event == "answer":
            row["sql"] = final.get("sql")
        if final_event == "error":
            row["error_code"] = final.get("code")
        if q.get("expect") == "refusal":
            row["correct"] = final_event == "refusal"
        elif final_event != "answer":
            row["correct"] = False
        else:
            try:
                gold_cols, gold_rows = run_gold(deps.warehouse, q["sql"], deps.row_limit)
            except GuardrailError as e:
                row.update(correct=False, gold_error=f"guardrail: {e.code}")
            else:
                row["correct"] = execution_match(
                    gold_cols, gold_rows, final["columns"], final["rows"], ordered=is_ordered(q["sql"])
                )
        results.append(row)

    in_scope = [r for r in results if r["expect"] != "refusal"]
    out_scope = [r for r in results if r["expect"] == "refusal"]
    latencies = [r["seconds"] for r in results]
    tags = sorted({t for r in in_scope for t in r["tags"]})
    return {
        "n_in_scope": len(in_scope),
        "n_refusal": len(out_scope),
        "execution_accuracy": sum(r["correct"] for r in in_scope) / len(in_scope) if in_scope else None,
        "refusal_accuracy": sum(r["correct"] for r in out_scope) / len(out_scope) if out_scope else None,
        "in_scope_refused": sum(r["outcome"] == "refusal" for r in in_scope),
        "guardrail_rejections": sum(r.get("error_code") == "sql_rejected" for r in results),
        "errors": sum(r["outcome"] == "error" for r in results),
        "latency_p50_s": _percentile(latencies, 0.50),
        "latency_p95_s": _percentile(latencies, 0.95),
        "by_tag": {
            t: round(
                sum(r["correct"] for r in in_scope if t in r["tags"]) / sum(t in r["tags"] for r in in_scope),
                4,
            )
            for t in tags
        },
        "sql_prompt_chars_mean": round(statistics.mean(meter.sql_chars), 1) if meter.sql_chars else None,
        "per_question": {r["id"]: {"correct": r["correct"], "outcome": r["outcome"]} for r in results},
        "results": results,
    }


def _ollama_reachable(url: str) -> bool:
    import httpx

    try:
        return httpx.get(f"{url.rstrip('/')}/api/tags", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def _ollama_version(url: str) -> str | None:
    import httpx

    try:
        return httpx.get(f"{url.rstrip('/')}/api/version", timeout=3).json().get("version")
    except (httpx.HTTPError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--llm", choices=["fake", "ollama", "gemini"], default="fake")
    ap.add_argument("--arm", choices=sorted(ARMS), default="A", help="A/B arm: A = no examples, B = 5 (M5)")
    ap.add_argument("--warehouse", choices=["duckdb"], default="duckdb")
    ap.add_argument("--duckdb-path", type=Path, default=ROOT / "data" / "transitpulse.duckdb")
    ap.add_argument("--ids", help="comma-separated question ids to run (default: all)")
    ap.add_argument("--json", action="store_true", help="print the summary as one JSON object")
    ap.add_argument("--save-summary", action="store_true", help="also write summary-<llm>-<timestamp>.json")
    ap.add_argument(
        "--results-dir", type=Path, default=RESULTS, help="where to write results (default: eval/results)"
    )
    args = ap.parse_args(argv)

    questions = load_questions()
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if not args.duckdb_path.exists():
        print(f"no warehouse at {args.duckdb_path}", file=sys.stderr)
        return 2
    settings = Settings(_env_file=None, agent_llm=args.llm)
    if args.llm == "fake":
        llm = oracle_llm(questions)
    else:
        if args.llm == "ollama" and not _ollama_reachable(settings.ollama_url):
            print(f"Ollama isn't reachable at {settings.ollama_url}", file=sys.stderr)
            return 2
        llm = make_llm(settings)
    deps = AgentDeps(
        llm=llm,
        warehouse=DuckDBWarehouse(args.duckdb_path),
        budget=ByteBudget(settings.agent_daily_bytes),
        max_bytes=settings.agent_max_bytes,
        row_limit=settings.agent_row_limit,
        timeout_s=settings.agent_timeout_s,
        examples_k=ARMS[args.arm],
    )
    report = evaluate(questions, deps)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "llm": llm.name if args.llm != "fake" else "fake (oracle)",
        "warehouse": f"duckdb:{args.duckdb_path.name}",
        "run_at": stamp,
        "arm": args.arm,
        "examples_k": ARMS[args.arm],
        "eval_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(),
        **({"ollama_version": _ollama_version(settings.ollama_url)} if args.llm == "ollama" else {}),
        **{k: v for k, v in report.items() if k != "results"},
    }
    results_dir = args.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)
    detail = json.dumps({**summary, "results": report["results"]}, indent=2) + "\n"
    (results_dir / f"{args.llm}-{args.arm}-{stamp}.json").write_text(detail, encoding="utf-8", newline="\n")
    if args.save_summary:
        text = json.dumps(summary, indent=2) + "\n"
        name = f"summary-{args.llm}-{args.arm}-{stamp}.json"
        (results_dir / name).write_text(text, encoding="utf-8", newline="\n")
    if args.json:
        print(json.dumps(summary))
    else:
        for k, v in summary.items():
            if k != "per_question":
                print(f"{k:>22}: {v}")
        for r in report["results"]:
            if not r["correct"]:
                print(f"  wrong: {r['id']} -> {r['outcome']} {r.get('error_code', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
