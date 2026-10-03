"""Demo execution adapter (UNTRUSTED, app-write-only) — the P0 stand-in for Browser Use.

It simulates an agent driving the demo payment app: it enqueues the workflow via the
BrowserTarget's APP-write credential and claims DONE. It has NO oracle access. The real
Browser Use adapter (P0-14) lands once an LLM credential is provisioned; this proves the
canonical lifecycle without one, using the same out-of-process boundary.

Scenario (how the simulated agent behaves) is carried on the BrowserTarget by the demo
environment: `correct` enqueues one job; `slow_retry` also enqueues a delayed duplicate.
"""

from __future__ import annotations

from typing import Any

import psycopg

from assertstate.domain.trace import AgentTrace


class DemoAdapter:
    def run(
        self,
        task: str,
        browser_target: dict[str, Any],
        execution_budget: dict[str, Any],
        run_id: str,
    ) -> AgentTrace:
        app_dsn = browser_target["creds"]  # app-write credential (NOT the oracle)
        invoice = browser_target.get("invoice", "bill-december")
        scenario = browser_target.get("scenario", "correct")
        retry_delay_s = float(browser_target.get("retry_delay_s", 0.5))

        steps: list[dict[str, Any]] = []
        with psycopg.connect(app_dsn, autocommit=True) as conn, conn.cursor() as cur:
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
            steps.append({"action": "enqueue_payment", "invoice": invoice})

            if scenario == "slow_retry":
                cur.execute(
                    "INSERT INTO payment_jobs(invoice, run_id, state, process_after) "
                    "VALUES (%s, %s, 'queued', now() + make_interval(secs => %s))",
                    (invoice, run_id, retry_delay_s),
                )
                steps.append(
                    {"action": "enqueue_retry", "invoice": invoice, "delay_s": retry_delay_s}
                )

            cur.execute(
                "UPDATE run_markers SET producers_closed = true WHERE run_id = %s", (run_id,)
            )
            steps.append({"action": "close_producers"})

        # The agent CLAIMS success regardless of the real outcome (the whole point).
        return AgentTrace(steps=tuple(steps), agent_claimed_done=True)
