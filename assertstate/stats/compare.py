"""Regression / version comparison (FEATURE-SPEC §8.5; §10 regression baselines + model-swap).

This is NOT the acceptance gate. The Wilson lower bound (stats/wilson.py) answers "is this run's
true pass rate >= threshold?"; it does NOT test whether version B is significantly worse than a
baseline A, and you may not infer that from two Wilson intervals overlapping. Regression / model-
swap use a distinct method:
  - independent runs  -> two-sample difference-in-proportions (Wald) CI;
  - same scenarios on both versions (paired) -> McNemar on the discordant pairs.
Both report "B significantly WORSE than A" at a one-sided confidence, never "better/equal" as a
pass. Deterministic, stdlib-only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from assertstate.stats.wilson import ONE_SIDED, TWO_SIDED


@dataclass(frozen=True)
class ComparisonResult:
    method: str  # "two_proportion" | "mcnemar"
    baseline_rate: float  # A pass-rate
    candidate_rate: float  # B pass-rate
    diff: float  # candidate - baseline (negative => B worse)
    ci_low: float | None  # CI on the diff (two_proportion); None for mcnemar
    ci_high: float | None
    p_value: float | None  # mcnemar p-value; None for two_proportion
    regressed: bool  # B is SIGNIFICANTLY worse than A at `confidence`
    confidence: float
    detail: str


def _z(confidence: float, side: str) -> float:
    if not (0.0 < confidence < 1.0):
        raise ValueError("confidence must be in (0, 1)")
    if side == ONE_SIDED:
        return NormalDist().inv_cdf(confidence)
    if side == TWO_SIDED:
        return NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    raise ValueError(f"side must be {ONE_SIDED!r} or {TWO_SIDED!r}")


def two_proportion(
    passed_a: int,
    n_a: int,
    passed_b: int,
    n_b: int,
    *,
    confidence: float = 0.95,
    side: str = ONE_SIDED,
) -> ComparisonResult:
    """Independent-runs comparison. B regresses iff the diff CI lies entirely below 0.

    Wald (unpooled) interval on (p_b - p_a); at p=0 or p=1 one SE term is 0, which understates
    uncertainty at the boundary — a documented limitation, so a single near-boundary trial won't
    be over-trusted; prefer the paired McNemar test when the same scenarios run on both versions.
    """
    if n_a <= 0 or n_b <= 0:
        raise ValueError("both runs need n > 0")
    if not (0 <= passed_a <= n_a) or not (0 <= passed_b <= n_b):
        raise ValueError("passed must be in [0, n]")
    p_a = passed_a / n_a
    p_b = passed_b / n_b
    diff = p_b - p_a
    se = math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    z = _z(confidence, side)
    ci_low = diff - z * se
    ci_high = diff + z * se
    regressed = ci_high < 0.0  # the whole interval for (B - A) is below zero => B worse
    return ComparisonResult(
        method="two_proportion",
        baseline_rate=p_a,
        candidate_rate=p_b,
        diff=diff,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=None,
        regressed=regressed,
        confidence=confidence,
        detail=(
            f"two_proportion: A={passed_a}/{n_a}({p_a:.3f}) B={passed_b}/{n_b}({p_b:.3f}) "
            f"diff={diff:+.3f} CI[{ci_low:+.3f},{ci_high:+.3f}] regressed={regressed}"
        ),
    )


def _binom_two_sided_p(k: int, n: int) -> float:
    # Exact two-sided sign-test p for McNemar: 2 * P(X <= k) under Binom(n, 0.5), capped at 1.
    cdf = sum(math.comb(n, i) for i in range(k + 1)) * (0.5**n)
    return min(1.0, 2.0 * cdf)


def mcnemar(
    both_pass: int,
    a_pass_b_fail: int,
    a_fail_b_pass: int,
    both_fail: int,
    *,
    confidence: float = 0.95,
) -> ComparisonResult:
    """Paired comparison (same scenarios on A and B). Discordant pairs only drive the test:
    `a_pass_b_fail` (b) vs `a_fail_b_pass` (c). B regresses iff b > c significantly (one-sided).

    Exact binomial sign test when discordants are few (<= 25), else the continuity-corrected
    chi-square approximation. `confidence` sets the one-sided alpha = 1 - confidence.
    """
    b = a_pass_b_fail
    c = a_fail_b_pass
    n_disc = b + c
    total = both_pass + b + c + both_fail
    p_a = (both_pass + b) / total if total else 0.0
    p_b = (both_pass + c) / total if total else 0.0
    alpha = 1.0 - confidence

    if n_disc == 0:
        two_sided_p = 1.0
    elif n_disc <= 25:
        two_sided_p = _binom_two_sided_p(min(b, c), n_disc)
    else:
        stat = (abs(b - c) - 1) ** 2 / n_disc  # continuity-corrected chi-square (1 df)
        two_sided_p = 2.0 * NormalDist().cdf(-math.sqrt(stat))
    # One-sided p for "B worse" (b > c): halve the two-sided p, but only when the effect is in
    # the worse direction; otherwise B is not worse.
    one_sided_p = (two_sided_p / 2.0) if b > c else 1.0
    regressed = b > c and one_sided_p <= alpha
    return ComparisonResult(
        method="mcnemar",
        baseline_rate=p_a,
        candidate_rate=p_b,
        diff=p_b - p_a,
        ci_low=None,
        ci_high=None,
        p_value=one_sided_p,
        regressed=regressed,
        confidence=confidence,
        detail=(
            f"mcnemar: discordant b(A✓B✗)={b} c(A✗B✓)={c} one_sided_p={one_sided_p:.4f} "
            f"alpha={alpha:.3f} regressed={regressed}"
        ),
    )
