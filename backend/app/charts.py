"""chart_spec is decided on the backend from the result shape: {type: line | bar | none, x, y}."""

import re
from datetime import date, datetime
from decimal import Decimal

MAX_BAR_CATEGORIES = 50
_TIME_NAME = re.compile(r"(^|_)(date|day|week|month|year|quarter|time|period)($|_)|^(yr|ym)$", re.I)
_ID_NAME = re.compile(r"(^|_)(id|ids|code|zip|postal|phone)$|^(id|rank|no|number)$", re.I)
_TIME_VALUE = re.compile(r"^\d{4}([-/]\d{1,2})?([-/]\d{1,2})?([ T].*)?$")


def _is_number(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _numeric_column(rows, i) -> bool:
    vals = [r[i] for r in rows if r[i] is not None]
    return bool(vals) and all(_is_number(v) for v in vals)


def _time_column(name: str, rows, i) -> bool:
    vals = [r[i] for r in rows if r[i] is not None]
    if not vals:
        return False
    if all(isinstance(v, (date, datetime)) for v in vals):
        return True
    if all(isinstance(v, str) and _TIME_VALUE.match(v) for v in vals):
        return True
    # A numeric year/month column, e.g. 2011 or 12, only counts when its name says so.
    return bool(_TIME_NAME.search(name)) and all(isinstance(v, int) for v in vals)


def chart_spec(columns: list[str], rows: list[list]) -> dict:
    none = {"type": "none"}
    if len(columns) != 2 or len(rows) < 2:
        return none
    for xi, yi in ((0, 1), (1, 0)):
        if not _numeric_column(rows, yi) or _ID_NAME.search(columns[yi]):
            continue  # nothing to plot, or the "number" is an identifier, not a measure
        if _numeric_column(rows, xi) and not _time_column(columns[xi], rows, xi):
            continue
        if _time_column(columns[xi], rows, xi):
            return {"type": "line", "x": columns[xi], "y": columns[yi]}
        if len(rows) <= MAX_BAR_CATEGORIES and len({r[xi] for r in rows}) == len(rows):
            return {"type": "bar", "x": columns[xi], "y": columns[yi]}
    return none
