"""Build a trusted BrowserObservations from the network capture (SYSTEM-DESIGN §3.8)."""

from __future__ import annotations

from assertstate.domain.trace import BrowserObservations
from assertstate.instrumentation.network_capture import TrustedNetworkCapture


def observations_from_capture(
    capture: TrustedNetworkCapture, host_contains: str | None = None
) -> BrowserObservations:
    """Snapshot the trusted records into a BrowserObservations (status 'captured')."""
    network = tuple(
        {
            "method": r.method,
            "url": r.url,
            "status": r.status,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
        }
        for r in capture.records()
    )
    return BrowserObservations(
        network=network,
        last_causal_request_completed_at=capture.last_request_completed_at(host_contains),
        status="captured",
    )
