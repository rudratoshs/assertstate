"""Cross-field semantic validation (FEATURE-SPEC §2, §5, §8; DEVELOPMENT.md §7).

Operates on the typed Contract. Errors block execution; warnings are advisory
(e.g. the expect-causality note, or a P0-unsupported settlement mode).
"""

from __future__ import annotations

from assertstate.contract.errors import ValidationReport
from assertstate.contract.sql import (
    SqlAnalysisError,
    has_volatile_projection,
    projected_columns,
)
from assertstate.domain.contract import (
    SETTLE_MODES,
    Contract,
    DbDeltaPolicy,
)
from assertstate.oracle.delta.predicate import PredicateError, referenced_columns


def _validate_statistics(c: Contract, report: ValidationReport) -> None:
    s = c.statistics
    if not (0.0 < s.confidence < 1.0):
        report.errors.append("statistics.confidence: must be in (0, 1)")
    if not (0.0 <= s.pass_threshold <= 1.0):
        report.errors.append("statistics.pass_threshold: must be in [0, 1]")
    if not (0.0 <= s.max_error_rate <= 1.0):
        report.errors.append("statistics.max_error_rate: must be in [0, 1]")
    if not (0.0 <= s.max_skip_rate <= 1.0):
        report.errors.append("statistics.max_skip_rate: must be in [0, 1]")
    if s.trials < 1:
        report.errors.append("statistics.trials: must be >= 1")
    if s.min_valid_trials > s.trials:
        report.errors.append("statistics.min_valid_trials: cannot exceed trials")
    if s.side not in ("one_sided", "two_sided"):
        report.errors.append("statistics.side: must be one_sided or two_sided")


def _validate_db_delta(policy: DbDeltaPolicy, idx: int, report: ValidationReport) -> None:
    where = f"forbid[{idx}].db_delta"
    if policy.settle.mode not in SETTLE_MODES:
        report.errors.append(
            f"{where}.settle.mode: unknown {policy.settle.mode!r} (one of {sorted(SETTLE_MODES)})"
        )
    elif not policy.settle.runnable:  # run_correlated is P2/deferred
        report.warnings.append(
            f"{where}.settle.mode={policy.settle.mode}: valid spec, but not runnable yet "
            f"(run_correlated is P2); runnable modes are drain and bounded"
        )
    # Per-mode required fields.
    if policy.settle.mode == "drain":
        if not policy.settle.queue:
            report.errors.append(f"{where}.settle: drain requires a `queue` (workflow-owned)")
        if policy.settle.timeout_s is None:
            report.errors.append(f"{where}.settle: drain requires a `timeout`")
    elif policy.settle.mode == "bounded":
        if policy.settle.max_wait_s is None:
            report.errors.append(f"{where}.settle: bounded requires a `max_wait`")

    has_pred = any(
        [
            policy.added_where,
            policy.changed_where_before,
            policy.changed_where_after,
            policy.removed_where,
        ]
    )
    if not has_pred:
        report.warnings.append(
            f"{where}: no added_where/changed_where/removed_where — the policy only caps row counts"
        )

    _validate_projection(policy, where, report)


def _validate_projection(policy: DbDeltaPolicy, where: str, report: ValidationReport) -> None:
    """Fail-closed PREDICATE observability (DEVELOPMENT §17): every column a `*_where`
    predicate reads must be projected, so a predicate is never silently blind, and the
    projection must be deterministic. This does NOT make the policy universally
    mutation-safe — a count-only policy still sees only the projected columns by design;
    the author must project every column whose mutation matters (DEVELOPMENT §6.6)."""
    # Volatile/nondeterministic projection -> reject (spurious or masked changes).
    if has_volatile_projection(policy.query):
        report.errors.append(
            f"{where}: volatile/nondeterministic column in the projection "
            f"(now()/random()/clock_timestamp()/... are not allowed in a db_delta query)"
        )

    try:
        projected = projected_columns(policy.query)
    except SqlAnalysisError as exc:
        report.errors.append(f"{where}: cannot analyze the SELECT projection ({exc})")
        return
    if projected is None:
        return  # SELECT * covers every column

    # Every column a predicate reads must be projected, or the diff is blind to it.
    refs: set[str] = set()
    for pred in (
        policy.added_where,
        policy.changed_where_before,
        policy.changed_where_after,
        policy.removed_where,
    ):
        if pred:
            try:
                refs |= referenced_columns(pred)
            except PredicateError as exc:
                report.errors.append(f"{where}: unparseable predicate {pred!r} ({exc})")
                return
    missing = {c.lower() for c in refs} - projected
    if missing:
        report.errors.append(
            f"{where}: predicate references column(s) not projected by the query: "
            f"{sorted(missing)} — the diff would be blind to them (DEVELOPMENT §17)"
        )

    # An explicit key must be projected, or rows cannot be keyed for the diff.
    if policy.key and policy.key.lower() not in projected:
        report.errors.append(f"{where}: key {policy.key!r} is not in the query projection")


def validate_semantics(c: Contract) -> ValidationReport:
    report = ValidationReport()
    _validate_statistics(c, report)

    for idx, policy in enumerate(c.forbid):
        _validate_db_delta(policy, idx, report)

    # Expect-causality warning (FEATURE-SPEC §5): an absolute expect does not prove the run
    # caused the state. P0 always runs isolated+seeded, which supplies the baseline — note it.
    if c.expect and not c.preconditions:
        report.warnings.append(
            "expect: absolute final-state assertions do not prove causation on their own; "
            "P0 relies on per-trial isolation + seed for the baseline (FEATURE-SPEC §5)"
        )

    if not c.expect and not c.forbid:
        report.warnings.append("contract: neither expect nor forbid — nothing is verified")

    return report
