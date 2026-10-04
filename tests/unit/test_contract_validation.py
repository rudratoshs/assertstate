"""P0-03 contract validation (FEATURE-SPEC §2; DEVELOPMENT §7, §34)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from assertstate.contract.loader import build_contract, load_and_validate
from assertstate.domain.comparator import Comparator

REPO = Path(__file__).resolve().parents[2]


def _base(**over: object) -> dict:
    raw = {
        "task": "t",
        "app": "demo",
        "statistics": {"trials": 30, "pass_threshold": 0.85},
    }
    raw.update(over)
    return raw


def test_example_contract_is_valid() -> None:
    contract, report = load_and_validate(REPO / "contracts" / "pay-invoice.p0.yaml")
    assert report.ok, report.errors
    assert contract is not None
    assert len(contract.expect) == 2
    assert len(contract.forbid) == 2
    assert contract.statistics.trials == 30


def test_missing_task_and_app_fail_schema() -> None:
    _, report = _load_dict({"statistics": {"trials": 1, "pass_threshold": 1.0}})
    assert not report.ok
    assert any("task" in e for e in report.errors)


def test_float_money_rejected() -> None:
    raw = _base(expect=[{"db": {"query": "SELECT amount FROM p", "eq_canonical": 98.70}}])
    with pytest.raises(Exception) as exc:
        build_contract(raw)
    assert "string" in str(exc.value)


def test_string_money_accepted() -> None:
    raw = _base(expect=[{"db": {"query": "SELECT amount FROM p", "eq_canonical": "98.70"}}])
    c = build_contract(raw)
    assert c.expect[0].comparator is Comparator.EQ_CANONICAL
    assert c.expect[0].value == "98.70"


def test_numeric_comparator_parses_decimal() -> None:
    raw = _base(expect=[{"db": {"query": "SELECT n FROM p", "lt": "100"}}])
    c = build_contract(raw)
    assert c.expect[0].value == Decimal("100")


def test_in_comparator_is_tuple_of_strings() -> None:
    raw = _base(expect=[{"db": {"query": "SELECT s FROM p", "in": ["a", "b"]}}])
    c = build_contract(raw)
    assert c.expect[0].value == ("a", "b")


def test_two_comparators_rejected() -> None:
    raw = _base(expect=[{"db": {"query": "q", "equals": "x", "lt": "1"}}])
    with pytest.raises(Exception):
        build_contract(raw)


def test_db_delta_requires_settle() -> None:
    raw = _base(forbid=[{"db_delta": {"query": "SELECT id FROM p", "max_added": 1}}])
    with pytest.raises(Exception) as exc:
        build_contract(raw)
    assert "settle" in str(exc.value)


def test_db_delta_that_polices_nothing_is_rejected() -> None:
    # A db_delta with no *_where predicate AND no max_* cap can never fire (guaranteed PASS).
    # It must be a load-time ERROR, not a warning (false-PASS prevention).
    raw = _base(
        forbid=[
            {
                "db_delta": {
                    "query": "SELECT id FROM p",
                    "settle": {"mode": "drain", "queue": "p", "timeout": "10s"},
                }
            }
        ]
    )
    _, report = _load_dict(raw)
    assert not report.ok
    assert any("polices nothing" in e for e in report.errors)


def test_changed_where_shorthand_and_mapping() -> None:
    raw = _base(
        forbid=[
            {
                "db_delta": {
                    "query": "SELECT id, t FROM p",
                    "changed_where": "t != 'acme'",
                    "settle": {"mode": "drain", "queue": "p", "timeout": "10s"},
                }
            },
            {
                "db_delta": {
                    "query": "SELECT id, t FROM p",
                    "changed_where": {"before": "t = 'acme'", "after": "t != 'acme'"},
                    "settle": {"mode": "drain", "timeout": 10},
                }
            },
        ]
    )
    c = build_contract(raw)
    assert c.forbid[0].changed_where_after == "t != 'acme'"
    assert c.forbid[0].changed_where_before is None
    assert c.forbid[1].changed_where_before == "t = 'acme'"
    assert c.forbid[1].changed_where_after == "t != 'acme'"


def test_api_expect_parses() -> None:
    from assertstate.domain.contract import ApiExpect

    raw = _base(expect=[{"api": {"request": "GET /x", "jsonpath": "$.s", "equals": "ok"}}])
    c = build_contract(raw)
    assert isinstance(c.expect[0], ApiExpect)
    assert c.expect[0].jsonpath == "$.s"


def test_api_expect_non_get_rejected() -> None:
    _, report = _load_dict(
        _base(expect=[{"api": {"request": "POST /x", "jsonpath": "$.s", "equals": "ok"}}])
    )
    assert not report.ok
    assert any("GET/HEAD" in e for e in report.errors)


def test_external_shorthand_parses() -> None:
    from assertstate.domain.contract import EXT_NAVIGATION, ExternalPolicy

    c = build_contract(_base(forbid=["external_top_level_navigation"]))
    assert isinstance(c.forbid[0], ExternalPolicy)
    assert c.forbid[0].kind == EXT_NAVIGATION


def test_http_policy_parses() -> None:
    from assertstate.domain.contract import HttpPolicy

    raw = _base(
        forbid=[
            {
                "http": {
                    "match": {"method": "POST", "path": "/pay/*", "status": [200]},
                    "body_matches": [{"jsonpath": "$.error"}],
                }
            }
        ]
    )
    c = build_contract(raw)
    assert isinstance(c.forbid[0], HttpPolicy)
    assert c.forbid[0].body_matches == ("$.error",)


def test_statistics_range_guards() -> None:
    _, report = _load_dict(_base(statistics={"trials": 10, "pass_threshold": 1.5}))
    assert not report.ok
    assert any("pass_threshold" in e for e in report.errors)


def test_min_valid_trials_cannot_exceed_trials() -> None:
    _, report = _load_dict(
        _base(statistics={"trials": 5, "pass_threshold": 0.9, "min_valid_trials": 10})
    )
    assert not report.ok
    assert any("min_valid_trials" in e for e in report.errors)


def test_drain_requires_queue_and_timeout() -> None:
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT id FROM p",
                        "max_added": 1,
                        "settle": {"mode": "drain"},
                    }
                }
            ]
        )
    )
    assert not report.ok
    assert any("drain requires a `queue`" in e for e in report.errors)
    assert any("drain requires a `timeout`" in e for e in report.errors)


def test_projection_blind_predicate_is_rejected() -> None:
    # predicate reads `tenant_id` but the query only projects `id` -> diff would be blind.
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT id FROM payments WHERE invoice='x'",
                        "added_where": "tenant_id != 'acme'",
                        "settle": {"mode": "drain", "queue": "p", "timeout": "10s"},
                    }
                }
            ]
        )
    )
    assert not report.ok
    assert any("not projected" in e for e in report.errors)


def test_volatile_projection_is_rejected() -> None:
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT id, now() AS t FROM payments",
                        "max_added": 1,
                        "settle": {"mode": "drain", "queue": "p", "timeout": "10s"},
                    }
                }
            ]
        )
    )
    assert not report.ok
    assert any("volatile" in e for e in report.errors)


def test_explicit_key_must_be_projected() -> None:
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT tenant_id FROM payments",
                        "key": "id",
                        "max_added": 1,
                        "settle": {"mode": "drain", "queue": "p", "timeout": "10s"},
                    }
                }
            ]
        )
    )
    assert not report.ok
    assert any("not in the query projection" in e for e in report.errors)


def test_select_star_covers_all_columns() -> None:
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT * FROM payments WHERE invoice='x'",
                        "added_where": "tenant_id != 'acme'",
                        "settle": {"mode": "drain", "queue": "p", "timeout": "10s"},
                    }
                }
            ]
        )
    )
    assert report.ok, report.errors


def test_bounded_mode_is_runnable_with_max_wait() -> None:
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT id FROM p",
                        "max_added": 1,
                        "settle": {"mode": "bounded", "max_wait": "10s"},
                    }
                }
            ]
        )
    )
    assert report.ok, report.errors
    assert not any("not runnable" in w for w in report.warnings)  # bounded is P1-runnable now


def test_bounded_requires_max_wait() -> None:
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT id FROM p",
                        "max_added": 1,
                        "settle": {"mode": "bounded"},
                    }
                }
            ]
        )
    )
    assert not report.ok
    assert any("bounded requires a `max_wait`" in e for e in report.errors)


def test_run_correlated_is_warned_not_runnable() -> None:
    _, report = _load_dict(
        _base(
            forbid=[
                {
                    "db_delta": {
                        "query": "SELECT id FROM p",
                        "max_added": 1,
                        "settle": {"mode": "run_correlated"},
                    }
                }
            ]
        )
    )
    assert report.ok  # valid spec, but P2
    assert any("run_correlated is P2" in w for w in report.warnings)


# --- helper: validate a dict by writing it to a temp file (loader reads paths) ---
def _load_dict(raw: dict) -> tuple[object, object]:
    import tempfile

    import yaml

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump(raw, fh)
        path = fh.name
    return load_and_validate(path)
