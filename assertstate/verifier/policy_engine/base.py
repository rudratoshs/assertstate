"""Shared policy result (deterministic, no I/O at evaluation time)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyResult:
    kind: str  # db_delta | http | external
    fired: bool  # the forbidden condition was observed
    gating: bool  # may this fire gate a FAIL? (false on shared staging / absent capture)
    detail: str
