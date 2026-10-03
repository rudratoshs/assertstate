"""P0-20 (breadth) — agent-outcome rows of the acceptance matrix through the orchestrator.

Each case runs the real lifecycle via run_contract (the canonical path). The agent always
claims DONE; the verdict comes only from the oracle + settled deltas. ERROR/SKIPPED/
INCONCLUSIVE rows of DEVELOPMENT §35 are proven at the component/stats tiers
(test_oracle, test_delta, test_stats); here we prove the PASS/FAIL agent-outcome rows
end-to-end. Cross-tenant UPDATE needs a pre-seeded baseline and is covered at the delta
tier (test_snapshot_delta::...cross_tenant_update).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from assertstate.contract.loader import load_and_validate
from assertstate.domain.result import Outcome
from assertstate.domain.verdict import RunOutcome
from assertstate.orchestrator.environment import TrialContext
from assertstate.orchestrator.runner import run_contract

REPO = Path(__file__).resolve().parents[2]
CONTRACT = str(REPO / "contracts" / "pay-invoice.e2e.yaml")
DEMO_ADAPTER = "assertstate.adapters.demo_adapter:DemoAdapter"


def _pg() -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", "/tmp"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _pg(), reason="no local Postgres reachable")


def _demo_env(**kw: object):
    demo_dir = REPO / "demo-app"
    if str(demo_dir) not in sys.path:
        sys.path.insert(0, str(demo_dir))
    from environment import DemoEnvironment  # type: ignore[import-not-found]

    return DemoEnvironment(**kw)


@pytest.mark.parametrize(
    "scenario,fault,expected",
    [
        ("correct", None, Outcome.PASS),  # one payment, right value, one tenant
        ("slow_retry", None, Outcome.FAIL),  # duplicate-on-retry caught after drain
        ("correct", "wrong_amount", Outcome.FAIL),  # amount 9.87 != 98.70 (expect fails)
        ("correct", "missing", Outcome.FAIL),  # claims done, never writes (expect fails)
        ("correct", "cross_tenant", Outcome.FAIL),  # row added for globex (db_delta fires)
    ],
)
def test_matrix_row(scenario: str, fault: str | None, expected: Outcome) -> None:
    contract, report = load_and_validate(CONTRACT)
    assert contract is not None, report.errors
    env = _demo_env(scenario=scenario, fault=fault)
    out = run_contract(contract, env, DEMO_ADAPTER, trials=1)
    result = out.trials[0]
    assert result.outcome is expected, f"{scenario}/{fault}: {result.outcome} ({result.reason})"


def _contract():
    c, report = load_and_validate(CONTRACT)
    assert c is not None, report.errors
    return c


def test_matrix_skipped_when_baseline_not_pinned() -> None:
    # A pre-existing payment breaks the "0 rows" precondition -> SKIPPED (not FAIL).
    env = _demo_env(scenario="correct", pre_seed_payment=True)
    out = run_contract(_contract(), env, DEMO_ADAPTER, trials=1)
    assert out.trials[0].outcome is Outcome.SKIPPED


def test_matrix_error_when_oracle_unavailable() -> None:
    # The oracle read fails -> correctness cannot be established -> ERROR (never a silent pass).
    inner = _demo_env(scenario="correct")

    class _BadOracle:
        def setup(self, i: int) -> TrialContext:
            ctx = inner.setup(i)
            ctx.oracle_dsn = ctx.oracle_dsn.replace(
                f"dbname={ctx.db_name}", "dbname=assertstate_nonexistent_db"
            )
            return ctx

        def teardown(self, ctx: TrialContext) -> None:
            inner.teardown(ctx)  # ctx.db_name is intact -> real DB is dropped

    out = run_contract(_contract(), _BadOracle(), DEMO_ADAPTER, trials=1)
    assert out.trials[0].outcome is Outcome.ERROR


def test_matrix_run_verdict_inconclusive_when_too_few_valid() -> None:
    # 1 valid trial but the contract requires min_valid_trials=3 -> Run = INCONCLUSIVE.
    env = _demo_env(scenario="correct")
    out = run_contract(_contract(), env, DEMO_ADAPTER, trials=1)
    assert out.trials[0].outcome is Outcome.PASS
    assert out.verdict.verdict is RunOutcome.INCONCLUSIVE
