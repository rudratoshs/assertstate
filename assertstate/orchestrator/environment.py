"""Environment abstraction for the orchestrator (SYSTEM-DESIGN §3.11, §5).

An Environment brings up a fresh, isolated instance of the application-under-test for one
trial (its own DB + any workers) and tears it down. It hands the orchestrator the trusted
OracleTarget DSN (read-only) and the agent-visible BrowserTarget — the split that keeps the
oracle credential away from the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TrialContext:
    run_id: str
    oracle_dsn: str  # read-only; used by the trusted side only
    browser_target: dict[str, Any]  # agent-visible; app-write creds live here, never oracle
    db_name: str
    handle: Any = field(default=None)  # env-specific teardown handle (e.g. a worker)
    adapter_env: dict[str, str] = field(default_factory=dict)  # agent-side creds (e.g. LLM key)


class Environment(Protocol):
    def setup(self, trial_index: int) -> TrialContext: ...
    def teardown(self, ctx: TrialContext) -> None: ...
