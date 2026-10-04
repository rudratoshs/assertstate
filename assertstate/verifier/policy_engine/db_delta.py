"""db_delta policy evaluation (FEATURE-SPEC §5; DEVELOPMENT.md §16, §23).

Given a DbDeltaPolicy and the computed Delta, count matches per event-set and decide
whether the policy fires (-> FAIL). An event-set is *policed* iff it has a predicate OR an
explicit cap (including 0 — "zero allowed"); an omitted (None) cap with no predicate leaves the
event-set ignored. GATING only under causal attribution (DEVELOPMENT §6.5):
on shared staging an observed delta is non-gating and can never FAIL.
"""

from __future__ import annotations

from assertstate.domain.contract import DbDeltaPolicy
from assertstate.domain.result import Attribution
from assertstate.domain.snapshot import Delta
from assertstate.oracle.delta.predicate import matches
from assertstate.verifier.policy_engine.base import PolicyResult


def _count_added(policy: DbDeltaPolicy, delta: Delta) -> int:
    return sum(
        1
        for row in delta.added.values()
        if policy.added_where is None or matches(policy.added_where, row)
    )


def _count_removed(policy: DbDeltaPolicy, delta: Delta) -> int:
    return sum(
        1
        for row in delta.removed.values()
        if policy.removed_where is None or matches(policy.removed_where, row)
    )


def _count_changed(policy: DbDeltaPolicy, delta: Delta) -> int:
    hits = 0
    for before, after in delta.changed.values():
        before_ok = policy.changed_where_before is None or matches(
            policy.changed_where_before, before
        )
        after_ok = policy.changed_where_after is None or matches(policy.changed_where_after, after)
        if before_ok and after_ok:
            hits += 1
    return hits


def evaluate_db_delta(
    policy: DbDeltaPolicy, delta: Delta, attribution: Attribution
) -> PolicyResult:
    # An event-set is policed iff it has a predicate OR an explicit cap (incl. 0). A cap of 0
    # therefore means "zero allowed" (strictest), never "ignore" — the false-PASS footgun fixed.
    added_policed = policy.added_where is not None or policy.max_added is not None
    changed_policed = (
        policy.changed_where_before is not None
        or policy.changed_where_after is not None
        or policy.max_changed is not None
    )
    removed_policed = policy.removed_where is not None or policy.max_removed is not None

    cap_added = policy.max_added if policy.max_added is not None else 0
    cap_changed = policy.max_changed if policy.max_changed is not None else 0
    cap_removed = policy.max_removed if policy.max_removed is not None else 0

    # Count every event-set always so `detail` reports the true delta even when unpoliced.
    added_hits = _count_added(policy, delta)
    changed_hits = _count_changed(policy, delta)
    removed_hits = _count_removed(policy, delta)

    fired = (
        (added_policed and added_hits > cap_added)
        or (changed_policed and changed_hits > cap_changed)
        or (removed_policed and removed_hits > cap_removed)
    )
    gating = attribution is Attribution.CAUSAL
    detail = (
        f"added={added_hits}/{('max' + str(cap_added)) if added_policed else 'unpoliced'} "
        f"changed={changed_hits}/{('max' + str(cap_changed)) if changed_policed else 'unpoliced'} "
        f"removed={removed_hits}/{('max' + str(cap_removed)) if removed_policed else 'unpoliced'} "
        f"fired={fired} gating={gating}"
    )
    return PolicyResult(kind="db_delta", fired=fired, gating=gating, detail=detail)
