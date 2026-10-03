"""Snapshot construction + fail-closed guards (DEVELOPMENT.md §14, §15).

Single-query statement snapshots (the P0 path). A truncated result, a duplicate key,
or a NULL key all make a QueryResult unusable -> the orchestrator turns that into ERROR
(never PASS).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from assertstate.domain.snapshot import QueryResult, Row, Snapshot
from assertstate.oracle.db_probe.probe import DbProbe


@dataclass(frozen=True)
class SnapshotQuery:
    """One keyed query within a Snapshot."""

    query_id: str
    sql: str
    key: str  # the PK/`key:` column used to key rows (single column in P0)
    params: tuple[Any, ...] = ()
    cap: int | None = None


def _build_query_result(
    query_id: str, key: str, rows: Sequence[Row], truncated: bool
) -> QueryResult:
    rows_by_key: dict[Any, Row] = {}
    pk_unique = True
    for row in rows:
        if key not in row:
            # The projection must include the key column (DEVELOPMENT §17).
            pk_unique = False
            break
        k = row[key]
        if k is None:
            # NULL key => ambiguous identity => unusable (DEVELOPMENT §14).
            pk_unique = False
            break
        if k in rows_by_key:
            # Duplicate key => diff is undefined => unusable.
            pk_unique = False
            break
        # Freeze the captured row so observation data cannot be mutated after capture.
        rows_by_key[k] = MappingProxyType(dict(row))
    return QueryResult(
        query_id=query_id,
        # Freeze the container too: neither rows_by_key nor its rows can be mutated post-capture.
        rows_by_key=MappingProxyType(rows_by_key if pk_unique else {}),
        row_count=len(rows),
        complete=not truncated,
        truncated=truncated,
        pk_unique=pk_unique,
    )


def take_snapshot(probe: DbProbe, specs: list[SnapshotQuery]) -> Snapshot:
    """Read each query at the DB's own statement snapshot (consistency='statement')."""
    queries: dict[str, QueryResult] = {}
    for spec in specs:
        result = probe.select(spec.sql, spec.params, spec.cap)
        queries[spec.query_id] = _build_query_result(
            spec.query_id, spec.key, result.rows, result.truncated
        )
    return Snapshot(
        taken_at=datetime.now(timezone.utc),
        consistency="statement",
        queries=MappingProxyType(queries),
    )
