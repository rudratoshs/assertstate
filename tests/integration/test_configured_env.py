"""P0-04 ConfiguredEnvironment: run a contract against a configured real app (real Postgres).

Uses a template-restored demo DB as the stand-in "external app" (it carries the read-only
oracle role + the privilege sentinel). Proves: a config-driven run verifies final state via
the read-only oracle (NoopAdapter = the agent already acted externally), labels attribution
observed on shared staging, and fails closed (ERROR) if the configured DSN is writable.
"""

from __future__ import annotations

from pathlib import Path

from assertstate.config.environment import ConfiguredEnvironment
from assertstate.config.model import AppConfig, BrowserConfig, OracleConfig
from assertstate.contract.loader import load_and_validate
from assertstate.domain.result import Attribution, Outcome
from assertstate.env.template import ClusterConfig
from assertstate.orchestrator.runner import run_contract
from tests.integration.conftest import admin_exec

CONTRACT = str(Path(__file__).resolve().parents[2] / "contracts" / "expect-only.example.yaml")
NOOP = "assertstate.adapters.noop_adapter:NoopAdapter"


def _app(dsn: str) -> AppConfig:
    return AppConfig(
        name="external",
        oracle=OracleConfig(db_dsn=dsn),
        browser=BrowserConfig(base_url="http://external.example"),
    )


def _seed(cfg: ClusterConfig, db: str, status: str) -> None:
    admin_exec(cfg, db, "INSERT INTO tenants(id) VALUES ('acme')")
    admin_exec(
        cfg,
        db,
        f"INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key) "
        f"VALUES ('bill-x','acme',98.70,'{status}','bill-x')",
    )


def test_config_run_passes_when_state_matches(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    _seed(cfg, db, "paid")
    contract, report = load_and_validate(CONTRACT)
    assert contract is not None, report.errors
    env = ConfiguredEnvironment(_app(cfg.oracle_dsn(db)))
    out = run_contract(contract, env, NOOP, trials=1)
    assert out.trials[0].outcome is Outcome.PASS
    assert out.trials[0].attribution is Attribution.OBSERVED  # shared staging


def test_config_run_fails_when_state_wrong(trial_db: tuple[ClusterConfig, str]) -> None:
    cfg, db = trial_db
    _seed(cfg, db, "pending")  # not 'paid'
    contract, _ = load_and_validate(CONTRACT)
    assert contract is not None
    out = run_contract(contract, ConfiguredEnvironment(_app(cfg.oracle_dsn(db))), NOOP, trials=1)
    assert out.trials[0].outcome is Outcome.FAIL


def test_config_run_errors_on_writable_dsn(trial_db: tuple[ClusterConfig, str]) -> None:
    # A writable (superuser) DSN fails the read-only check at setup -> ERROR, never a pass.
    cfg, db = trial_db
    _seed(cfg, db, "paid")
    contract, _ = load_and_validate(CONTRACT)
    assert contract is not None
    out = run_contract(contract, ConfiguredEnvironment(_app(cfg.admin_dsn(db))), NOOP, trials=1)
    assert out.trials[0].outcome is Outcome.ERROR
