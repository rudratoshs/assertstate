"""CLI exit-code mapping incl. ERROR-dominated → 4 (DEVELOPMENT §8)."""

from __future__ import annotations

from assertstate.cli import _exit_code
from assertstate.domain.verdict import RunOutcome, RunVerdict


def _v(outcome: RunOutcome, *, passed=0, failed=0, errored=0, skipped=0) -> RunVerdict:
    total = passed + failed + errored + skipped
    return RunVerdict(
        verdict=outcome,
        total_trials=total,
        valid_trials=passed + failed,
        passed=passed,
        failed=failed,
        errored=errored,
        skipped=skipped,
        pass_rate=None,
        wilson_lower=None,
        confidence=0.95,
        side="one_sided",
        pass_threshold=0.9,
        error_rate=errored / total if total else 0.0,
        skip_rate=skipped / total if total else 0.0,
    )


def test_pass_is_zero() -> None:
    assert _exit_code(_v(RunOutcome.PASS, passed=5)) == 0


def test_fail_is_one() -> None:
    assert _exit_code(_v(RunOutcome.FAIL, passed=1, failed=4)) == 1


def test_error_dominated_inconclusive_is_four() -> None:
    # Errors are the plurality of why the run couldn't conclude -> exit 4.
    assert _exit_code(_v(RunOutcome.INCONCLUSIVE, passed=1, errored=4)) == 4


def test_skip_dominated_inconclusive_is_three() -> None:
    # Skips, not errors, dominate -> plain INCONCLUSIVE exit 3.
    assert _exit_code(_v(RunOutcome.INCONCLUSIVE, skipped=5)) == 3


def test_no_valid_no_error_is_three() -> None:
    assert _exit_code(_v(RunOutcome.INCONCLUSIVE, skipped=3, errored=0)) == 3
