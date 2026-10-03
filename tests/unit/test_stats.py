"""P0-18 statistics: exact Wilson numbers + aggregation/completeness (FEATURE-SPEC §8)."""

from __future__ import annotations

import pytest

from assertstate.domain.contract import StatisticsConfig
from assertstate.domain.result import Outcome, TrialResult
from assertstate.domain.verdict import RunOutcome
from assertstate.stats.aggregate import aggregate
from assertstate.stats.wilson import wilson_lower_bound


@pytest.mark.parametrize(
    "k,n,conf,side,expected",
    [
        (20, 20, 0.95, "one_sided", 0.881),
        (25, 25, 0.95, "one_sided", 0.902),
        (30, 30, 0.95, "one_sided", 0.917),
        (35, 35, 0.95, "two_sided", 0.901),
        (50, 50, 0.95, "two_sided", 0.929),
    ],
)
def test_wilson_reference_numbers(k: int, n: int, conf: float, side: str, expected: float) -> None:
    assert round(wilson_lower_bound(k, n, conf, side), 3) == expected


def test_wilson_29_of_30_fails_a_090_gate() -> None:
    # FEATURE-SPEC §8.3 honest implication: 29/30 one-sided = 0.864 < 0.90.
    assert round(wilson_lower_bound(29, 30, 0.95, "one_sided"), 3) == 0.864


def test_wilson_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound(1, 0)
    with pytest.raises(ValueError):
        wilson_lower_bound(5, 3)
    with pytest.raises(ValueError):
        wilson_lower_bound(1, 2, confidence=1.0)


def _results(p: int, f: int, e: int = 0, s: int = 0) -> list[TrialResult]:
    out = [TrialResult(outcome=Outcome.PASS) for _ in range(p)]
    out += [TrialResult(outcome=Outcome.FAIL) for _ in range(f)]
    out += [TrialResult(outcome=Outcome.ERROR) for _ in range(e)]
    out += [TrialResult(outcome=Outcome.SKIPPED) for _ in range(s)]
    return out


def _cfg(**over: object) -> StatisticsConfig:
    base = dict(
        trials=30,
        pass_threshold=0.85,
        confidence=0.95,
        side="one_sided",
        min_valid_trials=25,
        max_error_rate=0.10,
        max_skip_rate=0.00,
    )
    base.update(over)
    return StatisticsConfig(**base)  # type: ignore[arg-type]


def test_aggregate_pass() -> None:
    v = aggregate(_results(30, 0), _cfg())
    assert v.verdict is RunOutcome.PASS
    assert v.valid_trials == 30 and v.passed == 30
    assert v.wilson_lower is not None and v.wilson_lower >= 0.85


def test_aggregate_fail_below_threshold() -> None:
    # 25/30 valid -> wilson well below 0.85 -> FAIL (not INCONCLUSIVE; completeness holds).
    v = aggregate(_results(25, 5), _cfg())
    assert v.verdict is RunOutcome.FAIL


def test_aggregate_zero_valid_is_inconclusive() -> None:
    v = aggregate(_results(0, 0, e=30), _cfg(max_error_rate=1.0))
    assert v.verdict is RunOutcome.INCONCLUSIVE
    assert v.pass_rate is None and v.wilson_lower is None


def test_aggregate_too_many_errors_is_inconclusive() -> None:
    # 26 valid meets min_valid_trials, but error_rate 4/30=0.133 > 0.10 -> INCONCLUSIVE.
    v = aggregate(_results(26, 0, e=4), _cfg())
    assert v.verdict is RunOutcome.INCONCLUSIVE
    assert v.errored == 4


def test_aggregate_skip_cap() -> None:
    v = aggregate(_results(26, 0, s=4), _cfg(max_skip_rate=0.0))
    assert v.verdict is RunOutcome.INCONCLUSIVE
    assert v.skipped == 4


def test_aggregate_insufficient_valid_is_inconclusive() -> None:
    v = aggregate(_results(10, 0), _cfg(min_valid_trials=25))
    assert v.verdict is RunOutcome.INCONCLUSIVE
