"""Browser Use adapter interface conformance (FEATURE-SPEC §6 / §2.4).

A live run needs an LLM key + a real browser, so it is NOT exercised in unit CI (see
scripts/prove_browser_use.py for the manual end-to-end proof). This guards the contract that
matters for the boundary: the adapter implements ExecutionAdapter exactly (so it is launched
out-of-process with only {task, browser_target, budget, run_id}) and is wired into the CLI.
"""

from __future__ import annotations

import inspect

from assertstate.adapters.browser_use_adapter import BrowserUseAdapter


def test_browser_use_adapter_matches_execution_adapter_signature() -> None:
    # Exact ExecutionAdapter shape: launched out-of-process with only these four inputs.
    params = list(inspect.signature(BrowserUseAdapter.run).parameters)
    assert params == ["self", "task", "browser_target", "execution_budget", "run_id"]


def test_browser_use_adapter_takes_no_oracle_input() -> None:
    # The adapter's inputs are agent-facing only — never an OracleTarget/DSN (INV-3).
    params = set(inspect.signature(BrowserUseAdapter.run).parameters)
    assert not (params & {"oracle", "oracle_target", "dsn", "db_dsn"})


def test_browser_use_adapter_is_registered_in_cli() -> None:
    from assertstate.cli import _ADAPTERS

    assert _ADAPTERS["browser-use"] == "assertstate.adapters.browser_use_adapter:BrowserUseAdapter"
