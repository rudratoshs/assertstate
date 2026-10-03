"""db_delta policy evaluation (FEATURE-SPEC §5; DEVELOPMENT.md §16, §23).

Given a DbDeltaPolicy and the computed Delta, count matches per event-set and decide
whether the policy fires (-> FAIL). An event-set is *policed* iff it has a predicate OR a
non-zero max (so a count-only duplicate check polices `added` via max_added, while an
unconstrained event-set is ignored). GATING only under causal attribution (DEVELOPMENT §6.5):
on shared staging an observed delta is non-gating and can never FAIL.
"""

from __future__ import annotations

from dataclasses import dataclass

from assertstate.domain.contract import DbDeltaPolicy
from assertstate.domain.result import Attribution
from assertstate.domain.snapshot import Delta
from assertstate.oracle.delta.predicate import matches


@dataclass(frozen=True)
class PolicyResult:
    kind: str
    fired: bool
    gating: bool
    added_hits: int
    changed_hits: int
    removed_hits: int
    detail: str


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
    added_policed = policy.added_where is not None or policy.max_added != 0
    changed_policed = (
        policy.changed_where_before is not None
        or policy.changed_where_after is not None
        or policy.max_changed != 0
    )
    removed_policed = policy.removed_where is not None or policy.max_removed != 0

    added_hits = _count_added(policy, delta) if added_policed else 0
    changed_hits = _count_changed(policy, delta) if changed_policed else 0
    removed_hits = _count_removed(policy, delta) if removed_policed else 0

    fired = (
        (added_policed and added_hits > policy.max_added)
        or (changed_policed and changed_hits > policy.max_changed)
        or (removed_policed and removed_hits > policy.max_removed)
    )
    gating = attribution is Attribution.CAUSAL
    detail = (
        f"added={added_hits}/max{policy.max_added} "
        f"changed={changed_hits}/max{policy.max_changed} "
        f"removed={removed_hits}/max{policy.max_removed} "
        f"fired={fired} gating={gating}"
    )
    return PolicyResult(
        kind="db_delta",
        fired=fired,
        gating=gating,
        added_hits=added_hits,
        changed_hits=changed_hits,
        removed_hits=removed_hits,
        detail=detail,
    )
