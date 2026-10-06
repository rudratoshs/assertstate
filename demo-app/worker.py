"""P0 demo application: the controllable async retry worker (DEVELOPMENT.md §19).

This is the APPLICATION side (it writes, using app-level credentials) — NOT the oracle.
It drains a `payment_jobs` queue and inserts `payments`, with controllable delay and fault
injection so the acceptance scenarios (wrong value, duplicate, slow-retry duplicate,
cross-tenant, missing) can be produced on demand. Schema is frozen DEVELOPMENT §19:
payment_jobs(id, invoice, run_id, state, process_after, attempts) — no extra columns.
"""

from __future__ import annotations

import threading
import time

import psycopg

# Fault modes injected at the application layer (not stored on the job row).
FAULT_NONE = None
FAULT_WRONG_AMOUNT = "wrong_amount"
FAULT_CROSS_TENANT = "cross_tenant"
FAULT_MISSING = "missing"  # claims done but never writes the payment


class DemoWorker:
    def __init__(
        self,
        app_dsn: str,
        *,
        tenant: str = "acme",
        amount: str = "98.70",
        fault: str | None = FAULT_NONE,
    ) -> None:
        self._dsn = app_dsn
        self._tenant = tenant
        self._amount = amount
        self._fault = fault
        self._stop = threading.Event()

    def _conn(self) -> psycopg.Connection[tuple]:
        return psycopg.connect(self._dsn, autocommit=True)

    def ensure_run(self, run_id: str) -> None:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO run_markers(run_id, producers_closed) VALUES (%s, false) "
                "ON CONFLICT (run_id) DO NOTHING",
                (run_id,),
            )

    def enqueue(self, run_id: str, invoice: str, process_after_s: float = 0.0) -> int:
        """Enqueue one run-owned payment job (optionally scheduled in the future)."""
        self.ensure_run(run_id)
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO payment_jobs(invoice, run_id, state, process_after) "
                "VALUES (%s, %s, 'queued', now() + make_interval(secs => %s)) RETURNING id",
                (invoice, run_id, float(process_after_s)),
            )
            row = cur.fetchone()
            assert row is not None
            return int(row[0])

    def close_producers(self, run_id: str) -> None:
        """Signal that no more jobs will be enqueued for this run (drain condition c)."""
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                "UPDATE run_markers SET producers_closed = true WHERE run_id = %s", (run_id,)
            )

    def process_due(self, run_id: str) -> int:
        """Process every currently-due queued job once. Returns how many were processed."""
        processed = 0
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT id, invoice FROM payment_jobs "
                "WHERE run_id = %s AND state = 'queued' AND process_after <= now() ORDER BY id",
                (run_id,),
            )
            jobs = cur.fetchall()
            for job_id, invoice in jobs:
                cur.execute(
                    "UPDATE payment_jobs SET state='active', attempts=attempts+1 WHERE id=%s",
                    (job_id,),
                )
                if self._fault != FAULT_MISSING:
                    tenant = "globex" if self._fault == FAULT_CROSS_TENANT else self._tenant
                    amount = "9.87" if self._fault == FAULT_WRONG_AMOUNT else self._amount
                    cur.execute(
                        "INSERT INTO payments"
                        "(invoice, tenant_id, amount, status, idempotency_key, run_id) "
                        "VALUES (%s, %s, %s, 'paid', %s, %s)",
                        (invoice, tenant, amount, invoice, run_id),
                    )
                cur.execute("UPDATE payment_jobs SET state='done' WHERE id=%s", (job_id,))
                cur.execute(
                    "UPDATE run_markers SET last_processed_job=%s WHERE run_id=%s",
                    (job_id, run_id),
                )
                processed += 1
        return processed

    def run_forever(self, run_id: str, poll_s: float = 0.02) -> None:
        """Background loop: process due jobs until stop() (models a separate worker process)."""
        while not self._stop.is_set():
            self.process_due(run_id)
            time.sleep(poll_s)

    def stop(self) -> None:
        self._stop.set()
