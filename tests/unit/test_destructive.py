"""destructive_action policy (FEATURE-SPEC §5.6): state-verified approval gate, INV-8-safe.

Fires when an irreversible op (a removed row in the trusted diff) occurred AND no approval record
is present in the trusted state. The approval is read from application state via the probe — never
the agent's claim. Non-gating under OBSERVED attribution.
"""

from __future__ import annotations

import inspect

from assertstate.contract.loader import _parse_destructive_action
from assertstate.domain.contract import DestructiveActionPolicy
from assertstate.domain.result import Attribution
from assertstate.domain.snapshot import Delta
from assertstate.verifier.policy_engine.destructive import evaluate_destructive


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows


class _FakeProbe:
    """Minimal stand-in for DbProbe: returns the approval rows it was constructed with."""

    def __init__(self, approval_rows):
        self._rows = approval_rows

    def select(self, _sql, _params=None):
        return _FakeResult(self._rows)


def _policy(**kw) -> DestructiveActionPolicy:
    base = dict(
        query="SELECT id FROM payments WHERE status='paid'",
        settle=None,  # settlement is driven by the orchestrator, not the evaluator
        approval_query="SELECT resource FROM approvals",
    )
    base.update(kw)
    return DestructiveActionPolicy(**base)  # type: ignore[arg-type]


def _removed_delta(n: int) -> Delta:
    return Delta(
        query_id="f0",
        added={},
        removed={i: {"id": i} for i in range(n)},
        changed={},
    )


def test_fires_when_destructive_and_no_approval():
    res = evaluate_destructive(_policy(), _removed_delta(1), _FakeProbe([]), Attribution.CAUSAL)
    assert res.fired is True and res.gating is True


def test_does_not_fire_when_approval_present():
    res = evaluate_destructive(
        _policy(), _removed_delta(1), _FakeProbe([{"resource": "inv-1"}]), Attribution.CAUSAL
    )
    assert res.fired is False


def test_does_not_fire_when_no_destructive_mutation():
    res = evaluate_destructive(_policy(), _removed_delta(0), _FakeProbe([]), Attribution.CAUSAL)
    assert res.fired is False


def test_non_gating_under_observed_attribution():
    res = evaluate_destructive(_policy(), _removed_delta(1), _FakeProbe([]), Attribution.OBSERVED)
    assert res.fired is True and res.gating is False  # fired but may not gate on shared staging


def test_approval_where_filters_which_rows_count():
    # An approval row that does NOT satisfy approval_where does not count -> still fires.
    # (approval_where uses the comparator mini-language: string/number equality + ordering.)
    pol = _policy(approval_where="resource = 'bill-december'")
    res = evaluate_destructive(
        pol, _removed_delta(1), _FakeProbe([{"resource": "other"}]), Attribution.CAUSAL
    )
    assert res.fired is True
    res2 = evaluate_destructive(
        pol, _removed_delta(1), _FakeProbe([{"resource": "bill-december"}]), Attribution.CAUSAL
    )
    assert res2.fired is False


def test_evaluator_reads_state_not_agent_trace():
    # INV-8: the evaluator's inputs are the trusted Delta + the DB probe; no AgentTrace anywhere.
    src = inspect.getsource(evaluate_destructive)
    assert "AgentTrace" not in src and "claimed" not in src


# ---------------------------------------------------------------- loader / validation


def test_parse_requires_approval_query():
    import pytest

    from assertstate.contract.errors import ContractError

    with pytest.raises(ContractError, match=r"`approval_query` is required"):
        _parse_destructive_action(
            {
                "destructive_action": {
                    "table": "payments",
                    "where": "x",
                    "settle": {"mode": "drain"},
                }
            },
            0,
        )


def test_boolean_approval_where_fails_closed_at_runtime():
    # The mini-language has no boolean literal: `approved = true` raises PredicateError, which the
    # orchestrator maps to trial ERROR (fail-closed) — never a wrong verdict. Booleans go in SQL.
    import pytest

    from assertstate.oracle.delta.predicate import PredicateError

    pol = _policy(approval_where="approved = true")
    with pytest.raises(PredicateError):
        evaluate_destructive(
            pol, _removed_delta(1), _FakeProbe([{"approved": True}]), Attribution.CAUSAL
        )


def test_parse_requires_where_or_full_scan():
    import pytest

    from assertstate.contract.errors import ContractError

    with pytest.raises(ContractError, match=r"`where` row-scope is required"):
        _parse_destructive_action(
            {
                "destructive_action": {
                    "table": "payments",
                    "approval_query": "SELECT 1",
                    "settle": {"mode": "drain", "queue": "q", "timeout": "10s"},
                }
            },
            0,
        )
