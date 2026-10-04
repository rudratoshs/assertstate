"""run_contract must THREAD the sandbox selection down to run_adapter (so the CLI's --config
sandbox choice actually reaches the child-process launcher — closing the "container mode is only
engaged in tests" gap). Needs Postgres for the oracle spine; run_adapter is mocked (no Docker)."""

from __future__ import annotations

import assertstate.orchestrator.runner as orch
from assertstate.domain.comparator import Comparator
from assertstate.domain.contract import Contract, DbExpect, StatisticsConfig
from assertstate.domain.result import Attribution
from assertstate.domain.trace import AgentTrace
from assertstate.env.template import ClusterConfig
from assertstate.orchestrator.environment import TrialContext
from tests.integration.conftest import admin_exec

SEED = """
INSERT INTO tenants(id) VALUES ('acme');
INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key)
VALUES ('bill-december','acme',98.70,'paid','bill-december');
"""


class _Env:
    def __init__(self, cfg: ClusterConfig, db: str) -> None:
        self.cfg, self.db = cfg, db

    def setup(self, trial_index: int) -> TrialContext:
        return TrialContext(
            run_id=f"sbx-{trial_index}",
            oracle_dsn=self.cfg.oracle_dsn(self.db),
            browser_target={"base_url": "http://127.0.0.1"},
            db_name=self.db,
            attribution=Attribution.CAUSAL,
        )

    def teardown(self, ctx: TrialContext) -> None:
        pass


def _contract() -> Contract:
    return Contract(
        task="t",
        app="demo",
        statistics=StatisticsConfig(trials=1, pass_threshold=0.5, min_valid_trials=1),
        expect=(
            DbExpect(
                query="SELECT status FROM payments WHERE invoice='bill-december'",
                comparator=Comparator.EQUALS,
                value="paid",
            ),
        ),
    )


def test_run_contract_threads_sandbox_to_run_adapter(
    trial_db: tuple[ClusterConfig, str], monkeypatch
) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    captured: dict[str, object] = {}

    def fake_run_adapter(*args: object, **kwargs: object) -> AgentTrace:
        captured["mode"] = kwargs.get("mode")
        captured["container_network"] = kwargs.get("container_network")
        return AgentTrace(steps=(), agent_claimed_done=True)

    monkeypatch.setattr(orch, "run_adapter", fake_run_adapter)
    orch.run_contract(
        _contract(),
        _Env(cfg, db),
        "x:Y",
        mode="container",
        container_network="bridge",
    )
    assert captured["mode"] == "container", "run_contract must thread mode to run_adapter"
    assert captured["container_network"] == "bridge", "and the network posture"


def test_run_contract_defaults_to_subprocess(
    trial_db: tuple[ClusterConfig, str], monkeypatch
) -> None:
    cfg, db = trial_db
    admin_exec(cfg, db, SEED)
    captured: dict[str, object] = {}

    def fake_run_adapter(*args: object, **kwargs: object) -> AgentTrace:
        captured["mode"] = kwargs.get("mode")
        return AgentTrace(steps=(), agent_claimed_done=True)

    monkeypatch.setattr(orch, "run_adapter", fake_run_adapter)
    orch.run_contract(_contract(), _Env(cfg, db), "x:Y")  # no mode -> subprocess default preserved
    assert captured["mode"] == "subprocess"
