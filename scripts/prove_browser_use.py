"""Real-agent proof (P0-14): run `assertstate` against a genuine Browser Use agent.

Loads the LLM key from random.env, stands up the demo web app, and runs the orchestrator
with the real BrowserUseAdapter on a 1-trial contract. Buggy app -> the agent clicks Pay,
sees success, reports DONE -> AssertState still catches the duplicate -> FAIL.

Cost-bounded: 1 trial, gpt-4o-mini, low max_steps.
Usage: python scripts/prove_browser_use.py [buggy|correct]
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "demo-app"))


def _load_env_file(path: Path) -> None:
    import os

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "buggy"
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    _load_env_file(REPO.parent / "random.env")

    from browser_environment import BrowserDemoEnvironment  # type: ignore[import-not-found]

    from assertstate.contract.loader import load_and_validate
    from assertstate.orchestrator.runner import run_contract

    contract, report = load_and_validate(REPO / "contracts" / "pay-invoice.e2e.yaml")
    assert contract is not None, report.errors

    app_desc = "has a hidden duplicate-payment bug" if mode == "buggy" else "is correct"
    print("\n" + "=" * 64)
    print("  REAL BROWSER-USE AGENT  vs  AssertState")
    print(f"  app {app_desc}; running {trials} trial(s) of a genuine gpt-4o-mini agent")
    print("=" * 64)

    env = BrowserDemoEnvironment(buggy=(mode == "buggy"))
    out = run_contract(
        contract, env, "assertstate.adapters.browser_use_adapter:BrowserUseAdapter", trials=trials
    )

    for i, t in enumerate(out.trials):
        dup = next((p["detail"] for p in t.policy_results if p["query_id"] == "f1"), "")
        note = f"[{dup}]" if t.outcome.value in ("PASS", "FAIL") else f"({t.reason})"
        print(
            f"  trial {i}: agent_claimed_done={t.refs.get('agent_claimed_done')}  "
            f"AssertState={t.outcome.value}   {note}"
        )

    v = out.verdict
    print("-" * 64)
    print(
        f"  RUN VERDICT: {v.verdict.value}   "
        f"({v.passed}P / {v.failed}F / {v.errored}E / {v.skipped}S, "
        f"wilson_lower={v.wilson_lower}, threshold={v.pass_threshold})"
    )
    print(f"  {v.reason}")
    print("=" * 64)
    return 0 if v.verdict.value in ("PASS", "FAIL", "INCONCLUSIVE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
