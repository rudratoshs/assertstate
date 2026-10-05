"""Trusted-capture wiring for real `--config` apps (FEATURE-SPEC §3).

Closes the gap where http/external/trajectory policies were non-gating against a real app: the
capture decision (`capture_enabled`), the proxy bind/advertise split by sandbox mode
(`_capture_addrs`), and the proxy address helper. The parent-owned capture itself is exercised
end-to-end in tests/integration/test_instrumentation.py.
"""

from __future__ import annotations

from assertstate.cli import _capture_addrs
from assertstate.config.environment import capture_enabled
from assertstate.config.model import BrowserConfig
from assertstate.instrumentation.network_capture import TrustedNetworkCapture, proxy_url


def test_capture_auto_on_for_http():
    assert capture_enabled(BrowserConfig(base_url="http://app.local/")) is True


def test_capture_auto_off_for_https():
    # HTTPS needs TLS interception (follow-up) -> stays non-gating, never a false FAIL.
    assert capture_enabled(BrowserConfig(base_url="https://app.local/")) is False


def test_capture_on_forces_even_for_https():
    assert capture_enabled(BrowserConfig(base_url="https://app.local/", capture="on")) is True


def test_capture_off_disables_even_for_http():
    assert capture_enabled(BrowserConfig(base_url="http://app.local/", capture="off")) is False


def test_capture_addrs_subprocess_is_loopback():
    assert _capture_addrs("subprocess") == ("127.0.0.1", "127.0.0.1")


def test_capture_addrs_container_uses_host_gateway():
    # Container agent reaches the parent over the Docker host gateway, so the proxy binds on all
    # interfaces and is advertised as host.docker.internal.
    assert _capture_addrs("container") == ("0.0.0.0", "host.docker.internal")


def test_proxy_url_composes_advertise_host():
    assert proxy_url("host.docker.internal", 51234) == "http://host.docker.internal:51234"


def test_capture_binds_and_exposes_port():
    cap = TrustedNetworkCapture()
    try:
        addr = cap.start(bind_host="127.0.0.1")
        assert cap.port is not None and str(cap.port) in addr
    finally:
        cap.stop()
