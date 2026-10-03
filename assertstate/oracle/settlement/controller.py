"""P0 settlement controller — `drain` only (DEVELOPMENT.md §18; FEATURE-SPEC §5a).

`drain` is the only correctness-valid settlement mode in P0 (it observes queue state and
needs no causal clock). Drain succeeds only when ALL hold:
    (a) no queued workflow-owned jobs
    (b) no in-flight/active workflow-owned jobs
    (c) producers can no longer enqueue work for this run (producers_closed)
    (d) downstream writes are observable (producers closed + queue empty => all jobs
        committed and visible to the read-only oracle)
If the guarantee cannot be established (timeout / producers never closed), that is an
ERROR, never a FAIL (settlement uncertainty must not be laundered into a contract verdict).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from assertstate.domain.result import SettlementRecord
from assertstate.oracle.settlement.queue import QueueProbe, QueueState


class SettlementError(Exception):
    """Drain could not be proven (timeout / producers open). -> trial ERROR."""


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
