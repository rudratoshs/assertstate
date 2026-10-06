"""Browser Use adapter interface conformance (FEATURE-SPEC §6 / §2.4).

A live run needs an LLM key + a real browser, so it is NOT exercised in unit CI (see
scripts/prove_browser_use.py for the manual end-to-end proof). This guards the contract that
matters for the boundary: the adapter implements ExecutionAdapter exactly (so it is launched
out-of-process with only {task, browser_target, budget, run_id}) and is wired into the CLI.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

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


def test_browser_use_adapter_routes_through_capture_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock browser_use (no live LLM/browser): the trusted capture proxy (§3) must reach Chromium
    via `--proxy-server`, and the agent's claimed-done must surface. Guards the proxy wiring I rely
    on for http/external/trajectory gating against a real `--config` app."""
    import browser_use  # the real package is importable in the venv

    captured: dict[str, Any] = {}

    class _FakeProfile:
        def __init__(self, **kw: Any) -> None:
            captured["profile_kwargs"] = kw

    class _FakeChat:
        def __init__(self, **kw: Any) -> None:
            captured["chat_kwargs"] = kw

    class _FakeHistory:
        def is_done(self) -> bool:
            return True

    class _FakeAgent:
        def __init__(self, **kw: Any) -> None:
            captured["task"] = kw.get("task")

        async def run(self, **kw: Any) -> _FakeHistory:
            return _FakeHistory()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(browser_use, "Agent", _FakeAgent)
    monkeypatch.setattr(browser_use, "BrowserProfile", _FakeProfile)
    monkeypatch.setattr(browser_use, "ChatOpenAI", _FakeChat)

    trace = BrowserUseAdapter().run(
        task="Pay the invoice",
        browser_target={"base_url": "http://127.0.0.1:9000/", "proxy": "http://127.0.0.1:5599"},
        execution_budget={"max_steps": 5},
        run_id="r-1",
    )

    assert trace.agent_claimed_done is True
    assert captured["profile_kwargs"]["args"] == ["--proxy-server=http://127.0.0.1:5599"]
    assert "http://127.0.0.1:9000/" in captured["task"]  # base_url injected into the agent task


def test_browser_use_adapter_no_proxy_passes_no_proxy_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    import browser_use

    captured: dict[str, Any] = {}

    class _FakeProfile:
        def __init__(self, **kw: Any) -> None:
            captured["profile_kwargs"] = kw

    class _FakeChat:
        def __init__(self, **kw: Any) -> None:
            pass

    class _FakeHistory:
        def is_done(self) -> bool:
            return False

    class _FakeAgent:
        def __init__(self, **kw: Any) -> None:
            pass

        async def run(self, **kw: Any) -> _FakeHistory:
            return _FakeHistory()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(browser_use, "Agent", _FakeAgent)
    monkeypatch.setattr(browser_use, "BrowserProfile", _FakeProfile)
    monkeypatch.setattr(browser_use, "ChatOpenAI", _FakeChat)

    trace = BrowserUseAdapter().run(
        task="Pay",
        browser_target={"base_url": "http://127.0.0.1:9000/"},  # no proxy
        execution_budget={},
        run_id="r-2",
    )
    assert trace.agent_claimed_done is False
    assert captured["profile_kwargs"]["args"] == []  # no --proxy-server when no capture proxy


def test_browser_use_adapter_remote_cdp_attaches_and_omits_launch_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote cloud browser (§9.5): with a `cdp_url` the adapter ATTACHES over CDP — it must pass
    cdp_url and must NOT pass launch-only flags (executable_path / headless / `--proxy-server`),
    since those don't apply to an already-running browser. A proxy present in browser_target must
    therefore NOT leak into the attached profile (capture is operator-side for remote browsers)."""
    import browser_use

    captured: dict[str, Any] = {}

    class _FakeProfile:
        def __init__(self, **kw: Any) -> None:
            captured["profile_kwargs"] = kw

    class _FakeChat:
        def __init__(self, **kw: Any) -> None:
            pass

    class _FakeHistory:
        def is_done(self) -> bool:
            return True

    class _FakeAgent:
        def __init__(self, **kw: Any) -> None:
            pass

        async def run(self, **kw: Any) -> _FakeHistory:
            return _FakeHistory()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(browser_use, "Agent", _FakeAgent)
    monkeypatch.setattr(browser_use, "BrowserProfile", _FakeProfile)
    monkeypatch.setattr(browser_use, "ChatOpenAI", _FakeChat)

    BrowserUseAdapter().run(
        task="Pay",
        browser_target={
            "base_url": "http://app.internal/",
            "cdp_url": "ws://browser.internal:9222/devtools/browser/abc",
            "proxy": "http://10.0.0.1:5599",  # present, but must NOT be injected into an attach
        },
        execution_budget={"max_steps": 5},
        run_id="r-3",
    )

    kw = captured["profile_kwargs"]
    assert kw.get("cdp_url") == "ws://browser.internal:9222/devtools/browser/abc"
    assert "args" not in kw  # no --proxy-server (launch flag) on an attached browser
    assert "executable_path" not in kw and "headless" not in kw
