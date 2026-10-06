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
        proxy = browser_target.get("proxy")  # trusted parent-owned capture proxy (§3), if any
        cdp_url = browser_target.get("cdp_url")  # remote cloud-browser CDP endpoint (§9.5), if any
        model = os.environ.get("ASSERTSTATE_LLM_MODEL", "gpt-4o-mini")
        max_steps = int(execution_budget.get("max_steps") or 12)

        full_task = (
            f"{task} Go to {base_url} and pay the invoice shown by clicking the "
            f"'Pay invoice' button. When you see a payment-successful confirmation, you are done."
        )
        claimed_done, steps = asyncio.run(
            self._drive(full_task, base_url, model, max_steps, proxy, cdp_url)
        )
        return AgentTrace(steps=tuple(steps), agent_claimed_done=claimed_done)

    async def _drive(
        self,
        task: str,
        base_url: str,
        model: str,
        max_steps: int,
        proxy: str | None,
        cdp_url: str | None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        from browser_use import Agent, BrowserProfile, ChatOpenAI

        if cdp_url:
            # REMOTE: attach to an operator-controlled cloud browser over CDP (§9.5). We do NOT
            # launch, so `--proxy-server` / executable_path / headless are not ours to set — they
            # are launch-time flags and have no effect on an already-running browser. Trusted
            # capture for a remote browser must therefore be configured OPERATOR-SIDE at that
            # browser's launch (point it at the parent proxy); if it is not, the parent simply
            # records nothing and the http/external/trajectory policies stay NON-GATING (§3,
            # fail-closed) — never a false pass. The adapter never silently claims capture.
            profile = BrowserProfile(cdp_url=cdp_url)
        else:
            # LOCAL: launch Chrome ourselves and route it through the trusted capture proxy when the
            # parent provided one, so the agent's app traffic is recorded in the parent (policies
            # gate). The agent could bypass it, but then no records -> non-gating (§3).
            headful = os.environ.get("ASSERTSTATE_BROWSER_HEADFUL") == "1"
            extra_args = [f"--proxy-server={proxy}"] if proxy else []
            profile = BrowserProfile(
                headless=not headful,  # ASSERTSTATE_BROWSER_HEADFUL=1 to watch the browser live
                executable_path=_CHROME if os.path.exists(_CHROME) else None,
                chromium_sandbox=False,
                args=extra_args,
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
