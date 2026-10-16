"""The agent's few-shot pool (arm B of the M5 A/B test, docs/AB_TEST.md): the in-scope `route: sql` questions of
eval/questions.yaml with their gold SQL, exported to api/agent/examples.json so the API image has them without eval/.

    uv run python -m eval.examples           # exit 1 if api/agent/examples.json is out of date
    uv run python -m eval.examples --write   # rewrite it
"""

import argparse
import json
import sys

from api.agent.prompts import EXAMPLES_PATH
from eval.gold import load_questions


def build() -> list[dict]:
    return [
        {"id": q["id"], "question": q["question"], "sql": " ".join(q["sql"].split()), "tags": q["tags"]}
        for q in load_questions()
        if q.get("expect") != "refusal" and q.get("route", "sql") == "sql"
    ]


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help=f"rewrite {EXAMPLES_PATH.name}")
    args = ap.parse_args(argv)
    text = render()
    if args.write:
        EXAMPLES_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"{len(build())} examples -> {EXAMPLES_PATH}")
        return 0
    current = (
        EXAMPLES_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") if EXAMPLES_PATH.exists() else ""
    )
    if current != text:
        print(f"{EXAMPLES_PATH} is out of date: run python -m eval.examples --write", file=sys.stderr)
        return 1
    print(f"{EXAMPLES_PATH}: in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
