"""P1 bounded settlement controller (pure, no DB/LLM)."""

from __future__ import annotations

import time

import pytest

from assertstate.domain.trace import BrowserObservations
from assertstate.oracle.settlement.controller import SettlementController, SettlementError


def test_bounded_waits_from_anchor_and_records() -> None:
    anchor = time.monotonic()
    rec = SettlementController().bounded(
        BrowserObservations(last_causal_request_completed_at=anchor, status="captured"),
        max_wait_s=0.1,
        poll_s=0.01,
    )
    assert rec.mode == "bounded"
    assert rec.causal_start_at == anchor
    assert "environmental propagation assumption" in (rec.bound_or_drain_signal or "")
    # it waited until at least anchor + max_wait
    assert time.monotonic() >= anchor + 0.1


def test_bounded_errors_without_trusted_anchor() -> None:
    # No instrumentation / agent bypassed the proxy -> no anchor -> ERROR (fail-closed).
    with pytest.raises(SettlementError, match="no trusted last-causal-request anchor"):
        SettlementController().bounded(BrowserObservations(), max_wait_s=1.0)


def test_bounded_errors_without_max_wait() -> None:
    with pytest.raises(SettlementError, match="max_wait is not configured"):
        SettlementController().bounded(
            BrowserObservations(
                last_causal_request_completed_at=time.monotonic(), status="captured"
            ),
            max_wait_s=None,
        )


def test_bounded_anchor_already_elapsed_does_not_block() -> None:
    # If the bound already elapsed during the agent run, bounded returns promptly.
    rec = SettlementController().bounded(
        BrowserObservations(
            last_causal_request_completed_at=time.monotonic() - 5.0, status="captured"
        ),
        max_wait_s=0.1,
    )
    assert rec.mode == "bounded"
