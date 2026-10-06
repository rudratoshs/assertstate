"""Settlement controller — `drain` (P0) and `bounded` (P1) (DEVELOPMENT.md §18; FEATURE-SPEC §5a).

`drain` observes queue state and needs no causal clock; it succeeds only when ALL hold:
    (a) no queued workflow-owned jobs
    (b) no in-flight/active workflow-owned jobs
    (c) producers can no longer enqueue work for this run (producers_closed)
    (d) downstream writes are observable (producers closed + queue empty => all jobs
        committed and visible to the read-only oracle)

`bounded` (frozen FEATURE-SPEC §5a / SYSTEM-DESIGN §6.3): wait a documented `max_wait` from
the TRUSTED last causal browser-request completion (BrowserObservations), then snapshot. The
bound is an ENVIRONMENTAL ASSUMPTION recorded in evidence — `bounded` does NOT independently
detect escaped server-side writes (that is `drain`'s job). No trusted anchor -> ERROR.

`run_correlated` (P2): completion is proven exactly like `drain` (producers closed + queue empty),
but the DELTA is then filtered to rows carrying THIS run's id (`run_id_col == run_id`), so a
concurrent OTHER run's writes are excluded without any temporal/timing inference. It requires app
cooperation: the app must stamp the run id onto its writes AND expose the drainable queue.

If a guarantee cannot be established (drain timeout/producers-open; bounded missing anchor),
that is ERROR, never FAIL (settlement uncertainty must not be laundered into a verdict).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from assertstate.domain.result import SettlementRecord
from assertstate.domain.trace import BrowserObservations
from assertstate.oracle.settlement.queue import QueueProbe, QueueState


class SettlementError(Exception):
    """A settlement guarantee could not be established. -> trial ERROR (never FAIL)."""


@dataclass(frozen=True)
class DrainResult:
    state: QueueState
    waited_s: float
    record: SettlementRecord


class SettlementController:
    def drain(
        self,
        queue: QueueProbe,
        run_id: str,
        *,
        timeout_s: float,
        poll_s: float = 0.05,
        causal_start_at: float | None = None,
    ) -> DrainResult:
        start_wall = time.time()
        start = time.monotonic()
        deadline = start + timeout_s
        state = queue.state(run_id)
        while True:
            state = queue.state(run_id)
            if state.producers_closed and state.queued == 0 and state.active == 0:
                waited = time.monotonic() - start
                return DrainResult(
                    state=state,
                    waited_s=waited,
                    record=SettlementRecord(
                        mode="drain",
                        causal_start_at=causal_start_at,
                        started_at=start_wall,
                        completed_at=time.time(),
                        bound_or_drain_signal=(
                            f"queued=0 active=0 producers_closed "
                            f"last_processed_job={state.last_processed_job}"
                        ),
                    ),
                )
            if time.monotonic() >= deadline:
                raise SettlementError(
                    f"drain not proven within {timeout_s}s for run {run_id!r}: "
                    f"queued={state.queued} active={state.active} "
                    f"producers_closed={state.producers_closed}"
                )
            time.sleep(poll_s)

    def run_correlated(
        self,
        queue: QueueProbe,
        run_id: str,
        *,
        timeout_s: float,
        poll_s: float = 0.05,
    ) -> SettlementRecord:
        """Prove the run is COMPLETE (same drain condition), for a run-correlated diff (§5a, P2).

        Completion is established exactly as `drain` (producers closed + queue empty), so a late
        worker write cannot escape the snapshot. The caller then filters the delta by
        `run_id_col == run_id` — removing temporal inference entirely. Failure to prove completion
        within `timeout_s` -> SettlementError (-> ERROR, never a silent pass).
        """
        drained = self.drain(queue, run_id, timeout_s=timeout_s, poll_s=poll_s)
        rec = drained.record
        return SettlementRecord(
            mode="run_correlated",
            causal_start_at=rec.causal_start_at,
            started_at=rec.started_at,
            completed_at=rec.completed_at,
            bound_or_drain_signal=(
                f"run_correlated: completion via queue drain ({rec.bound_or_drain_signal}); "
                f"delta filtered to run_id={run_id!r}"
            ),
        )

    def bounded(
        self,
        observations: BrowserObservations,
        *,
        max_wait_s: float | None,
        poll_s: float = 0.02,
    ) -> SettlementRecord:
        """Wait `max_wait_s` from the TRUSTED last-causal-request anchor, then allow snapshot.

        Fail closed: no trusted anchor (instrumentation absent or agent bypassed it) -> ERROR;
        unconfigured max_wait -> ERROR. `observations.last_causal_request_completed_at` is a
        time.monotonic() stamp recorded by the trusted parent-side proxy, so it shares this
        process's clock. Does NOT detect escaped writes — that is `drain`'s job (§5a).
        """
        anchor = observations.last_causal_request_completed_at
        if anchor is None:
            raise SettlementError(
                "bounded: no trusted last-causal-request anchor "
                "(instrumentation unavailable or the agent did not route through it) — "
                "cannot establish the bound"
            )
        if max_wait_s is None or max_wait_s < 0:
            raise SettlementError("bounded: max_wait is not configured")
        start_wall = time.time()
        target = anchor + float(max_wait_s)
        while time.monotonic() < target:
            time.sleep(poll_s)
        return SettlementRecord(
            mode="bounded",
            causal_start_at=anchor,
            started_at=start_wall,
            completed_at=time.time(),
            bound_or_drain_signal=(
                f"waited max_wait={max_wait_s}s from last_causal_request "
                f"(environmental propagation assumption; does not detect escaped writes)"
            ),
        )
