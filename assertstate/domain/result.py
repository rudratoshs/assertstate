"""Trial outcomes and TrialResult (FEATURE-SPEC §8.1; SYSTEM-DESIGN §4; DEVELOPMENT §24).

PASS    = expectations hold AND no gating forbid policy fires AND budget (gating subset) holds
FAIL    = the workflow COMPLETED and violated the contract
ERROR   = correctness could not be established (infra/oracle/verifier/settlement/snapshot)
SKIPPED = a precondition could not be established
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Outcome(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class Attribution(Enum):
    CAUSAL = "causal"  # isolated single-writer env (the only P0 mode)
    OBSERVED = "observed"  # shared staging (P1+) — db_delta is non-gating here


@dataclass(frozen=True)
class SettlementRecord:
    mode: str
    causal_start_at: float | None = None
    started_at: float | None = None
    completed_at: float | None = None
    bound_or_drain_signal: str | None = None


@dataclass(frozen=True)
class TrialResult:
    outcome: Outcome
    reason: str = ""
    attribution: Attribution = Attribution.CAUSAL
    expect_results: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    policy_results: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    budget_results: dict[str, Any] = field(default_factory=dict)
    settlement: SettlementRecord | None = None
    refs: dict[str, str] = field(default_factory=dict)
