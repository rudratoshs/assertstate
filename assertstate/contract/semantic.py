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
    ApiExpect,
    Contract,
    DbDeltaPolicy,
    DestructiveActionPolicy,
    SettlementConfig,
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


def _validate_settle(settle: SettlementConfig, where: str, report: ValidationReport) -> None:
    """Shared settle-mode validation (db_delta + destructive_action)."""
    if settle.mode not in SETTLE_MODES:
        report.errors.append(
            f"{where}.settle.mode: unknown {settle.mode!r} (one of {sorted(SETTLE_MODES)})"
        )
    # Per-mode required fields.
    if settle.mode == "drain":
        if not settle.queue:
            report.errors.append(f"{where}.settle: drain requires a `queue` (workflow-owned)")
        if settle.timeout_s is None:
            report.errors.append(f"{where}.settle: drain requires a `timeout`")
    elif settle.mode == "bounded":
        if settle.max_wait_s is None:
            report.errors.append(f"{where}.settle: bounded requires a `max_wait`")
    elif settle.mode == "run_correlated":
        # P2, app-cooperation: the app must stamp the run id onto its writes AND expose the
        # drainable queue used to prove completion (producers closed + queue empty).
        if not settle.run_id_col:
            report.errors.append(
                f"{where}.settle: run_correlated requires a `run_id_col` (the column the app "
                "stamps with the run id; the delta is filtered to this run's rows)"
            )
        if not settle.queue:
            report.errors.append(
                f"{where}.settle: run_correlated requires a `queue` to prove completion (drain)"
            )
        if settle.timeout_s is None:
            report.errors.append(f"{where}.settle: run_correlated requires a `timeout`")


def _validate_db_delta(policy: DbDeltaPolicy, idx: int, report: ValidationReport) -> None:
    where = f"forbid[{idx}].db_delta"
    _validate_settle(policy.settle, where, report)

    has_pred = any(
        [
            policy.added_where,
            policy.changed_where_before,
            policy.changed_where_after,
            policy.removed_where,
        ]
    )
    has_cap = any(c is not None for c in (policy.max_added, policy.max_changed, policy.max_removed))
    if not has_pred and not has_cap:
        # A policy with no predicate AND no explicit cap polices nothing: it can never fire
        # (a guaranteed PASS — the cardinal false-PASS sin). Reject it at load.
        report.errors.append(
            f"{where}: db_delta polices nothing (no *_where predicate and no max_* cap) — it can "
            "never fire; add a predicate or an explicit cap (e.g. max_added: 0)"
        )
    elif not has_pred:
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


def _validate_destructive(
    policy: DestructiveActionPolicy, idx: int, report: ValidationReport
) -> None:
    where = f"forbid[{idx}].destructive_action"
    _validate_settle(policy.settle, where, report)
    if not policy.approval_query:
        report.errors.append(f"{where}: `approval_query` is required (the trusted approval read)")
    # Note: approval_where uses the comparator mini-language (string/number equality + ordering),
    # which has no boolean literal. `approved = true` fails CLOSED at runtime (PredicateError ->
    # trial ERROR, never a wrong verdict); boolean filters belong in the approval_query SQL (see the
    # shipped example). A load-time parse-check is not added: the engine has no parse-only entry and
    # a matches()-probe would false-reject valid ordering predicates (e.g. `amount > 5`).
    # The destructive signal (an in-scope removal) always polices — it can fire — so no
    # polices-nothing check is needed; the fire condition is "destructive AND no approval".


def validate_semantics(c: Contract) -> ValidationReport:
    report = ValidationReport()
    _validate_statistics(c, report)

    for idx, policy in enumerate(c.forbid):
        if isinstance(policy, DbDeltaPolicy):
            _validate_db_delta(policy, idx, report)
        elif isinstance(policy, DestructiveActionPolicy):
            _validate_destructive(policy, idx, report)
        # http / external policies are structurally validated at load; nothing further here.

    # expect.api must be observational: GET/HEAD only (FEATURE-SPEC §3.7).
    for idx, e in enumerate(c.expect):
        if isinstance(e, ApiExpect):
            method = e.request.strip().split(" ", 1)[0].upper()
            if method not in ("GET", "HEAD"):
                report.errors.append(
                    f"expect[{idx}].api: observational only — {method} is not GET/HEAD"
                )

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
