"""RunVerdict (FEATURE-SPEC §8; SYSTEM-DESIGN §4; DEVELOPMENT §26)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from assertstate.domain.result import TrialResult


class RunOutcome(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class RunVerdict:
    verdict: RunOutcome
    total_trials: int
    valid_trials: int  # PASS + FAIL
    passed: int
    failed: int
    errored: int
    skipped: int
    pass_rate: float | None  # None when valid_trials == 0
    wilson_lower: float | None
    confidence: float
    side: str
    pass_threshold: float
    error_rate: float
    skip_rate: float
    reason: str = ""
    per_trial: tuple[TrialResult, ...] = field(default_factory=tuple)
