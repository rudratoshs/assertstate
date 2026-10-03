"""Execution adapter contract (SYSTEM-DESIGN §3.5; DEVELOPMENT §10).

The adapter runs in the UNTRUSTED child process. It receives only a BrowserTarget (as a
plain dict over IPC) + the budget + run_id, and returns an AgentTrace. It never receives an
OracleTarget / DSN / trusted object.
"""

from __future__ import annotations

from typing import Any, Protocol

from assertstate.domain.trace import AgentTrace


class AdapterError(Exception):
    """The adapter subprocess failed, timed out, or returned a malformed/oversized result.

    Always maps to a trial ERROR (never FAIL, never a silent PASS).
    """


class ExecutionAdapter(Protocol):
    """Implemented on the UNTRUSTED side; invoked only inside the child process."""

    def run(
        self,
        task: str,
        browser_target: dict[str, Any],
        execution_budget: dict[str, Any],
        run_id: str,
    ) -> AgentTrace: ...
