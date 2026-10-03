"""Restricted predicate evaluator for db_delta *_where clauses (DEVELOPMENT.md §16, OID-3).

NO eval(). A tiny recursive-descent parser over a safe grammar:

    expr    := or_expr
    or_expr := and_expr ( OR and_expr )*
    and_expr:= term ( AND term )*
    term    := '(' expr ')' | comparison
    comp    := column OP operand
    OP      := '=' | '!=' | '<>' | '<' | '<=' | '>' | '>='
    operand := quoted-string | number

Semantics (fail-closed): a column not present in the row raises PredicateError (-> ERROR;
we never silently treat a missing projected column as "no match"). Any comparison involving
NULL yields False (SQL three-valued 'unknown' collapses to not-matched).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

Row = Mapping[str, Any]

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
      (?P<lparen>\() |
      (?P<rparen>\)) |
      (?P<op><>|!=|<=|>=|=|<|>) |
      (?P<and>\bAND\b) |
      (?P<or>\bOR\b) |
      (?P<string>'(?:[^']|'')*') |
      (?P<number>-?\d+(?:\.\d+)?) |
      (?P<ident>[A-Za-z_][A-Za-z0-9_.]*)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


class PredicateError(Exception):
    """A predicate could not be parsed or evaluated. -> trial ERROR."""


def _tokenize(s: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(s):
        if s[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(s, pos)
        if not m or m.lastgroup is None:
            raise PredicateError(f"cannot tokenize predicate near: {s[pos : pos + 20]!r}")
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    return tokens


Predicate = Callable[[Row], bool]


def _cmp(col: str, op: str, literal: Any) -> Predicate:
    def run(row: Row) -> bool:
        if col not in row:
            raise PredicateError(f"predicate references column not in result: {col!r}")
        value = row[col]
        if value is None:
            return False  # NULL comparison -> unknown -> not matched
        if op in ("=", "!=", "<>"):
            equal = _loose_equal(value, literal)
            return equal if op == "=" else not equal
        # ordering comparators are numeric
        try:
            left, right = Decimal(str(value)), Decimal(str(literal))
        except (InvalidOperation, ValueError) as exc:
            raise PredicateError(
                f"non-numeric ordering comparison: {value!r} {op} {literal!r}"
            ) from exc
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        return left >= right  # ">="

    return run


def _loose_equal(value: Any, literal: Any) -> bool:
    # Numbers compare numerically; everything else as strings.
    if isinstance(literal, Decimal):
        try:
            return Decimal(str(value)) == literal
        except (InvalidOperation, ValueError):
            return False
    return str(value) == str(literal)


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self._t = tokens
        self._i = 0

    def _peek(self) -> tuple[str, str] | None:
        return self._t[self._i] if self._i < len(self._t) else None

    def _next(self) -> tuple[str, str]:
        tok = self._peek()
        if tok is None:
            raise PredicateError("unexpected end of predicate")
        self._i += 1
        return tok

    def parse(self) -> Predicate:
        pred = self._or()
        if self._peek() is not None:
            raise PredicateError(f"trailing tokens in predicate: {self._t[self._i :]!r}")
        return pred

    def _or(self) -> Predicate:
        left = self._and()
        while (tok := self._peek()) and tok[0] == "or":
            self._next()
            right = self._and()
            left = _or_fn(left, right)
        return left

    def _and(self) -> Predicate:
        left = self._term()
        while (tok := self._peek()) and tok[0] == "and":
            self._next()
            right = self._term()
            left = _and_fn(left, right)
        return left

    def _term(self) -> Predicate:
        tok = self._peek()
        if tok is None:
            raise PredicateError("expected comparison or '('")
        if tok[0] == "lparen":
            self._next()
            inner = self._or()
            closing = self._next()
            if closing[0] != "rparen":
                raise PredicateError("missing ')'")
            return inner
        return self._comparison()

    def _comparison(self) -> Predicate:
        ident = self._next()
        if ident[0] != "ident":
            raise PredicateError(f"expected a column name, got {ident[1]!r}")
        op_tok = self._next()
        if op_tok[0] != "op":
            raise PredicateError(f"expected a comparison operator, got {op_tok[1]!r}")
        operand = self._next()
        if operand[0] == "string":
            literal: Any = operand[1][1:-1].replace("''", "'")
        elif operand[0] == "number":
            literal = Decimal(operand[1])
        else:
            raise PredicateError(f"expected a literal, got {operand[1]!r}")
        return _cmp(ident[1], op_tok[1], literal)


def _and_fn(a: Predicate, b: Predicate) -> Predicate:
    return lambda row: a(row) and b(row)


def _or_fn(a: Predicate, b: Predicate) -> Predicate:
    return lambda row: a(row) or b(row)


def compile_predicate(expr: str) -> Predicate:
    tokens = _tokenize(expr)
    if not tokens:
        raise PredicateError("empty predicate")
    return _Parser(tokens).parse()


def matches(expr: str, row: Row) -> bool:
    return compile_predicate(expr)(row)


def referenced_columns(expr: str) -> set[str]:
    """The column names a predicate references (every ident is a column in this grammar).

    Raises PredicateError if the predicate cannot be tokenized. Used at load time to
    prove a db_delta's predicate only reads columns the query projects (DEVELOPMENT §17).
    """
    return {val.lower() for kind, val in _tokenize(expr) if kind == "ident"}
