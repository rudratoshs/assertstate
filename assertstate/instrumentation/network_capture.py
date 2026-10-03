"""Trusted browser network capture via a parent-owned recording forward-proxy.

SYSTEM-DESIGN §3.8 / §6.3: `bounded` needs a TRUSTED source of the last causal
browser-originated request completion. This proxy runs in the trusted parent; the agent's
browser is pointed at it, but the records live here, in the parent. The agent can route
through it (honest) or bypass it (then no records -> bounded cannot establish its anchor ->
ERROR, never a fabricated bound). The agent can never READ or FORGE these records.

Scope of this slice: plain HTTP only (the demo app is HTTP). HTTPS would require TLS
interception (a documented P1+ extension); a CONNECT request is recorded as unsupported and
produces no timing anchor (fail-closed).
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_MAX_BODY = 64 * 1024  # cap captured response bodies (evidence stays bounded)

_HOP_BY_HOP = {
    "proxy-connection",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "host",
}


@dataclass(frozen=True)
class RequestRecord:
    method: str
    url: str
    status: int | None  # None if the forward failed / unsupported
    started_at: float  # time.monotonic()
    completed_at: float
    host: str = ""  # netloc of the request URL (for external-domain policies)
    resp_body: str = ""  # response body, capped (for http 200-with-error-body policy)


class TrustedNetworkCapture:
    """A trusted, append-only recorder of browser requests (verifier-owned)."""

    def __init__(self) -> None:
        self._records: list[RequestRecord] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # --- trusted-side read API (the agent never gets this object) ---
    def records(self) -> list[RequestRecord]:
        with self._lock:
            return list(self._records)

    def last_request_completed_at(self, host_contains: str | None = None) -> float | None:
        """The latest completion time of a successfully-forwarded request (optionally filtered)."""
        recs = [
            r
            for r in self.records()
            if r.status is not None and (host_contains is None or host_contains in r.url)
        ]
        return max((r.completed_at for r in recs), default=None)

    def _append(self, rec: RequestRecord) -> None:
        with self._lock:
            self._records.append(rec)  # append-only

    # --- lifecycle ---
    def start(self) -> str:
        """Start the proxy; return the address to route the browser through."""
        capture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:
                pass

            def _forward(self, method: str) -> None:
                url = self.path  # in proxy mode this is the absolute URI
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else None
                headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP}
                started = time.monotonic()
                status: int | None = None
                data = b""
                try:
                    req = urllib.request.Request(url, data=body, method=method, headers=headers)
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        status = resp.status
                        data = resp.read()
                        resp_headers = [
                            (k, v) for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP
                        ]
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    for k, v in resp_headers:
                        if k.lower() != "content-length":
                            self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(data)
                except urllib.error.HTTPError as exc:
                    status = exc.code
                    data = exc.read()
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    self.send_error(502, "proxy forward failed")
                finally:
                    capture._append(
                        RequestRecord(
                            method=method,
                            url=url,
                            status=status,
                            started_at=started,
                            completed_at=time.monotonic(),
                            host=urlparse(url).netloc,
                            resp_body=data[:_MAX_BODY].decode("utf-8", "replace"),
                        )
                    )

            def do_GET(self) -> None:
                self._forward("GET")

            def do_POST(self) -> None:
                self._forward("POST")

            def do_CONNECT(self) -> None:  # HTTPS tunnel — not supported in this slice
                capture._append(
                    RequestRecord("CONNECT", self.path, None, time.monotonic(), time.monotonic())
                )
                self.send_error(501, "HTTPS capture not supported in this slice")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        port = self._server.server_address[1]  # we bound to 127.0.0.1 above
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)
