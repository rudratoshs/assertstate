"""P0-16 comparators + P0-17 db_delta policy (pure, no DB)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from assertstate.domain.comparator import Comparator
from assertstate.domain.contract import DbDeltaPolicy, SettlementConfig
from assertstate.domain.result import Attribution
from assertstate.domain.snapshot import Delta
from assertstate.verifier.expect.comparators import ComparatorError, canon_v1, compare
from assertstate.verifier.policy_engine.db_delta import evaluate_db_delta

DRAIN = SettlementConfig(mode="drain", queue="p", timeout_s=10)


# --- comparators ---
def test_equals_is_strict() -> None:
    assert compare(Comparator.EQUALS, "paid", "paid") is True
    assert compare(Comparator.EQUALS, Decimal("98.70"), "98.70") is True
    assert compare(Comparator.EQUALS, Decimal("98.7"), "98.70") is False  # strict


def test_eq_canonical_is_numeric_aware() -> None:
    assert compare(Comparator.EQ_CANONICAL, Decimal("98.70"), "98.7") is True
    assert compare(Comparator.EQ_CANONICAL, "98.700", "98.7") is True
    assert canon_v1("  ACME  ") == "acme"


def test_in_membership() -> None:
    assert compare(Comparator.IN, "b", ("a", "b")) is True
    assert compare(Comparator.IN, "z", ("a", "b")) is False


def test_numeric_ordering_and_fail_closed() -> None:
    assert compare(Comparator.LT, Decimal("5"), Decimal("10")) is True
    assert compare(Comparator.GTE, Decimal("10"), Decimal("10")) is True
    with pytest.raises(ComparatorError):
        compare(Comparator.LT, "not-a-number", Decimal("10"))


def test_regex_fullmatch() -> None:
    assert compare(Comparator.REGEX, "abc123", r"[a-z]+\d+") is True
    assert compare(Comparator.REGEX, "abc123x", r"[a-z]+\d+") is False


# --- db_delta policy ---
def _policy(**over: object) -> DbDeltaPolicy:
    base: dict = dict(query="SELECT id FROM payments", settle=DRAIN)
    base.update(over)
    return DbDeltaPolicy(**base)


def _delta(added=None, changed=None, removed=None) -> Delta:
    return Delta("q", added=added or {}, removed=removed or {}, changed=changed or {})


def test_duplicate_policy_fires_on_second_added() -> None:
    p = _policy(max_added=1)
    assert evaluate_db_delta(p, _delta(added={1: {}, 2: {}}), Attribution.CAUSAL).fired is True
    assert evaluate_db_delta(p, _delta(added={1: {}}), Attribution.CAUSAL).fired is False


def test_tenant_added_policy_fires() -> None:
    p = _policy(added_where="tenant_id != 'acme'", max_added=0)
    bad = _delta(added={1: {"tenant_id": "globex"}})
    ok = _delta(added={1: {"tenant_id": "acme"}})
    assert evaluate_db_delta(p, bad, Attribution.CAUSAL).fired is True
    assert evaluate_db_delta(p, ok, Attribution.CAUSAL).fired is False


def test_tenant_steal_via_changed_where() -> None:
    p = _policy(
        changed_where_before="tenant_id = 'acme'", changed_where_after="tenant_id != 'acme'"
    )
    steal = _delta(changed={1: ({"tenant_id": "acme"}, {"tenant_id": "globex"})})
    assert evaluate_db_delta(p, steal, Attribution.CAUSAL).fired is True
    # an unrelated change to an already-non-acme row must NOT fire
    unrelated = _delta(changed={2: ({"tenant_id": "globex"}, {"tenant_id": "globex"})})
    assert evaluate_db_delta(p, unrelated, Attribution.CAUSAL).fired is False


def test_removed_where_fires() -> None:
    p = _policy(removed_where="status = 'active'", max_removed=0)
    assert evaluate_db_delta(p, _delta(removed={1: {"status": "active"}}), Attribution.CAUSAL).fired


def test_unpoliced_eventset_is_ignored() -> None:
    # duplicate policy (max_added:1 only) must NOT fire on an unrelated changed row.
    p = _policy(max_added=1)
    d = _delta(added={1: {}}, changed={2: ({"x": 1}, {"x": 2})})
    assert evaluate_db_delta(p, d, Attribution.CAUSAL).fired is False


def test_observed_attribution_is_non_gating() -> None:
    p = _policy(max_added=1)
    r = evaluate_db_delta(p, _delta(added={1: {}, 2: {}}), Attribution.OBSERVED)
    assert r.fired is True and r.gating is False  # fired, but cannot gate on shared staging
