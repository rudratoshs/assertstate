"""Untrusted child entrypoint: `python -m assertstate.adapters.child <module:attr>`.

Reads one JSON request from stdin, runs the named adapter, writes one JSON AgentTrace to
stdout. This process is UNTRUSTED: it imports only the adapter + domain types and never
receives oracle credentials (the parent strips them from the env). A malicious adapter may
misbehave (garbage/oversized output, crash, hang) — the trusted runner classifies all of
that as AdapterError -> ERROR.
"""

from __future__ import annotations

import importlib
import json
import sys

from assertstate.domain.trace import AgentTrace


def main() -> int:
    spec = sys.argv[1]
    module_name, _, attr = spec.partition(":")
    request = json.loads(sys.stdin.read())

    module = importlib.import_module(module_name)
    adapter = getattr(module, attr)()
    trace: AgentTrace = adapter.run(
        request["task"],
        request["browser_target"],
        request["execution_budget"],
        request["run_id"],
    )
    sys.stdout.write(
        json.dumps(
            {
                "steps": list(trace.steps),
                "agent_claimed_done": bool(trace.agent_claimed_done),
            }
        )
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
