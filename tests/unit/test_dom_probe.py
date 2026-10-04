"""Trusted DOM probe + expect.ui evaluator (FEATURE-SPEC §4.6).

The probe does a parent-side read-only GET of server-rendered HTML and matches a minimal selector
subset — agent-independent, so INV-8 holds. Tested against a tiny local HTTP server (no browser)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assertstate.domain.comparator import Comparator
from assertstate.domain.contract import UiExpect
from assertstate.oracle.db_probe.probe import OracleError
from assertstate.oracle.dom_probe.probe import DomProbe, _parse_selector
from assertstate.verifier.expect.evaluator import evaluate_ui_expect

_HTML = b"""<!doctype html>
<html><body>
  <h1>Invoice</h1>
  <div id="status">paid</div>
  <span class="amount">98.70</span>
  <div id="wrap"><b>bold</b> and <i>italic</i></div>
</body></html>
"""


@pytest.fixture
def server() -> Iterator[str]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_HTML)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


# --- selector subset ---
def test_selector_subset_parses() -> None:
    assert _parse_selector("#status") == (None, "status", None)
    assert _parse_selector(".amount") == (None, None, "amount")
    assert _parse_selector("h1") == ("h1", None, None)
    assert _parse_selector("div#status") == ("div", "status", None)
    assert _parse_selector("span.amount") == ("span", None, "amount")


@pytest.mark.parametrize("bad", ["", "a > b", "#a.b", "div[x=1]", "a,b"])
def test_unsupported_selector_rejected(bad: str) -> None:
    with pytest.raises(OracleError):
        _parse_selector(bad)


# --- probe reads real (server-rendered) HTML ---
def test_probe_reads_by_id_class_tag(server: str) -> None:
    p = DomProbe(server)
    assert p.read("/", "#status") == (True, "paid")
    assert p.read("/", ".amount") == (True, "98.70")
    assert p.read("/", "h1") == (True, "Invoice")
    assert p.read("/", "div#status") == (True, "paid")


def test_probe_captures_descendant_text(server: str) -> None:
    found, text = DomProbe(server).read("/", "#wrap")
    assert found is True and "bold" in text and "italic" in text


def test_probe_missing_selector_is_not_found(server: str) -> None:
    assert DomProbe(server).read("/", "#nope") == (False, None)


def test_probe_rejects_non_http_base_url() -> None:
    with pytest.raises(OracleError):
        DomProbe("demo://whatever").read("/", "#status")


# --- evaluator ---
def _ui(selector: str, comp: Comparator, value: object) -> UiExpect:
    return UiExpect(selector=selector, comparator=comp, value=value)


def test_ui_evaluator_equals_and_mismatch(server: str) -> None:
    p = DomProbe(server)
    assert evaluate_ui_expect(p, _ui("#status", Comparator.EQUALS, "paid")).ok is True
    r = evaluate_ui_expect(p, _ui("#status", Comparator.EQUALS, "unpaid"))
    assert r.ok is False and r.present is True


def test_ui_evaluator_absent_and_any(server: str) -> None:
    p = DomProbe(server)
    assert evaluate_ui_expect(p, _ui("#nope", Comparator.ABSENT, None)).ok is True
    assert evaluate_ui_expect(p, _ui("#status", Comparator.ANY, None)).ok is True
    # a missing selector under ANY is not present -> not ok
    assert evaluate_ui_expect(p, _ui("#nope", Comparator.ANY, None)).ok is False


# --- render='js': SPA / client-rendered DOM via headless Chrome ---
def _chrome_available() -> bool:
    from assertstate.oracle.dom_probe.probe import _find_chrome

    try:
        _find_chrome()
        return True
    except OracleError:
        return False


_JS_HTML = b"""<!doctype html><html><body>
  <div id="status">loading</div>
  <script>setTimeout(function(){document.getElementById('status').textContent='paid';},30)</script>
</body></html>"""


@pytest.fixture
def js_server() -> Iterator[str]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_JS_HTML)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.mark.skipif(not _chrome_available(), reason="no Chrome/Chromium for render='js'")
def test_js_render_executes_client_side_javascript(js_server: str) -> None:
    # render='html' sees the pre-JS value; render='js' sees the DOM after JS ran.
    p = DomProbe(js_server)
    assert p.read("/", "#status", "html") == (True, "loading")
    assert p.read("/", "#status", "js") == (True, "paid")
