"""DemoEnvironment: brings up the disposable demo app per trial (DEVELOPMENT §19, §20).

Each trial gets a fresh template-restored DB, a seeded tenant set, and a running background
worker (the app's own async processor). Teardown stops the worker and drops the DB. Hands
the orchestrator a read-only oracle DSN (trusted) and an app-write BrowserTarget (agent).

Requires `demo-app/` on sys.path (so `worker` imports). The CLI/tests add it.
"""

from __future__ import annotations

import threading
import uuid

import psycopg
from worker import DemoWorker  # type: ignore[import-not-found]

from assertstate.env.template import ClusterConfig, build_template, create_trial_db, drop_db
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.orchestrator.environment import TrialContext


class DemoEnvironment:
    def __init__(
        self,
        cfg: ClusterConfig | None = None,
        *,
        scenario: str = "correct",
        fault: str | None = None,
        invoice: str = "bill-december",
        retry_delay_s: float = 0.5,
        pre_seed_payment: bool = False,
    ) -> None:
        self._cfg = cfg or ClusterConfig()
        self._scenario = scenario
        self._fault = fault
        self._invoice = invoice
        self._retry_delay_s = retry_delay_s
        self._pre_seed_payment = pre_seed_payment
        build_template(self._cfg)

    def setup(self, trial_index: int) -> TrialContext:
        db = f"assertstate_run_{uuid.uuid4().hex[:10]}_{trial_index}"
        create_trial_db(self._cfg, db)
        run_id = f"run-{trial_index}"
        # Seed base app state (tenants). Baseline for the invoice is 0 rows (precondition).
        with (
            psycopg.connect(self._cfg.admin_dsn(db), autocommit=True) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("INSERT INTO tenants(id) VALUES ('acme'), ('globex')")
            if self._pre_seed_payment:
                # Breaks the "0 rows for this invoice" precondition -> trial should SKIP.
                cur.execute(
                    "INSERT INTO payments(invoice, tenant_id, amount, status, idempotency_key) "
                    "VALUES (%s, 'acme', 98.70, 'paid', %s)",
                    (self._invoice, self._invoice),
                )
        # Start the app's background worker (app-side writer).
        worker = DemoWorker(self._cfg.admin_dsn(db), fault=self._fault)
        thread = threading.Thread(target=worker.run_forever, args=(run_id, 0.02), daemon=True)
        thread.start()
        browser_target = {
            "base_url": f"demo://{db}",
            "creds": self._cfg.admin_dsn(db),  # APP-write credential (never the oracle)
            "scenario": self._scenario,
            "invoice": self._invoice,
            "retry_delay_s": self._retry_delay_s,
        }
        oracle_dsn = self._cfg.oracle_dsn(db)
        # Assert the oracle role is READ-ONLY at runtime on the real run path (not just by
        # construction) — fail-closed: a writable oracle raises OracleError -> trial ERROR (§13).
        DbProbe(oracle_dsn).verify_read_only()
        return TrialContext(
            run_id=run_id,
            oracle_dsn=oracle_dsn,  # read-only (verified above)
            browser_target=browser_target,
            db_name=db,
            handle=(worker, thread),
        )

    def teardown(self, ctx: TrialContext) -> None:
        if ctx.handle is not None:
            worker, thread = ctx.handle
            worker.stop()
            thread.join(timeout=3)
        drop_db(self._cfg, ctx.db_name)
