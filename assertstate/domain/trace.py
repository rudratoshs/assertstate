"""Execution-side records (SYSTEM-DESIGN.md §3.8, §4).

AgentTrace is UNTRUSTED (from the adapter). agent_claimed_done is recorded as
EVIDENCE ONLY and never enters the verdict (INV-8). BrowserObservations and
RunMeasurements are TRUSTED and P1 — declared here, inert in P0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentTrace:
    """UNTRUSTED. The only thing returned across the IPC boundary (INV-6)."""

    steps: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    agent_claimed_done: bool = False  # recorded; NEVER a verdict input


@dataclass(frozen=True)
class BrowserObservations:
    """TRUSTED instrumentation. P1 — in P0 this is represented as out-of-scope, not faked."""

    network: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    last_causal_request_completed_at: float | None = None
    status: str = "out_of_scope_p0"


@dataclass(frozen=True)
class RunMeasurements:
    """TRUSTED harness measurement. P1. In P0 only wall-seconds is harness-measured."""

    wall_seconds: float | None = None
    action_count: int | None = None  # P1 (agent-reported in P0 -> non-gating)
    cost_usd: str | None = None  # P1 (agent-reported in P0 -> non-gating)
