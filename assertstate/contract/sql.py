"""Lightweight SQL projection analysis for db_delta validation (DEVELOPMENT.md §17).

Not a full SQL parser — just enough to (a) extract the set of output column names a
SELECT projects, and (b) reject volatile/nondeterministic projections at load.

Scope of the guarantee this enables (be precise — DEVELOPMENT §6.6): it protects
*predicate observability* — every column a `*_where` predicate reads must be projected,
so a predicate can never be silently blind. It does NOT make a db_delta universally
mutation-safe: a count-only policy (max_added/max_changed/max_removed with no predicate)
still observes only the projected columns by design, so the contract author must project
every column whose mutation matters. Fail-closed: anything we cannot analyze raises
SqlAnalysisError (-> a load error).
"""

from __future__ import annotations

import re

# Functions/keywords whose presence in a projection makes a snapshot nondeterministic.
_VOLATILE = (
    "now",
    "random",
    "clock_timestamp",
    "statement_timestamp",
    "timeofday",
    "current_timestamp",
    "current_date",
    "current_time",
    "localtimestamp",
    "localtime",
    "gen_random_uuid",
    "uuid_generate_v1",
    "uuid_generate_v4",
    "nextval",
)
_VOLATILE_RE = re.compile(r"\b(" + "|".join(_VOLATILE) + r")\b", re.IGNORECASE)
_SELECT_RE = re.compile(r"^\s*select\s+(?P<cols>.+?)\s+from\s", re.IGNORECASE | re.DOTALL)


class SqlAnalysisError(Exception):
    """The SELECT projection could not be analyzed. -> load error (fail-closed)."""


def _split_top_level(cols: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in cols:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _output_name(item: str) -> str:
    """The column name this projection item appears as in a result row (psycopg dict key)."""
    m = re.search(r"\s+as\s+(?P<alias>\"?[A-Za-z_][A-Za-z0-9_]*\"?)\s*$", item, re.IGNORECASE)
    if m:
        return m.group("alias").strip('"').lower()
    token = item.strip().strip('"')
    if "." in token:  # table.column -> column
        token = token.split(".")[-1]
    return token.lower()


def projected_columns(query: str) -> set[str] | None:
    """Return the set of lowercased output column names, or None for SELECT * (covers all).

    Raises SqlAnalysisError if the SELECT list cannot be parsed into simple columns.
    """
    m = _SELECT_RE.search(query)
    if not m:
        raise SqlAnalysisError("cannot locate SELECT ... FROM projection")
    cols = m.group("cols")
    if "*" in cols:
        return None  # covers all columns
    items = _split_top_level(cols)
    if not items:
        raise SqlAnalysisError("empty projection")
    names: set[str] = set()
    for item in items:
        if "(" in item and not re.search(r"\s+as\s+", item, re.IGNORECASE):
            # an expression with no alias -> we cannot name/guarantee it
            raise SqlAnalysisError(f"unaliased expression in projection: {item!r}")
        names.add(_output_name(item))
    return names


def has_volatile_projection(query: str) -> bool:
    m = _SELECT_RE.search(query)
    cols = m.group("cols") if m else query
    return bool(_VOLATILE_RE.search(cols))
