"""P0-09 predicate evaluator (DEVELOPMENT.md §16; safe, no eval)."""

from __future__ import annotations

import pytest

from assertstate.oracle.delta.predicate import PredicateError, matches, referenced_columns


def test_string_equals_and_not_equals() -> None:
    assert matches("tenant_id = 'acme'", {"tenant_id": "acme"}) is True
    assert matches("tenant_id != 'acme'", {"tenant_id": "globex"}) is True
    assert matches("tenant_id != 'acme'", {"tenant_id": "acme"}) is False
    assert matches("tenant_id <> 'acme'", {"tenant_id": "globex"}) is True


def test_numeric_ordering() -> None:
    assert matches("amount > 100", {"amount": "150"}) is True
    assert matches("amount > 100", {"amount": "98.70"}) is False
    assert matches("amount <= 98.70", {"amount": "98.70"}) is True


def test_and_or_and_parens() -> None:
    row = {"tenant_id": "globex", "status": "active"}
    assert matches("tenant_id != 'acme' AND status = 'active'", row) is True
    assert matches("tenant_id = 'acme' OR status = 'active'", row) is True
    assert matches("(tenant_id = 'acme' OR status = 'active') AND tenant_id != 'acme'", row) is True
    assert matches("tenant_id = 'acme' AND status = 'active'", row) is False


def test_null_comparison_is_not_matched() -> None:
    # SQL three-valued logic: NULL != 'acme' is unknown -> not matched.
    assert matches("tenant_id != 'acme'", {"tenant_id": None}) is False
    assert matches("tenant_id = 'acme'", {"tenant_id": None}) is False


def test_missing_column_raises() -> None:
    with pytest.raises(PredicateError):
        matches("tenant_id != 'acme'", {"other": "x"})


def test_quoted_quote_escaping() -> None:
    assert matches("name = 'O''Brien'", {"name": "O'Brien"}) is True


@pytest.mark.parametrize("bad", ["tenant_id !! 'x'", "AND tenant_id = 'x'", "tenant_id =", "()"])
def test_malformed_predicates_raise(bad: str) -> None:
    with pytest.raises(PredicateError):
        matches(bad, {"tenant_id": "x"})


def test_cross_tenant_steal_pattern() -> None:
    # The FEATURE-SPEC §5.1 changed_where steal: before acme, after not-acme.
    assert matches("tenant_id = 'acme'", {"tenant_id": "acme"}) is True
    assert matches("tenant_id != 'acme'", {"tenant_id": "globex"}) is True


def test_referenced_columns() -> None:
    assert referenced_columns("tenant_id != 'acme'") == {"tenant_id"}
    assert referenced_columns("a = '1' AND b > 2 OR c = 'x'") == {"a", "b", "c"}
    with pytest.raises(PredicateError):
        referenced_columns("!! bad")
