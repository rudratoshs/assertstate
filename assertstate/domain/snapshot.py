"""Snapshot + Delta (SYSTEM-DESIGN.md §4, §6; DEVELOPMENT.md §14-§17).

Fail-closed: a truncated or non-unique-key snapshot is ERROR, never PASS.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# A captured row is a read-only mapping (snapshot.py wraps DB rows in MappingProxyType),
# so observation data cannot be mutated after capture (DEVELOPMENT.md "captured observation").
Row = Mapping[str, Any]


@dataclass(frozen=True)
class QueryResult:
    """One query's keyed result set within a Snapshot.

    Captured observation: snapshot.py builds ``rows_by_key`` as a read-only MappingProxyType
    of read-only rows, so neither the container nor its rows can be mutated after capture.
    (A QueryResult constructed by hand with a plain dict is accepted by the type but not frozen;
    only captured snapshots carry the immutability guarantee.)
    """

    query_id: str
    rows_by_key: Mapping[Hashable, Row]
    row_count: int
    complete: bool
    truncated: bool
    pk_unique: bool

    @property
    def usable(self) -> bool:
        """A result is usable for a verdict only if complete, untruncated, and unique-keyed."""
        return self.complete and not self.truncated and self.pk_unique


@dataclass(frozen=True)
class Snapshot:
    """An oracle read set at a point in time (captured ``queries`` is a read-only mapping)."""

    taken_at: datetime
    consistency: str  # "statement" (single query, P0) | "repeatable_read" (multi, P1)
    queries: Mapping[str, QueryResult] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return all(q.usable for q in self.queries.values())


@dataclass(frozen=True)
class Delta:
    """diff(before, after) for one db_delta query, keyed by PK/`key:`."""

    query_id: str
    added: dict[Hashable, Row]
    removed: dict[Hashable, Row]
    changed: dict[Hashable, tuple[Row, Row]]  # key -> (before_row, after_row)
