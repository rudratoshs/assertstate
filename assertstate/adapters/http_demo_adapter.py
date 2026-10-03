"""Scripted HTTP agent (UNTRUSTED) — proves `bounded` without an LLM.

It makes a real browser-like HTTP request to the demo web app, routed through the
parent-owned trusted capture proxy (if `browser_target.proxy` is set), so a trusted
last-causal-request anchor exists for bounded settlement. With no proxy it still pays, but
leaves no anchor -> bounded fails closed. It has no oracle/DB access.
"""

from __future__ import annotations

import urllib.request
from typing import Any

from assertstate.domain.trace import AgentTrace


class HttpDemoAdapter:
    def run(
        self,
        task: str,
        browser_target: dict[str, Any],
        execution_budget: dict[str, Any],
        run_id: str,
    ) -> AgentTrace:
        base = browser_target["base_url"].rstrip("/")
        proxy = browser_target.get("proxy")
        opener = (
            urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy}))
            if proxy
            else urllib.request.build_opener()
        )
        opener.open(urllib.request.Request(base + "/"), timeout=15).read()  # view invoice
        opener.open(urllib.request.Request(base + "/pay", data=b""), timeout=15).read()  # pay
        return AgentTrace(
            steps=({"action": "http_pay", "base": base, "via_proxy": bool(proxy)},),
            agent_claimed_done=True,
        )
