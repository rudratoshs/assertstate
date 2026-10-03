"""P0-01/P0-02 smoke: the package and its domain models import and construct."""

from __future__ import annotations

from decimal import Decimal

import assertstate
from assertstate.domain.comparator import Comparator, ComparatorValue
from assertstate.domain.contract import Contract, StatisticsConfig
from assertstate.domain.result import Outcome, TrialResult
from assertstate.domain.snapshot import Delta, QueryResult
from assertstate.domain.targets import BrowserTarget, ExecutionBudget, OracleTarget
from assertstate.domain.trace import AgentTrace, BrowserObservations
from assertstate.domain.verdict import RunOutcome


def test_version() -> None:
    assert isinstance(assertstate.__version__, str)


def test_domain_constructs() -> None:
    c = Contract(task="t", app="demo", statistics=StatisticsConfig(trials=1, pass_threshold=1.0))
    assert c.task == "t"
    assert BrowserTarget(base_url="http://x").creds is None
    assert OracleTarget(db_dsn_readonly="dsn").api_base is None
    assert ExecutionBudget(max_cost_usd="0.10").max_cost_usd == "0.10"
    assert AgentTrace().agent_claimed_done is False
    assert BrowserObservations().status == "out_of_scope_p0"


def test_enums() -> None:
    assert Comparator("equals") is Comparator.EQUALS
    assert Outcome.PASS.value == "PASS"
    assert RunOutcome.INCONCLUSIVE.value == "INCONCLUSIVE"


def test_comparator_value_alias_is_usable() -> None:
    v: ComparatorValue = Decimal("1.5")
    assert v == Decimal("1.5")


def test_snapshot_and_delta_shapes() -> None:
    q = QueryResult(
        "q", rows_by_key={}, row_count=0, complete=True, truncated=False, pk_unique=True
    )
    assert q.usable is True
    d = Delta(query_id="q", added={}, removed={}, changed={})
    assert d.added == {}


def test_trial_result_defaults_causal() -> None:
    tr = TrialResult(outcome=Outcome.PASS)
    assert tr.attribution.value == "causal"
