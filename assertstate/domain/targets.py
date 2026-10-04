"""Targets (SYSTEM-DESIGN.md §4). The split IS the trust boundary.

OracleTarget is TRUSTED and must never cross the IPC boundary to the agent.
BrowserTarget is the only target the untrusted adapter ever receives.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrowserTarget:
    """Agent-visible. Handed to the untrusted adapter over IPC (SYSTEM-DESIGN §2, §12)."""

    base_url: str
    creds: str | None = None  # resolved trusted-side; redacted in evidence; never an oracle cred


@dataclass(frozen=True)
class OracleTarget:
    """TRUSTED. Read-only DB + (P1) read-only API. Never serialized to the child (INV-3)."""

    db_dsn_readonly: str
    # --- read-only API oracle (P1, shipped: GET/HEAD only via ApiProbe; expect.api live) ---
    api_base: str | None = None
    api_creds_readonly: str | None = None
    api_endpoint_allowlist: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExecutionBudget:
    """Budget caps (FEATURE-SPEC §12).

    In P0 only ``max_seconds`` is harness-trusted/gating; ``max_steps``/``max_cost_usd`` are
    agent-reported -> evidence-only, non-gating (DEVELOPMENT §25).
    """

    max_steps: int | None = None
    max_cost_usd: str | None = None  # string -> Decimal; never a YAML float
    max_seconds: float | None = None
