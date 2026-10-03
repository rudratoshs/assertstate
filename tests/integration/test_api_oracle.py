"""P1 API oracle (expect.api) against a standalone JSON server. No DB — runs anywhere."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assertstate.domain.comparator import Comparator
from assertstate.domain.contract import ApiExpect
from assertstate.oracle.api_probe.probe import ApiProbe, OracleError
from assertstate.verifier.expect.evaluator import evaluate_api_expect


def _api_server() -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:
            body = b'{"status":"succeeded","amount":"98.70"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", 0), H)


def _base() -> tuple[ThreadingHTTPServer, str]:
    srv = _api_server()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_api_expect_passes() -> None:
    srv, base = _base()
    try:
        e = ApiExpect("GET /latest", "$.status", Comparator.EQUALS, "succeeded")
        assert evaluate_api_expect(ApiProbe(base), e).ok is True
    finally:
        srv.shutdown()


def test_api_expect_wrong_value_fails() -> None:
    srv, base = _base()
    try:
        e = ApiExpect("GET /latest", "$.status", Comparator.EQUALS, "failed")
        assert evaluate_api_expect(ApiProbe(base), e).ok is False
    finally:
        srv.shutdown()


def test_api_expect_missing_path_fails_not_errors() -> None:
    srv, base = _base()
    try:
        e = ApiExpect("GET /latest", "$.nope", Comparator.EQUALS, "x")
        r = evaluate_api_expect(ApiProbe(base), e)
        assert r.ok is False and r.present is False
    finally:
        srv.shutdown()


def test_api_probe_rejects_unsafe_method() -> None:
    srv, base = _base()
    try:
        with pytest.raises(OracleError, match="observational"):
            ApiProbe(base).request("POST", "/latest")
    finally:
        srv.shutdown()
