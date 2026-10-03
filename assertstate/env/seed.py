"""Per-trial seeding + precondition verification (DEVELOPMENT.md §21; FEATURE-SPEC §3).

Seed DATA is applied via app-level writes; preconditions are VERIFIED through the read-only
oracle. If a precondition cannot be established, the trial is SKIPPED (never FAIL) — this is
what makes the duplicate baseline (0 rows for the key) a real guarantee (FEATURE-SPEC §5.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from assertstate.domain.contract import Precondition
from assertstate.oracle.db_probe.probe import DbProbe, OracleError


class SeedError(Exception):
    """Seed data could not be applied (infrastructure). -> trial ERROR."""


def apply_fixtures(app_dsn: str, statements: Sequence[str]) -> None:
    """Apply fixture SQL via app-level writes (NOT the oracle role)."""
    try:
        with psycopg.connect(app_dsn, autocommit=True) as conn, conn.cursor() as cur:
            for sql in statements:
                cur.execute(sql)
    except psycopg.Error as exc:
        raise SeedError(f"fixture apply failed: {exc}") from exc


@dataclass(frozen=True)
class PreconditionResult:
    description: str
    established: bool
    detail: str


def verify_preconditions(
    probe: DbProbe, preconditions: Sequence[Precondition]
) -> list[PreconditionResult]:
    """Check each precondition through the read-only oracle.

    A precondition with an assert_query is established iff the first column of the first row
    equals assert_equals (string compare). A precondition with no query is informational and
    treated as established. Oracle failure propagates as OracleError (-> ERROR), not SKIPPED.
    """
    out: list[PreconditionResult] = []
    for pc in preconditions:
        if not pc.assert_query:
            out.append(PreconditionResult(pc.description, True, "no assertion (informational)"))
            continue
        res = probe.select(pc.assert_query)  # may raise OracleError -> ERROR upstream
        if not res.rows:
            out.append(PreconditionResult(pc.description, False, "query returned no rows"))
            continue
        first_row = res.rows[0]
        value = str(next(iter(first_row.values())))
        ok = pc.assert_equals is None or value == pc.assert_equals
        out.append(
            PreconditionResult(pc.description, ok, f"got {value!r} expected {pc.assert_equals!r}")
        )
    return out


def preconditions_established(results: Sequence[PreconditionResult]) -> bool:
    return all(r.established for r in results)


__all__ = [
    "SeedError",
    "OracleError",
    "PreconditionResult",
    "apply_fixtures",
    "verify_preconditions",
    "preconditions_established",
]
