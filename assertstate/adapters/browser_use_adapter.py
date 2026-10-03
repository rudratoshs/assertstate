"""Real Browser Use execution adapter (UNTRUSTED child) — P0-14.

A genuine autonomous browser agent: given the task + BrowserTarget base_url, it drives a
real Chromium via Browser Use + an LLM and reports what it did. It receives its own LLM
credential from the child env (passed explicitly as an agent credential, never the oracle).
It has no database/oracle access — it only operates the web UI.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from assertstate.domain.trace import AgentTrace

_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class BrowserUseAdapter:
    def run(
        self,
        task: str,
        browser_target: dict[str, Any],
        execution_budget: dict[str, Any],
        run_id: str,
    ) -> AgentTrace:
        base_url = browser_target["base_url"]
        model = os.environ.get("ASSERTSTATE_LLM_MODEL", "gpt-4o-mini")
        max_steps = int(execution_budget.get("max_steps") or 12)

        full_task = (
            f"{task} Go to {base_url} and pay the invoice shown by clicking the "
            f"'Pay invoice' button. When you see a payment-successful confirmation, you are done."
        )
        claimed_done, steps = asyncio.run(self._drive(full_task, base_url, model, max_steps))
        return AgentTrace(steps=tuple(steps), agent_claimed_done=claimed_done)

    async def _drive(
        self, task: str, base_url: str, model: str, max_steps: int
    ) -> tuple[bool, list[dict[str, Any]]]:
        from browser_use import Agent, BrowserProfile, ChatOpenAI

        headful = os.environ.get("ASSERTSTATE_BROWSER_HEADFUL") == "1"
        profile = BrowserProfile(
            headless=not headful,  # set ASSERTSTATE_BROWSER_HEADFUL=1 to watch the browser live
            executable_path=_CHROME if os.path.exists(_CHROME) else None,
            chromium_sandbox=False,
        )
        gif = os.environ.get("ASSERTSTATE_BROWSER_GIF")  # set to a path to record the run
        agent: Any = Agent(
            task=task,
            llm=ChatOpenAI(model=model, api_key=os.environ["OPENAI_API_KEY"]),
            browser_profile=profile,
            directly_open_url=True,  # open the URL named in the task directly
            generate_gif=gif if gif else False,
        )
        history = await agent.run(max_steps=max_steps)
        try:
            claimed_done = bool(history.is_done())
        except Exception:
            claimed_done = True  # the agent returned without erroring; it believes it finished
        steps = [{"action": "browser_use_run", "model": model, "is_done": claimed_done}]
        return claimed_done, steps
