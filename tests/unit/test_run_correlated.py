"""run_correlated settlement (FEATURE-SPEC §5a, P2): completion via drain + diff filtered by run id.

Unit coverage of the two pure pieces: the controller relabels a proven drain as run_correlated (and
fails closed on timeout), and the delta filter keeps only rows carrying this run's id (so a
concurrent other run is excluded with no temporal inference). The end-to-end concurrency proof is
in tests/integration/test_run_correlated.py.
"""

from __future__ import annotations

import pytest

from assertstate.domain.snapshot import Delta
from assertstate.oracle.settlement.controller import SettlementController, SettlementError
from assertstate.oracle.settlement.queue import QueueState
from assertstate.orchestrator.runner import _filter_delta_by_run_id


class _FakeQueue:
    """Yields the given QueueStates in order (last repeats)."""

    def __init__(self, states):
        self._states = states
        self._i = 0

    def state(self, _run_id):
        s = self._states[min(self._i, len(self._states) - 1)]
        self._i += 1
        return s


def _done() -> QueueState:
    return QueueState(queued=0, active=0, producers_closed=True, last_processed_job=7)


def _busy() -> QueueState:
    return QueueState(queued=1, active=0, producers_closed=False, last_processed_job=None)


def test_run_correlated_settles_once_complete():
    rec = SettlementController().run_correlated(
        _FakeQueue([_busy(), _done()]), "runA", timeout_s=1.0, poll_s=0.001
    )
    assert rec.mode == "run_correlated"
    assert "run_id='runA'" in (rec.bound_or_drain_signal or "")


def test_run_correlated_times_out_fail_closed():
    with pytest.raises(SettlementError, match=r"drain not proven"):
        SettlementController().run_correlated(
            _FakeQueue([_busy()]), "runA", timeout_s=0.05, poll_s=0.001
        )


def test_delta_filter_keeps_only_this_run():
    delta = Delta(
        query_id="f0",
        added={1: {"id": 1, "run_id": "runA"}, 2: {"id": 2, "run_id": "runB"}},
        removed={},
        changed={},
    )
    filtered = _filter_delta_by_run_id(delta, "run_id", "runA")
    assert set(filtered.added) == {1}  # runB (a concurrent run) is excluded


def test_delta_filter_changed_uses_after_row():
    delta = Delta(
        query_id="f0",
        added={},
        removed={},
        changed={9: ({"id": 9, "run_id": "old"}, {"id": 9, "run_id": "runA"})},
    )
    assert set(_filter_delta_by_run_id(delta, "run_id", "runA").changed) == {9}
    assert set(_filter_delta_by_run_id(delta, "run_id", "other").changed) == set()
