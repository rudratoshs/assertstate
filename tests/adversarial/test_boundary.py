"""P0-13 boundary proof suite (DEVELOPMENT §36 items 1-8, INV-3..6).

Scope: a subprocess + filtered env backs INV-3/4/5/6. INV-7 (filesystem/socket isolation)
is the P1 container hardening and is intentionally NOT asserted here.
"""

from __future__ import annotations

import pytest

from assertstate.adapters.base import AdapterError
from assertstate.adapters.runner import run_adapter

A = "tests.adversarial._adapters"


def _run(spec: str, **over: object):
    kw = dict(
        task="t",
        browser_target={"base_url": "http://app", "creds": "app-dsn"},
        execution_budget={"max_seconds": 5},
        run_id="r1",
    )
    kw.update(over)
    return run_adapter(spec, **kw)  # type: ignore[arg-type]


def test_honest_adapter_roundtrips() -> None:
    trace = _run(f"{A}:HonestAdapter")
    assert trace.agent_claimed_done is True
    assert trace.steps == ({"action": "noop"},)


def test_inv3_oracle_dsn_never_reaches_child(monkeypatch: pytest.MonkeyPatch) -> None:
    # A secret in the PARENT env must not be copied into the child (allowlist).
    monkeypatch.setenv("ORACLE_DSN", "postgresql://secret-should-not-leak/db")
    monkeypatch.setenv("ASSERTSTATE_PG_ADMIN_USER", "superuser-secret")
    trace = _run(f"{A}:LeakAdapter")
    seen = trace.steps[0]
    assert seen["oracle_dsn_env"] is None  # INV-3: not present in child env
    assert seen["assertstate_env_keys"] == []  # no ASSERTSTATE_* secrets leaked
    assert seen["saw_oracle_in_target"] is False  # INV-5: only browser_target crossed


def test_inv6_extra_keys_rejected() -> None:
    with pytest.raises(AdapterError, match="wrong shape"):
        _run(f"{A}:BadShapeAdapter")  # smuggled "stolen" key -> rejected


def test_malformed_output_is_error() -> None:
    with pytest.raises(AdapterError, match="not JSON"):
        _run(f"{A}:GarbageAdapter")


def test_oversized_output_is_error() -> None:
    with pytest.raises(AdapterError, match="exceeded"):
        _run(f"{A}:HugeAdapter")


def test_crash_is_error() -> None:
    with pytest.raises(AdapterError, match="exited 3"):
        _run(f"{A}:CrashAdapter")


def test_timeout_is_error() -> None:
    with pytest.raises(AdapterError, match="timed out"):
        _run(f"{A}:TimeoutAdapter", timeout_s=0.5)


def test_runner_never_has_oracle_in_its_own_contract() -> None:
    # Belt-and-braces: the request shape the runner builds carries no oracle field.
    import inspect

    src = inspect.getsource(run_adapter)
    assert "oracle" not in src.lower()


def test_inv1_child_not_imported_into_trusted_process() -> None:
    # INV-1: the untrusted child module must run out-of-process, never be imported in-process.
    # Importing the trusted runner/orchestrator must NOT pull `assertstate.adapters.child` in.
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    code = (
        "import sys; import assertstate.orchestrator.runner; import assertstate.adapters.runner; "
        "assert 'assertstate.adapters.child' not in sys.modules, "
        "'child module was imported into the trusted process'"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(repo))
    assert r.returncode == 0, r.stderr
