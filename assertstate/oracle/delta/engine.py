"""db_delta diff (DEVELOPMENT.md §16).

diff(before, after) -> Delta, keyed by PK/`key:`. O(n) over keyed rows. Both inputs
must be usable (complete, untruncated, unique-keyed); a non-usable input raises DeltaError
so the orchestrator records ERROR rather than a diff over incomplete state.
"""

from __future__ import annotations

from assertstate.domain.snapshot import Delta, QueryResult


class DeltaError(Exception):
    """A diff could not be computed over the given snapshots. -> trial ERROR."""


def diff(query_id: str, before: QueryResult, after: QueryResult) -> Delta:
    if not before.usable or not after.usable:
        raise DeltaError(
            f"{query_id}: cannot diff unusable snapshot "
            f"(before.usable={before.usable}, after.usable={after.usable})"
        )
    before_keys = set(before.rows_by_key)
    after_keys = set(after.rows_by_key)

    added = {k: after.rows_by_key[k] for k in after_keys - before_keys}
    removed = {k: before.rows_by_key[k] for k in before_keys - after_keys}
    changed = {
        k: (before.rows_by_key[k], after.rows_by_key[k])
        for k in after_keys & before_keys
        if before.rows_by_key[k] != after.rows_by_key[k]
    }
    return Delta(query_id=query_id, added=added, removed=removed, changed=changed)
