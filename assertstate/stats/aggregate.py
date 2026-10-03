"""Aggregate trial outcomes into a RunVerdict (FEATURE-SPEC §8.2/§8.3; DEVELOPMENT.md §26).

valid_trials = PASS + FAIL. Wilson is computed over valid trials only, BUT the Run cannot
PASS unless completeness holds, so ERRORs/SKIPs can't be laundered out of the denominator.
valid_trials == 0 -> INCONCLUSIVE (never PASS/0).
"""

from __future__ import annotations

from collections.abc import Sequence

from assertstate.domain.contract import StatisticsConfig
from assertstate.domain.result import Outcome, TrialResult
from assertstate.domain.verdict import RunOutcome, RunVerdict
from assertstate.stats.wilson import wilson_lower_bound


def aggregate(results: Sequence[TrialResult], cfg: StatisticsConfig) -> RunVerdict:
    total = len(results)
    passed = sum(1 for r in results if r.outcome is Outcome.PASS)
    failed = sum(1 for r in results if r.outcome is Outcome.FAIL)
    errored = sum(1 for r in results if r.outcome is Outcome.ERROR)
    skipped = sum(1 for r in results if r.outcome is Outcome.SKIPPED)
    valid = passed + failed

    error_rate = errored / total if total else 0.0
    skip_rate = skipped / total if total else 0.0

    complete = (
        valid >= cfg.min_valid_trials
        and error_rate <= cfg.max_error_rate
        and skip_rate <= cfg.max_skip_rate
    )

    pass_rate: float | None
    wilson: float | None
    if valid == 0:
        pass_rate = None
        wilson = None
        verdict = RunOutcome.INCONCLUSIVE
        reason = "no valid trials (PASS+FAIL == 0)"
    else:
        pass_rate = passed / valid
        wilson = wilson_lower_bound(passed, valid, cfg.confidence, cfg.side)
        if not complete:
            verdict = RunOutcome.INCONCLUSIVE
            reason = (
                f"completeness failed (valid={valid}>={cfg.min_valid_trials}? "
                f"error_rate={error_rate:.3f}<={cfg.max_error_rate}? "
                f"skip_rate={skip_rate:.3f}<={cfg.max_skip_rate}?)"
            )
        elif wilson >= cfg.pass_threshold:
            verdict = RunOutcome.PASS
            reason = f"wilson_lower={wilson:.4f} >= pass_threshold={cfg.pass_threshold}"
        else:
            verdict = RunOutcome.FAIL
            reason = f"wilson_lower={wilson:.4f} < pass_threshold={cfg.pass_threshold}"

    return RunVerdict(
        verdict=verdict,
        total_trials=total,
        valid_trials=valid,
        passed=passed,
        failed=failed,
        errored=errored,
        skipped=skipped,
        pass_rate=pass_rate,
        wilson_lower=wilson,
        confidence=cfg.confidence,
        side=cfg.side,
        pass_threshold=cfg.pass_threshold,
        error_rate=error_rate,
        skip_rate=skip_rate,
        reason=reason,
        per_trial=tuple(results),
    )
