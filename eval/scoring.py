"""Execution accuracy: does the agent's answer table hold the same data as the gold query's?

* rows are compared as multisets, or in order when the gold SQL ends in ORDER BY ... LIMIT (a "top N" question)
* column order and names don't matter when the column counts match (every permutation is tried, up to 6 columns)
* numbers match at relative tolerance 1e-4 (ints and floats alike); dates/timestamps compare as ISO strings
"""

import datetime as dt
import itertools
import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import sqlglot
from sqlglot import exp

REL_TOL = 1e-4
MAX_PERMUTED_COLUMNS = 6


def normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def values_equal(a: Any, b: Any) -> bool:
    a, b = normalize(a), normalize(b)
    if _is_number(a) and _is_number(b):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-9)
    if isinstance(a, str) and isinstance(b, str) and len(a) >= 10 and len(b) >= 10 and a[4] == "-" == b[4]:
        # a DATE and a midnight TIMESTAMP of the same day, or ISO strings with different precision
        return a.replace("T", " ").removesuffix(" 00:00:00") == b.replace("T", " ").removesuffix(" 00:00:00")
    return a == b


def rows_equal(a: Sequence, b: Sequence) -> bool:
    return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b, strict=True))


def rows_match(gold: Sequence[Sequence], pred: Sequence[Sequence], ordered: bool) -> bool:
    if len(gold) != len(pred):
        return False
    if ordered:
        return all(rows_equal(g, p) for g, p in zip(gold, pred, strict=True))
    unused = list(range(len(pred)))
    for g in gold:
        hit = next((i for i in unused if rows_equal(g, pred[i])), None)
        if hit is None:
            return False
        unused.remove(hit)
    return True


def execution_match(
    gold_columns: Sequence[str],
    gold_rows: Sequence[Sequence],
    pred_columns: Sequence[str],
    pred_rows: Sequence[Sequence],
    ordered: bool = False,
) -> bool:
    n = len(gold_columns)
    if len(pred_columns) != n:
        return False
    if n > MAX_PERMUTED_COLUMNS:
        return rows_match(gold_rows, pred_rows, ordered)
    for perm in itertools.permutations(range(n)):
        permuted = [[row[i] for i in perm] for row in pred_rows]
        if rows_match(gold_rows, permuted, ordered):
            return True
    return False


def is_ordered(gold_sql: str) -> bool:
    """True when the gold query's outermost level has both ORDER BY and LIMIT, so row order is part of the answer."""
    tree = sqlglot.parse_one(gold_sql, read="bigquery")
    return isinstance(tree, exp.Query) and bool(tree.args.get("order")) and bool(tree.args.get("limit"))
