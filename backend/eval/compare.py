"""Execution-accuracy comparison: do the predicted rows match the gold rows?

Follows the BIRD EX metric (set equality of row tuples, column order positional), except that
when the gold query has a top-level ORDER BY the row order must match too, per SPEC.md.
"""

import math
from datetime import date, datetime
from decimal import Decimal

import sqlglot
from sqlglot import exp


def gold_is_ordered(gold_sql: str) -> bool:
    try:
        tree = sqlglot.parse_one(gold_sql, read="postgres")
    except sqlglot.errors.SqlglotError:
        return False
    return tree.args.get("order") is not None


def _norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float, Decimal)):
        f = float(v)
        return None if math.isnan(f) else round(f, 4)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def _rows(rows) -> list[tuple]:
    return [tuple(_norm(v) for v in r) for r in rows]


def results_match(pred_rows, gold_rows, ordered: bool = False) -> bool:
    p, g = _rows(pred_rows), _rows(gold_rows)
    if ordered:
        return p == g
    return set(p) == set(g)
