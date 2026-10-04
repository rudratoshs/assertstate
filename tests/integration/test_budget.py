"""max_seconds is a trusted, GATING budget: a correctness-PASS still FAILs if the agent
over-ran the time budget (closes the F4 non-gating gap). Requires Postgres (trial_db)."""

from __future__ import annotations

from assertstate.domain.comparator import Comparator
from assertstate.domain.contract import Contract, DbExpect, ExecutionBudget, StatisticsConfig
from assertstate.domain.result import Attribution, Outcome
from assertstate.domain.verdict import RunOutcome
from assertstate.env.template import ClusterConfig
from assertstate.orchestrator.environment import TrialContext
from assertstate.orchestrator.runner import run_contract
from tests.integration.conftest import admin_exec

SEED = """
INSERT INTO tenants(id) VALUES ('acme');
INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key)
VALUES ('bill-december','acme',98.70,'paid','bill-december');
"""

_ADAPTER = "tests.adversarial._adapters:SlowAdapter"


class _Env:
    def __init__(self, cfg: ClusterConfig, db: str, sleep_s: float) -> None:
        self.cfg, self.db, self.sleep_s = cfg, db, sleep_s

    def setup(self, trial_index: int) -> TrialContext:
        return TrialContext(
            run_id=f"budget-{trial_index}",
            oracle_dsn=self.cfg.oracle_dsn(self.db),
            browser_target={"base_url": "http://127.0.0.1", "sleep_s": self.sleep_s},
            db_name=self.db,
            attribution=Attribution.CAUSAL,
        )

    def teardown(self, ctx: TrialContext) -> None:
        pass


def _contract(max_seconds: float) -> Contract:
    return Contract(
        task="pay the invoice within time budget",
        app="demo",
        statistics=StatisticsConfig(trials=1, pass_threshold=0.5, min_valid_trials=1),
        expect=(
            DbExpect(
                query="SELECT status FROM payments WHERE invoice='bill-december'",
                comparator=Comparator.EQUALS,
                value="paid",
            ),
        ),
        budget=ExecutionBudget(max_seconds=max_seconds),
    )


def test_overrun_turns_pass_into_fail(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    # Correctness holds (status == paid) but the agent sleeps ~1.0s past a 0.3s budget.
    out = run_contract(_contract(max_seconds=0.3), _Env(cfg, db, sleep_s=1.0), _ADAPTER)
    trial = out.trials[0]
    assert trial.outcome is Outcome.FAIL, trial.reason
    assert "budget exceeded" in trial.reason
    assert trial.budget_results["over_budget"] is True
    assert out.verdict.verdict is RunOutcome.FAIL


def test_within_budget_passes(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    # Same correctness, generous budget -> PASS (budget is not spuriously gating).
    out = run_contract(_contract(max_seconds=30.0), _Env(cfg, db, sleep_s=0.05), _ADAPTER)
    trial = out.trials[0]
    assert trial.outcome is Outcome.PASS, trial.reason
    assert trial.budget_results["over_budget"] is False
