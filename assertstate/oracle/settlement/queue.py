"""Read-only observation of the workflow queue for settlement (DEVELOPMENT.md §18).

The settlement controller must observe queue state WITHOUT writing — so the QueueProbe
reads through the read-only oracle (the oracle role has SELECT on payment_jobs/run_markers,
no write). This keeps settlement observational, like every other oracle read.
"""

from __future__ import annotations

from dataclasses import dataclass

from assertstate.oracle.db_probe.probe import DbProbe


@dataclass(frozen=True)
class QueueState:
    queued: int
    active: int
    producers_closed: bool
    last_processed_job: int | None


class QueueProbe:
    """Observes a run's queue state via read-only SELECTs.

    DEMO-COUPLED: this probe reads the demo app's fixed queue schema (`payment_jobs` + `run_markers`
    keyed by `run_id`). The contract's `settle.queue` names the workflow-owned queue for the record,
    but this probe does not parameterize on it — drain settlement is a demo-env capability. A real
    `--config` app that wants drain supplies its own queue-state probe for its own schema.
    """

    def __init__(self, probe: DbProbe) -> None:
        self._p = probe

    def state(self, run_id: str) -> QueueState:
        queued = self._p.select(
            "SELECT count(*) AS n FROM payment_jobs WHERE run_id = %s AND state = 'queued'",
            (run_id,),
        ).rows[0]["n"]
        active = self._p.select(
            "SELECT count(*) AS n FROM payment_jobs WHERE run_id = %s AND state = 'active'",
            (run_id,),
        ).rows[0]["n"]
        marker = self._p.select(
            "SELECT producers_closed, last_processed_job FROM run_markers WHERE run_id = %s",
            (run_id,),
        ).rows
        producers_closed = bool(marker[0]["producers_closed"]) if marker else False
        last_job = marker[0]["last_processed_job"] if marker else None
        return QueueState(
            queued=int(queued),
            active=int(active),
            producers_closed=producers_closed,
            last_processed_job=last_job,
        )
