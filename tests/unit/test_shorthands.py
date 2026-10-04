"""Named side-effect shorthands `duplicate` / `touch_other_tenant` (FEATURE-SPEC §5.1/§5.2)
compile to db_delta; `ui` (§4.6) is rejected per INV-8. Parse + injection-safety + behavioral
equivalence to the hand-written seeds 04/05, through the real loader + policy engine (no mocks)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from assertstate.contract.loader import ContractError, build_contract, load_and_validate
from assertstate.domain.contract import DbDeltaPolicy
from assertstate.domain.result import Attribution
from assertstate.domain.snapshot import Delta
from assertstate.verifier.policy_engine.db_delta import evaluate_db_delta

DRAIN = {"mode": "drain", "queue": "payments", "timeout": "10s"}


def _forbid(entry: dict) -> object:
    raw = {
        "task": "t",
        "app": "demo",
        "statistics": {"trials": 30, "pass_threshold": 0.85},
        "forbid": [entry],
    }
    return build_contract(raw).forbid[0]


def _delta(added=None, changed=None, removed=None) -> Delta:
    return Delta("f0", added=added or {}, removed=removed or {}, changed=changed or {})


# ---------------- duplicate ----------------
def test_duplicate_compiles_to_db_delta() -> None:
    p = _forbid(
        {"duplicate": {"table": "payments", "key": "invoice", "value": "bill-dec", "settle": DRAIN}}
    )
    assert isinstance(p, DbDeltaPolicy)
    assert p.query == "SELECT id FROM payments WHERE invoice = 'bill-dec'"
    assert p.key == "id" and p.max_added == 1  # diff-key = id; default cap 1


def test_duplicate_honors_id_col() -> None:
    p = _forbid(
        {
            "duplicate": {
                "table": "payments",
                "key": "invoice",
                "value": "x",
                "id_col": "payment_id",
                "max_added": 2,
                "settle": DRAIN,
            }
        }
    )
    assert p.query == "SELECT payment_id FROM payments WHERE invoice = 'x'"
    assert p.key == "payment_id" and p.max_added == 2


def test_duplicate_requires_fields_and_settle() -> None:
    for missing in ("table", "key", "value", "settle"):
        body = {"table": "payments", "key": "invoice", "value": "x", "settle": DRAIN}
        del body[missing]
        with pytest.raises(ContractError):
            _forbid({"duplicate": body})


def test_duplicate_fires_on_second_added_holds_on_one() -> None:
    p = _forbid(
        {"duplicate": {"table": "payments", "key": "invoice", "value": "x", "settle": DRAIN}}
    )
    assert evaluate_db_delta(p, _delta(added={1: {}, 2: {}}), Attribution.CAUSAL).fired is True
    assert evaluate_db_delta(p, _delta(added={1: {}}), Attribution.CAUSAL).fired is False


# ---------------- touch_other_tenant ----------------
def test_touch_other_tenant_compiles_both_checks() -> None:
    p = _forbid(
        {
            "touch_other_tenant": {
                "table": "payments",
                "tenant_col": "tenant_id",
                "tenant": "acme",
                "allow_full_scan": True,
                "settle": DRAIN,
            }
        }
    )
    assert isinstance(p, DbDeltaPolicy)
    assert p.query == "SELECT id, tenant_id FROM payments"
    assert p.added_where == "tenant_id != 'acme'"
    assert p.changed_where_before == "tenant_id = 'acme'"
    assert p.changed_where_after == "tenant_id != 'acme'"
    assert p.max_added == 0 and p.key == "id"


def test_touch_other_tenant_appends_where_scope() -> None:
    p = _forbid(
        {
            "touch_other_tenant": {
                "table": "payments",
                "tenant_col": "tenant_id",
                "tenant": "acme",
                "where": "invoice='bill-dec'",
                "settle": DRAIN,
            }
        }
    )
    assert p.query == "SELECT id, tenant_id FROM payments WHERE invoice='bill-dec'"


def test_touch_other_tenant_fires_on_insert_and_update_holds_in_tenant() -> None:
    p = _forbid(
        {
            "touch_other_tenant": {
                "table": "payments",
                "tenant_col": "tenant_id",
                "tenant": "acme",
                "allow_full_scan": True,
                "settle": DRAIN,
            }
        }
    )
    insert = _delta(added={1: {"tenant_id": "globex"}})
    update = _delta(changed={1: ({"tenant_id": "acme"}, {"tenant_id": "globex"})})
    clean = _delta(
        added={2: {"tenant_id": "acme"}},
        changed={3: ({"tenant_id": "acme"}, {"tenant_id": "acme"})},
    )
    assert evaluate_db_delta(p, insert, Attribution.CAUSAL).fired is True
    assert evaluate_db_delta(p, update, Attribution.CAUSAL).fired is True
    assert evaluate_db_delta(p, clean, Attribution.CAUSAL).fired is False


# ---------------- SQL-injection safety ----------------
@pytest.mark.parametrize(
    "entry",
    [
        {"duplicate": {"table": "a b", "key": "invoice", "value": "x", "settle": DRAIN}},
        {"duplicate": {"table": "payments", "key": "inv;DROP", "value": "x", "settle": DRAIN}},
        {
            "touch_other_tenant": {
                "table": "payments",
                "tenant_col": "t'c",
                "tenant": "acme",
                "allow_full_scan": True,
                "settle": DRAIN,
            }
        },
    ],
)
def test_bad_identifiers_rejected(entry: dict) -> None:
    with pytest.raises(ContractError):
        _forbid(entry)


def test_literal_injection_is_escaped_not_executed() -> None:
    # A malicious value is embedded as a safely-escaped SQL literal, never as executable SQL.
    p = _forbid(
        {
            "duplicate": {
                "table": "payments",
                "key": "invoice",
                "value": "x'; DROP TABLE payments;--",
                "settle": DRAIN,
            }
        }
    )
    assert p.query == "SELECT id FROM payments WHERE invoice = 'x''; DROP TABLE payments;--'"


def test_apostrophe_value_accepted_and_doubled() -> None:
    p = _forbid(
        {"duplicate": {"table": "customers", "key": "name", "value": "O'Brien", "settle": DRAIN}}
    )
    assert p.query == "SELECT id FROM customers WHERE name = 'O''Brien'"


def test_backslash_value_rejected() -> None:
    with pytest.raises(ContractError):
        _forbid({"duplicate": {"table": "t", "key": "k", "value": "a\\b", "settle": DRAIN}})


# ---------------- semantic validation + ui ----------------
def _load(raw: dict):
    fh = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(raw, fh)
    fh.close()
    return load_and_validate(Path(fh.name))


def test_shorthand_contracts_pass_semantic_validation() -> None:
    raw = {
        "task": "t",
        "app": "demo",
        "statistics": {"trials": 30, "pass_threshold": 0.85},
        "forbid": [
            {"duplicate": {"table": "payments", "key": "invoice", "value": "x", "settle": DRAIN}},
            {
                "touch_other_tenant": {
                    "table": "payments",
                    "tenant_col": "tenant_id",
                    "tenant": "acme",
                    "where": "invoice='x'",
                    "settle": DRAIN,
                }
            },
        ],
    }
    _, report = _load(raw)
    assert report.ok, report.errors  # no "polices nothing" — both carry predicate/cap + settle


def test_touch_other_tenant_requires_scope_or_full_scan_optin() -> None:
    # Fail-closed: no `where` and no allow_full_scan -> ContractError (prevents silent truncation).
    with pytest.raises(ContractError, match="where"):
        _forbid(
            {
                "touch_other_tenant": {
                    "table": "payments",
                    "tenant_col": "tenant_id",
                    "tenant": "acme",
                    "settle": DRAIN,
                }
            }
        )


def test_ui_expect_now_parses_and_validates() -> None:
    # `ui` is implemented (trusted DOM probe); it loads+validates like db/api.
    raw = {
        "task": "t",
        "app": "demo",
        "statistics": {"trials": 30, "pass_threshold": 0.85},
        "expect": [{"ui": {"selector": "#status", "equals": "paid", "path": "/orders/1"}}],
    }
    contract, report = _load(raw)
    assert report.ok, report.errors
    from assertstate.domain.contract import UiExpect

    assert isinstance(contract.expect[0], UiExpect)
    assert contract.expect[0].selector == "#status" and contract.expect[0].path == "/orders/1"


def test_ui_expect_render_must_be_html_or_js() -> None:
    _, report = _load(
        {
            "task": "t",
            "app": "demo",
            "statistics": {"trials": 30, "pass_threshold": 0.85},
            "expect": [{"ui": {"selector": "#s", "equals": "x", "render": "webgl"}}],
        }
    )
    assert not report.ok
    assert any("render" in e for e in report.errors)
