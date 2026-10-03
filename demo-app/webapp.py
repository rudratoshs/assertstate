"""Minimal web UI for the demo app, so a REAL browser agent has something to drive.

A single invoice page with a "Pay" button. POSTing /pay enqueues the payment via the app's
own DB credential. The `buggy` variant also schedules a delayed retry -> a duplicate payment
committed after an early snapshot: the app-level false-success a real agent cannot see (it
just sees "Payment successful"). The oracle/verdict path is unchanged.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg

_PAGE = """<!doctype html><html><head><title>Acme Billing</title></head>
<body style="font-family:sans-serif;max-width:40em;margin:3em auto">
<h1>Invoice bill-december</h1>
<p>Amount due: <b>$98.70</b> &mdash; tenant acme</p>
<form method="post" action="/pay">
  <button type="submit" style="padding:0.6em 1.4em;font-size:1.1em">Pay invoice</button>
</form>
</body></html>"""

_DONE = """<!doctype html><html><head><title>Paid</title></head>
<body style="font-family:sans-serif;max-width:40em;margin:3em auto">
<h1>Payment successful</h1>
<p>Invoice bill-december has been paid.</p>
</body></html>"""


def make_server(
    dsn: str, run_id: str, *, buggy: bool, invoice: str = "bill-december"
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # silence request logging
            pass

        def _send(self, body: str, status: int = 200) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._send(_PAGE)

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/pay":
                self._send("not found", 404)
                return
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO run_markers(run_id, producers_closed) VALUES (%s, false) "
                    "ON CONFLICT (run_id) DO NOTHING",
                    (run_id,),
                )
                cur.execute(
                    "INSERT INTO payment_jobs(invoice, run_id, state, process_after) "
                    "VALUES (%s, %s, 'queued', now())",
                    (invoice, run_id),
                )
                if buggy:
                    # The app's broken idempotency: a delayed retry -> duplicate payment.
                    cur.execute(
                        "INSERT INTO payment_jobs(invoice, run_id, state, process_after) "
                        "VALUES (%s, %s, 'queued', now() + make_interval(secs => 0.5))",
                        (invoice, run_id),
                    )
                cur.execute(
                    "UPDATE run_markers SET producers_closed = true WHERE run_id = %s", (run_id,)
                )
            self._send(_DONE)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t
