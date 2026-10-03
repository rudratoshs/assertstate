"""Comparators and their typed operands (DEVELOPMENT.md §7).

The operand type is determined by the comparator; it is NOT a single ``str | None``:
    equals / eq_canonical / regex -> str      (money kept as STRING, parsed to Decimal at compare)
    in                            -> tuple[str, ...]
    lt / lte / gt / gte           -> Decimal   (numeric; fail-closed on non-finite)
    absent / any                  -> None      (no operand)
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum


class Comparator(Enum):
    EQUALS = "equals"
    EQ_CANONICAL = "eq_canonical"
    IN = "in"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    REGEX = "regex"
    ABSENT = "absent"
    ANY = "any"


# The union of all comparator operand shapes.
ComparatorValue = str | Decimal | tuple[str, ...] | None

#: Comparators whose operand is a bare string.
STRING_COMPARATORS = frozenset({Comparator.EQUALS, Comparator.EQ_CANONICAL, Comparator.REGEX})
#: Comparators whose operand is numeric (parsed to Decimal).
NUMERIC_COMPARATORS = frozenset({Comparator.LT, Comparator.LTE, Comparator.GT, Comparator.GTE})
#: Comparators that take a list operand.
LIST_COMPARATORS = frozenset({Comparator.IN})
#: Comparators that take no operand.
NULLARY_COMPARATORS = frozenset({Comparator.ABSENT, Comparator.ANY})


def expected_operand_kind(c: Comparator) -> str:
    """Return a human label for the operand shape a comparator requires."""
    if c in STRING_COMPARATORS:
        return "string"
    if c in NUMERIC_COMPARATORS:
        return "numeric"
    if c in LIST_COMPARATORS:
        return "list"
    return "none"
