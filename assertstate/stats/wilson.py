"""Wilson score lower bound (FEATURE-SPEC §8.3; DEVELOPMENT.md §26).

Verified reference (all-success): 20/20 one-sided 95% = 0.881, 25/25 = 0.902,
30/30 = 0.917, 35/35 two-sided 95% = 0.901, 50/50 two-sided = 0.929.

Wilson quantifies uncertainty of a binomial proportion under the stated trial model; it
does NOT remove correlation among trials (that is disclosed alongside the interval).
"""

from __future__ import annotations

import math
from statistics import NormalDist

ONE_SIDED = "one_sided"
TWO_SIDED = "two_sided"


def _z(confidence: float, side: str) -> float:
    if not (0.0 < confidence < 1.0):
        raise ValueError("confidence must be in (0, 1)")
    if side == ONE_SIDED:
        return NormalDist().inv_cdf(confidence)
    if side == TWO_SIDED:
        return NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    raise ValueError(f"side must be {ONE_SIDED!r} or {TWO_SIDED!r}")


def wilson_lower_bound(
    successes: int, n: int, confidence: float = 0.95, side: str = ONE_SIDED
) -> float:
    """Lower bound of the Wilson score interval for `successes/n`."""
    if n <= 0:
        raise ValueError("n must be > 0 (callers must handle valid_trials == 0 upstream)")
    if not (0 <= successes <= n):
        raise ValueError("successes must be in [0, n]")
    z = _z(confidence, side)
    p = successes / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (center - margin) / denominator
