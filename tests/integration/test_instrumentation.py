"""Trusted network-capture proxy (SYSTEM-DESIGN §3.8). No DB / no LLM — runs anywhere.

Proves: requests routed through the parent-owned proxy are recorded with trusted timing;
last_causal_request_completed_at is derived from the records; and a client that BYPASSES
the proxy leaves no records (so bounded would fail closed).
"""

from __future__ import annotations

import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from assertstate.instrumentation.network_capture import TrustedNetworkCapture
from assertstate.instrumentation.observations import observations_from_capture


def _target_server() -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            n = int(self.headers.get("Content-Length", 0))
            if n:
                self.rfile.read(n)
            body = b"paid"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", 0), H)


def _via_proxy(proxy_url: str, target_url: str, data: bytes | None = None) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url}))
    with opener.open(urllib.request.Request(target_url, data=data), timeout=10) as resp:
        return resp.read().decode()


def test_proxy_records_trusted_timing() -> None:
    target = _target_server()
    threading.Thread(target=target.serve_forever, daemon=True).start()
    thost, tport = target.server_address
    base = f"http://{thost}:{tport}"

    capture = TrustedNetworkCapture()
    proxy = capture.start()
    try:
        assert _via_proxy(proxy, base + "/") == "ok"
        time.sleep(0.05)
        assert _via_proxy(proxy, base + "/pay", data=b"x") == "paid"
    finally:
        capture.stop()
        target.shutdown()

    recs = capture.records()
    assert len(recs) == 2
    assert {r.method for r in recs} == {"GET", "POST"}
    assert all(r.status == 200 for r in recs)
    assert all(r.completed_at >= r.started_at for r in recs)
    # the anchor bounded relies on: latest completion of a real request
    anchor = capture.last_request_completed_at(host_contains=str(tport))
    assert anchor is not None
    assert anchor == max(r.completed_at for r in recs)


def test_observations_built_from_capture() -> None:
    target = _target_server()
    threading.Thread(target=target.serve_forever, daemon=True).start()
    base = f"http://{target.server_address[0]}:{target.server_address[1]}"
    capture = TrustedNetworkCapture()
    proxy = capture.start()
    try:
        _via_proxy(proxy, base + "/")
    finally:
        capture.stop()
        target.shutdown()
    obs = observations_from_capture(capture)
    assert obs.status == "captured"
    assert obs.last_causal_request_completed_at is not None
    assert len(obs.network) == 1


def test_bypassing_the_proxy_leaves_no_records() -> None:
    # An agent that does NOT route through the proxy produces no trusted timing ->
    # bounded must fail closed (no anchor), never fabricate one.
    capture = TrustedNetworkCapture()
    capture.start()
    try:
        assert capture.records() == []
        assert capture.last_request_completed_at() is None
    finally:
        capture.stop()
