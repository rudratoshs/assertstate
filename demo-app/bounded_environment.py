"""BoundedDemoEnvironment: demo app + worker + web UI + TRUSTED capture proxy (for `bounded`).

Like BrowserDemoEnvironment, but it also starts a parent-owned TrustedNetworkCapture and
hands the orchestrator the capture (ctx.capture) so `bounded` can read the trusted
last-causal-request anchor. The agent is routed through the proxy via browser_target.proxy;
set route_through_proxy=False to simulate an agent that bypasses instrumentation (bounded
then fails closed -> ERROR). Requires `demo-app/` on sys.path.
"""

from __future__ import annotations

import threading
import uuid

import psycopg
from webapp import make_server, serve_in_thread  # type: ignore[import-not-found]
from worker import DemoWorker  # type: ignore[import-not-found]

from assertstate.env.template import ClusterConfig, build_template, create_trial_db, drop_db
from assertstate.instrumentation.network_capture import TrustedNetworkCapture
from assertstate.orchestrator.environment import TrialContext


class BoundedDemoEnvironment:
    def __init__(
        self,
        cfg: ClusterConfig | None = None,
        *,
        buggy: bool = True,
        invoice: str = "bill-december",
        route_through_proxy: bool = True,
    ) -> None:
        self._cfg = cfg or ClusterConfig()
        self._buggy = buggy
        self._invoice = invoice
        self._route = route_through_proxy
        build_template(self._cfg)

    def setup(self, trial_index: int) -> TrialContext:
        db = f"assertstate_bd_{uuid.uuid4().hex[:10]}_{trial_index}"
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

        capture = TrustedNetworkCapture()  # parent-owned; the agent never gets this object
        proxy_url = capture.start()

        browser_target = {"base_url": f"http://127.0.0.1:{port}/", "invoice": self._invoice}
        if self._route:
            browser_target["proxy"] = proxy_url  # agent routes through the trusted proxy

        return TrialContext(
            run_id=run_id,
            oracle_dsn=self._cfg.oracle_dsn(db),
            browser_target=browser_target,
            db_name=db,
            handle=(worker, wthread, server, capture),
            capture=capture,  # trusted anchor source for `bounded`
        )

    def teardown(self, ctx: TrialContext) -> None:
        if ctx.handle is not None:
            worker, wthread, server, capture = ctx.handle
            server.shutdown()
            capture.stop()
            worker.stop()
            wthread.join(timeout=3)
        drop_db(self._cfg, ctx.db_name)
