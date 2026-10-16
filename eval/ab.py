"""The M5 A/B test's statistics (docs/AB_TEST.md): arm A (no examples) vs arm B (5 retrieved examples).

    uv run --group agent python -m eval.ab [--llm ollama:llama3.1:8b] [--json]   # newest A and B summaries compared
    uv run --group agent python -m eval.ab --power [--json]                        # power analysis from arm A
    uv run --group agent python -m eval.ab --check     # exit 1 if a summary, docs/AB_TEST.md or the default k is off

Reads the newest summary-<llm>-<arm>-*.json per arm in eval/results/ (written by `eval.run_eval --arm A|B
--save-summary`). Exact two-sided McNemar on the discordant pairs, a paired percentile bootstrap of acc_B - acc_A
over questions (10,000 resamples, seed 0) and power by simulation (10,000, seed 0). Standard library only.
"""

import argparse
import json
import math
import random
import re
import sys
from functools import cache
from pathlib import Path

from eval.gold import load_questions

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(__file__).with_name("results")
DOC = ROOT / "docs" / "AB_TEST.md"
EVAL_SHA256 = (
    "45e5a1f238dbfa1363605a6f7c4dfb778be42d29e3437ac69c9e4b79b557277c"  # eval/questions.yaml, frozen
)
ARMS_K = {"A": 0, "B": 5}
ALPHA = 0.05
MIN_REFUSAL = 0.9  # B must keep refusing off-topic questions to ship
RESAMPLES = SIMS = 10_000
SEED = 0
BREAK_G = 0.05  # power model: B breaks each A-right question with this probability
EFFECTS = (0.05, 0.10, 0.15, 0.20)
TARGET_POWER = 0.8


# ---------------------------------------------------------------------------------------------------------------
# statistics


@cache
def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p: twice the smaller binomial(b + c, 1/2) tail, capped at 1."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def _quantile(xs: list[float], q: float) -> float:
    """numpy's default (linear) quantile of a sorted list."""
    pos = q * (len(xs) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def bootstrap_ci(
    a: list[bool], b: list[bool], resamples: int = RESAMPLES, seed: int = SEED
) -> tuple[float, float]:
    """95% paired percentile bootstrap of mean(b) - mean(a), resampling questions with replacement."""
    n = len(a)
    d = [int(y) - int(x) for x, y in zip(a, b, strict=True)]
    rng = random.Random(seed)
    stats = sorted(sum(d[i] for i in rng.choices(range(n), k=n)) / n for _ in range(resamples))
    return _quantile(stats, 0.025), _quantile(stats, 0.975)


def power(
    n: int, p_a: float, effect: float, g: float = BREAK_G, sims: int = SIMS, seed: int = SEED
) -> float | None:
    """P(McNemar p < ALPHA and B ahead) when B fixes each of A's wrong questions with probability f and breaks each
    right one with g, f chosen so the expected improvement is `effect`. None if no f in [0, 1] gives it."""
    right = round(p_a * n)
    wrong = n - right
    if wrong == 0:
        return None
    f = (effect * n + g * right) / wrong
    if not 0 <= f <= 1:
        return None
    rng = random.Random(seed)
    hits = 0
    for _ in range(sims):
        c, b = rng.binomialvariate(wrong, f), rng.binomialvariate(right, g)
        hits += c > b and mcnemar_exact(b, c) < ALPHA
    return hits / sims


def power_analysis(n: int, p_a: float) -> dict:
    """Power at +5/+10/+15/+20 points and the smallest whole-point improvement with power >= 80%."""
    mde = next(
        (pts for pts in range(1, 101) if (pw := power(n, p_a, pts / 100)) is not None and pw >= TARGET_POWER),
        None,
    )
    return {
        "n": n,
        "p_a": p_a,
        "g": BREAK_G,
        "sims": SIMS,
        "seed": SEED,
        "alpha": ALPHA,
        "power": {f"+{round(e * 100)}": power(n, p_a, e) for e in EFFECTS},
        "mde_points_at_80": mde,
    }


# ---------------------------------------------------------------------------------------------------------------
# summaries


def newest(llm: str, arm: str, results: Path = RESULTS) -> dict | None:
    """The newest summary for this LLM (e.g. ollama:llama3.1:8b) and arm, by run_at."""
    found = []
    for path in results.glob(f"summary-{llm.split(':')[0]}-{arm}-*.json"):
        s = json.loads(path.read_text(encoding="utf-8"))
        if s.get("llm") == llm and s.get("arm") == arm:
            found.append((s["run_at"], path.name, s))
    return max(found, key=lambda t: t[:2])[2] if found else None


def _arm(s: dict, in_scope: list[str], refusals: list[str]) -> dict:
    pq = s["per_question"]
    right = sum(pq[i]["correct"] for i in in_scope)
    return {
        "run_at": s["run_at"],
        "examples_k": s.get("examples_k"),
        "ollama_version": s.get("ollama_version"),
        "correct": right,
        "n": len(in_scope),
        "accuracy": right / len(in_scope),
        "refusal_correct": sum(pq[i]["correct"] for i in refusals),
        "n_refusal": len(refusals),
        "refusal_accuracy": sum(pq[i]["correct"] for i in refusals) / len(refusals),
        "errors": s.get("errors"),
        "in_scope_refused": s.get("in_scope_refused"),
        "latency_p50_s": s.get("latency_p50_s"),
        "latency_p95_s": s.get("latency_p95_s"),
        "sql_prompt_chars_mean": s.get("sql_prompt_chars_mean"),
        "by_tag": s.get("by_tag"),
    }


def compare(a: dict, b: dict, questions: list[dict]) -> dict:
    """Both arms paired by question id: accuracies, discordant counts, McNemar p, bootstrap CI and the decision."""
    in_scope = [q["id"] for q in questions if q.get("expect") != "refusal"]
    refusals = [q["id"] for q in questions if q.get("expect") == "refusal"]
    xa = [a["per_question"][i]["correct"] for i in in_scope]
    xb = [b["per_question"][i]["correct"] for i in in_scope]
    arm_a, arm_b = _arm(a, in_scope, refusals), _arm(b, in_scope, refusals)
    n_b = sum(x and not y for x, y in zip(xa, xb, strict=True))  # A right, B wrong
    n_c = sum(y and not x for x, y in zip(xa, xb, strict=True))  # A wrong, B right
    p = mcnemar_exact(n_b, n_c)
    lo, hi = bootstrap_ci(xa, xb)
    reasons = []
    if not p < ALPHA:
        reasons.append(f"McNemar p = {p:.3g} is not < {ALPHA}")
    if not arm_b["accuracy"] > arm_a["accuracy"]:
        reasons.append("acc_B is not above acc_A")
    if not arm_b["refusal_accuracy"] >= MIN_REFUSAL:
        reasons.append(f"B's refusal accuracy {arm_b['refusal_accuracy']:.2f} is below {MIN_REFUSAL}")
    return {
        "llm": a["llm"],
        "arms": {"A": arm_a, "B": arm_b},
        "b": n_b,
        "c": n_c,
        "mcnemar_p": p,
        "diff": arm_b["accuracy"] - arm_a["accuracy"],
        "ci": [lo, hi],
        "ship_b": not reasons,
        "default_examples_k": ARMS_K["B"] if not reasons else ARMS_K["A"],
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------------------------------------------
# the doc check


def _fmt(x: float) -> str:
    return f"{x + 0.0:+.4f}"


def doc_numbers(r: dict) -> dict[str, str]:
    """The Results section's numbers as they must be written."""
    a, b = r["arms"]["A"], r["arms"]["B"]
    return {
        "accuracy": f"{a['correct']}/{a['n']} = {a['accuracy']:.4f} | {b['correct']}/{b['n']} = {b['accuracy']:.4f}",
        "b": str(r["b"]),
        "c": str(r["c"]),
        "p": f"{r['mcnemar_p']:.3g}",
        "diff": _fmt(r["diff"]),
        "ci": f"[{_fmt(r['ci'][0])}, {_fmt(r['ci'][1])}]",
    }


PATTERNS = {
    "accuracy": r"Execution accuracy[^|\n]*\|\s*(\d+/\d+ = \d\.\d{4})\s*\|\s*(\d+/\d+ = \d\.\d{4})",
    "b": r"\bb = (\d+)",
    "c": r"\bc = (\d+)",
    "p": r"McNemar exact p = ([0-9.e+-]+\d)",
    "diff": r"acc_B - acc_A = ([+-]\d\.\d{4})",
    "ci": r"bootstrap CI (\[[+-]\d\.\d{4}, [+-]\d\.\d{4}\])",
}


def read_doc(text: str) -> dict[str, str | None]:
    """The same numbers as written in the doc's Results section (None where missing)."""
    m = re.search(r"^## Results\n(.*?)(?=^## )", text, re.S | re.M)
    section = m.group(1) if m else ""
    out: dict[str, str | None] = {}
    for key, pat in PATTERNS.items():
        hit = re.search(pat, section)
        out[key] = None if hit is None else " | ".join(hit.groups()) if key == "accuracy" else hit.group(1)
    return out


def check(llm: str, results: Path = RESULTS, doc: Path = DOC) -> list[str]:
    """Every reason the committed A/B is incomplete or disagrees with the doc or the default k."""
    from api.settings import Settings

    questions = load_questions()
    ids = {q["id"] for q in questions}
    problems = []
    arms = {arm: newest(llm, arm, results) for arm in ARMS_K}
    for arm, s in arms.items():
        if s is None:
            problems.append(f"no summary for arm {arm} ({llm}) in {results}")
            continue
        if set(s.get("per_question", {})) != ids:
            problems.append(f"arm {arm}: per_question does not cover all {len(ids)} questions")
        if s.get("eval_sha256") != EVAL_SHA256:
            problems.append(f"arm {arm}: eval_sha256 {s.get('eval_sha256')} is not the frozen {EVAL_SHA256}")
        if s.get("examples_k") != ARMS_K[arm]:
            problems.append(f"arm {arm}: examples_k {s.get('examples_k')} is not {ARMS_K[arm]}")
    if problems:
        return problems
    r = compare(arms["A"], arms["B"], questions)
    written = read_doc(doc.read_text(encoding="utf-8"))
    for key, want in doc_numbers(r).items():
        if written[key] != want:
            problems.append(f"{doc.name} Results: {key} is {written[key]!r}, recomputed {want!r}")
    default = Settings.model_fields["agent_examples_k"].default
    if default != r["default_examples_k"]:
        problems.append(
            f"Settings.agent_examples_k defaults to {default}; the decision rule gives {r['default_examples_k']}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--llm", default="ollama:llama3.1:8b", help="the summaries' llm field")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    ap.add_argument("--power", action="store_true", help="power analysis from arm A's accuracy")
    ap.add_argument(
        "--check", action="store_true", help="exit 1 if the A/B is incomplete or the doc disagrees"
    )
    args = ap.parse_args(argv)

    if args.check:
        problems = check(args.llm)
        for p in problems:
            print(p, file=sys.stderr)
        if not problems:
            print(f"A/B ({args.llm}): summaries, {DOC.name} and the default examples_k agree")
        return 1 if problems else 0

    questions = load_questions()
    a = newest(args.llm, "A")
    if a is None:
        print(f"no arm A summary for {args.llm}", file=sys.stderr)
        return 2
    if args.power:
        in_scope = [q["id"] for q in questions if q.get("expect") != "refusal"]
        acc = sum(a["per_question"][i]["correct"] for i in in_scope) / len(in_scope)
        out = {"arm_a_run_at": a["run_at"], **power_analysis(len(in_scope), acc)}
    else:
        b = newest(args.llm, "B")
        if b is None:
            print(f"no arm B summary for {args.llm}", file=sys.stderr)
            return 2
        out = compare(a, b, questions)
    if args.json:
        print(json.dumps(out))
    else:
        for k, v in out.items():
            print(f"{k:>20}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
