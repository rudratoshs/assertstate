"""INV-7 container sandbox (SYSTEM-DESIGN §10, adversarial tests 4-5). Requires Docker.

Proves the boundary a bare subprocess cannot: inside the locked-down container the agent
cannot reach host artifact paths (no mount) or trusted sockets (--network none). Skips if
Docker is unavailable (the honest gate).
"""

from __future__ import annotations

import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assertstate.adapters.runner import run_adapter

A = "tests.adversarial._adapters"


def _docker() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(
    not _docker(), reason="Docker unavailable (INV-7 needs a container)"
)


def _run(spec: str, browser_target: dict, mode: str = "container") -> object:
    return run_adapter(
        spec,
        task="t",
        browser_target=browser_target,
        execution_budget={"max_seconds": 30},
        run_id="r",
        timeout_s=120,
        mode=mode,
    )


def test_inv7_honest_roundtrip_in_container() -> None:
    trace = _run(f"{A}:HonestAdapter", {})
    assert trace.agent_claimed_done is True
    assert trace.steps == ({"action": "noop"},)


def test_inv7_host_artifact_path_unreachable(tmp_path: object) -> None:
    """Non-vacuous: a REAL host file the bare subprocess reads is unreachable in the container.

    The sentinel lives outside the only two mounts (/app/assertstate, /app/tests), so its host
    path does not exist inside the --read-only, no-extra-mount container. The subprocess child
    (host FS) reading it proves the path & adapter work; the container child failing proves INV-7
    adds filesystem isolation a bare subprocess does not.
    """
    from pathlib import Path

    sentinel = Path(str(tmp_path)) / "host-only-artifact.txt"  # not under any container mount
    marker = "SENTINEL-INV7-HOST-ONLY-9f2a"
    sentinel.write_text(marker, encoding="utf-8")
    probe = {"probe_path": str(sentinel)}

    # Baseline: the SAME path IS reachable from the bare subprocess (host filesystem).
    host = _run(f"{A}:FsProbeAdapter", probe, mode="subprocess")
    assert host.steps[0]["reachable"] is True, "sentinel must exist on host (else vacuous)"
    assert marker[:20] in host.steps[0]["detail"], "subprocess must actually read the host file"

    # INV-7: inside the locked-down container the very same host path is unreachable.
    contained = _run(f"{A}:FsProbeAdapter", probe)
    assert contained.steps[0]["reachable"] is False, "host file reachable inside the container"


def test_inv7_trusted_socket_unreachable() -> None:
    # Stand up a trusted socket on the host; the --network none container cannot reach it.
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()

    # Bind all interfaces so the host positive control reaches it via the real host IP that
    # gethostname() resolves to (which may be a LAN IP, not loopback). --network none still blocks
    # the container regardless of bind address (it has no network interface at all).
    srv = ThreadingHTTPServer(("0.0.0.0", 0), H)  # noqa: S104 - ephemeral test server, torn down
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host_ip = socket.gethostbyname(socket.gethostname())
    port = srv.server_address[1]
    probe = {"probe_host": host_ip, "probe_port": port}
    try:
        # Positive control: the SAME socket IS reachable from the bare subprocess (host network).
        # Without this the container assertion could pass vacuously (e.g. wrong host/port).
        host = _run(f"{A}:SocketProbeAdapter", probe, mode="subprocess")
        assert host.steps[0]["reachable"] is True, "socket must be reachable on host (else vacuous)"

        # INV-7: the --network none container cannot reach that same trusted socket.
        trace = _run(f"{A}:SocketProbeAdapter", probe)
        assert trace.steps[0]["reachable"] is False  # no network -> cannot reach the trusted socket
    finally:
        srv.shutdown()
