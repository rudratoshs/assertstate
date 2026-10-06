"""`_settle` dispatch fail-closes on a non-runnable settlement mode (FEATURE-SPEC §5a).

Defensive guard: if a settle mode is ever not RUNNABLE, `_settle` must NOT silently fall through to
a windowless after-snapshot (a latent false-PASS in an async env) — it raises SettlementError
(→ trial ERROR). All three shipped modes (drain/bounded/run_correlated) are runnable, so this guard
is exercised with a forged mode built directly from domain objects (bypassing load validation).
"""

from __future__ import annotations

import pytest

from assertstate.domain.contract import Contract, DbDeltaPolicy, SettlementConfig, StatisticsConfig
from assertstate.oracle.settlement.controller import SettlementError
from assertstate.orchestrator.environment import TrialContext
from assertstate.orchestrator.runner import _settle


def _ctx() -> TrialContext:
    return TrialContext(run_id="r", oracle_dsn="", browser_target={}, db_name="x")


def test_non_runnable_settle_mode_fails_closed() -> None:
    policy = DbDeltaPolicy(
        query="SELECT id FROM payments",
        settle=SettlementConfig(mode="not_a_real_mode"),  # forged non-runnable mode
        max_added=0,
    )
    contract = Contract(
        task="t",
        app="demo",
        statistics=StatisticsConfig(trials=1, pass_threshold=0.5),
        forbid=(policy,),
    )
    with pytest.raises(SettlementError, match=r"not runnable"):
        _settle(contract, probe=None, ctx=_ctx())  # type: ignore[arg-type]
