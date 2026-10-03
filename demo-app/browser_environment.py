"""BrowserDemoEnvironment: demo app WITH a web UI, for the real-agent proof (P0-14).

Per trial: fresh template-restored DB + seeded tenants + background worker + a running web
server bound to that DB. Hands the agent a BrowserTarget base_url (the web page) and its LLM
credential via adapter_env; hands the trusted side the read-only oracle DSN. Teardown stops
the server + worker and drops the DB.

Requires `demo-app/` on sys.path (so `worker` / `webapp` import).
"""

from __future__ import annotations

import os
import threading
import uuid

import psycopg
from webapp import make_server, serve_in_thread  # type: ignore[import-not-found]
from worker import DemoWorker  # type: ignore[import-not-found]

from assertstate.env.template import ClusterConfig, build_template, create_trial_db, drop_db
from assertstate.orchestrator.environment import TrialContext


class BrowserDemoEnvironment:
    def __init__(
        self,
        cfg: ClusterConfig | None = None,
        *,
        buggy: bool = True,
        invoice: str = "bill-december",
        model: str = "gpt-4o-mini",
    ) -> None:
        self._cfg = cfg or ClusterConfig()
        self._buggy = buggy
        self._invoice = invoice
        self._model = model
        build_template(self._cfg)

    def setup(self, trial_index: int) -> TrialContext:
        db = f"assertstate_bu_{uuid.uuid4().hex[:10]}_{trial_index}"
        create_trial_db(self._cfg, db)
        run_id = f"run-{trial_index}"
        app_dsn = self._cfg.admin_dsn(db)
        with psycopg.connect(app_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO tenants(id) VALUES ('acme'), ('globex')")

        worker = DemoWorker(app_dsn, fault=None)
        wthread = threading.Thread(target=worker.run_forever, args=(run_id, 0.02), daemon=True)
        wthread.start()

        server = make_server(app_dsn, run_id, buggy=self._buggy, invoice=self._invoice)
        serve_in_thread(server)
        port = server.server_address[1]

        adapter_env = {
            "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"],  # the agent's own credential
            "ASSERTSTATE_LLM_MODEL": self._model,
        }
        # Forward the "watch the browser" flag / GIF-record path across the boundary.
        if os.environ.get("ASSERTSTATE_BROWSER_HEADFUL") == "1":
            adapter_env["ASSERTSTATE_BROWSER_HEADFUL"] = "1"
        if os.environ.get("ASSERTSTATE_BROWSER_GIF"):
            adapter_env["ASSERTSTATE_BROWSER_GIF"] = os.environ["ASSERTSTATE_BROWSER_GIF"]

        return TrialContext(
            run_id=run_id,
            oracle_dsn=self._cfg.oracle_dsn(db),  # read-only; trusted side only
            browser_target={"base_url": f"http://127.0.0.1:{port}/"},  # agent sees only the page
            db_name=db,
            handle=(worker, wthread, server),
            adapter_env=adapter_env,
        )

    def teardown(self, ctx: TrialContext) -> None:
        if ctx.handle is not None:
            worker, wthread, server = ctx.handle
            server.shutdown()
            worker.stop()
            wthread.join(timeout=3)
        drop_db(self._cfg, ctx.db_name)
