"""P1 jsonpath + http + external policy logic (pure, synthetic observations)."""

from __future__ import annotations

import pytest

from assertstate.domain.contract import (
    EXT_DATA_TRANSFER,
    EXT_REQUEST,
    ExternalPolicy,
    HttpMatch,
    HttpPolicy,
)
from assertstate.domain.trace import BrowserObservations
from assertstate.verifier.jsonpath import JsonPathError, extract
from assertstate.verifier.policy_engine.external import evaluate_external
from assertstate.verifier.policy_engine.http import evaluate_http


def _obs(*recs: dict, status: str = "captured") -> BrowserObservations:
    return BrowserObservations(network=tuple(recs), status=status)


def _rec(host: str, **over: object) -> dict:
    base = {
        "method": "GET",
        "url": f"http://{host}/x",
        "status": 200,
        "host": host,
        "resp_body": "",
    }
    base.update(over)
    return base


# --- jsonpath ---
def test_jsonpath_basic() -> None:
    assert extract("$.status", {"status": "ok"}) == (True, "ok")
    assert extract("$.a.b", {"a": {"b": 1}}) == (True, 1)
    assert extract("$.a[1].x", {"a": [{}, {"x": 9}]}) == (True, 9)
    assert extract("$.missing", {}) == (False, None)
    with pytest.raises(JsonPathError):
        extract("nostart", {})


# --- http 200-with-error-body ---
def test_http_200_with_error_body_fires() -> None:
    rec = _rec(
        "app",
        method="POST",
        url="http://app/payments/42",
        status=200,
        resp_body='{"ok":false,"error":"declined"}',
    )
    p = HttpPolicy(HttpMatch("POST", "/payments/*", (200, 201, 202)), body_matches=("$.error",))
    r = evaluate_http(p, _obs(rec))
    assert r.fired is True and r.gating is True


def test_http_clean_body_does_not_fire() -> None:
    rec = _rec(
        "app", method="POST", url="http://app/payments/42", status=200, resp_body='{"ok":true}'
    )
    p = HttpPolicy(HttpMatch("POST", "/payments/*", (200,)), body_matches=("$.error",))
    assert evaluate_http(p, _obs(rec)).fired is False


def test_http_non_gating_without_capture() -> None:
    rec = _rec(
        "app", method="POST", url="http://app/payments/1", status=200, resp_body='{"error":"x"}'
    )
    p = HttpPolicy(HttpMatch("POST", "/payments/*", (200,)), body_matches=("$.error",))
    r = evaluate_http(p, _obs(rec, status="out_of_scope_p0"))
    assert r.gating is False  # no trusted capture -> cannot gate


# --- external activity ---
def test_external_request_fires_on_other_host() -> None:
    r = evaluate_external(
        ExternalPolicy(kind=EXT_REQUEST), _obs(_rec("evil.com")), app_hosts={"app"}
    )
    assert r.fired is True


def test_external_allows_app_and_allowlisted_hosts() -> None:
    p = ExternalPolicy(kind=EXT_REQUEST, allow_domains=("cdn.example",))
    assert evaluate_external(p, _obs(_rec("app")), {"app"}).fired is False
    assert evaluate_external(p, _obs(_rec("cdn.example")), {"app"}).fired is False


def test_external_deny_domains() -> None:
    p = ExternalPolicy(kind=EXT_REQUEST, deny_domains=("tracker.com",))
    assert evaluate_external(p, _obs(_rec("other.com")), {"app"}).fired is False
    assert evaluate_external(p, _obs(_rec("tracker.com")), {"app"}).fired is True


def test_external_data_transfer_body_match() -> None:
    p = ExternalPolicy(kind=EXT_DATA_TRANSFER, body_match="secret")
    hit = _rec("evil.com", url="http://evil.com/?d=secret")
    miss = _rec("evil.com", url="http://evil.com/?d=benign")
    assert evaluate_external(p, _obs(hit), {"app"}).fired is True
    assert evaluate_external(p, _obs(miss), {"app"}).fired is False
