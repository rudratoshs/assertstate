"""Typed comparators for expect.db (FEATURE-SPEC §2.3; DEVELOPMENT.md §22).

Deterministic, no LLM. `canon-v1` is a minimal, versioned canonicalizer: numeric-aware
(so "98.70" == "98.7" == Decimal('98.70')) and otherwise whitespace-collapsed + casefolded.
Ordering comparators fail closed on non-finite values (raise, -> trial ERROR; never a
silent pass).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from assertstate.domain.comparator import Comparator, ComparatorValue

CANONICALIZER_VERSION = "canon-v1"


class ComparatorError(Exception):
    """A comparator could not be evaluated (e.g. non-finite numeric). -> trial ERROR."""


def canon_v1(value: Any) -> str:
    """Canonical string form: numeric if parseable, else trimmed/collapsed + casefolded."""
    s = str(value).strip()
    try:
        d = Decimal(s)
        if d.is_finite():
            return format(d.normalize(), "f")
    except InvalidOperation:
        pass
    return " ".join(s.split()).casefold()


def _to_decimal(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ComparatorError(f"not numeric: {value!r}") from exc
    if not d.is_finite():
        raise ComparatorError(f"non-finite value (fail-closed): {value!r}")
    return d


def compare(comparator: Comparator, observed: Any, expected: ComparatorValue) -> bool:
    """Compare a non-null observed value against the contract operand (value comparators only).

    ABSENT/ANY are presence checks handled by the evaluator, not here.
    """
    if comparator is Comparator.EQUALS:
        return str(observed) == str(expected)
    if comparator is Comparator.EQ_CANONICAL:
        return canon_v1(observed) == canon_v1(expected)
    if comparator is Comparator.IN:
        assert isinstance(expected, tuple)
        return str(observed) in expected
    if comparator in (Comparator.LT, Comparator.LTE, Comparator.GT, Comparator.GTE):
        left, right = _to_decimal(observed), _to_decimal(expected)
        if comparator is Comparator.LT:
            return left < right
        if comparator is Comparator.LTE:
            return left <= right
        if comparator is Comparator.GT:
            return left > right
        return left >= right  # GTE
    if comparator is Comparator.REGEX:
        assert isinstance(expected, str)
        return re.fullmatch(expected, str(observed)) is not None
    raise ComparatorError(f"{comparator} is a presence check, not a value comparator")
