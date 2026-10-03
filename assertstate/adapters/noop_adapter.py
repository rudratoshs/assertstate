"""No-op adapter (UNTRUSTED): does nothing and claims DONE.

For post-hoc checking — "my agent already ran against the app; just verify the state" — and
for config-driven runs where the acting is external. It has no oracle access.
"""

from __future__ import annotations

from typing import Any

from assertstate.domain.trace import AgentTrace


class NoopAdapter:
    def run(
        self,
        task: str,
        browser_target: dict[str, Any],
        execution_budget: dict[str, Any],
        run_id: str,
    ) -> AgentTrace:
        return AgentTrace(steps=({"action": "noop"},), agent_claimed_done=True)
