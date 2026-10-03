"""P0-09 diff engine + P0-08 snapshot-guard logic (pure, no DB)."""

from __future__ import annotations

import pytest

from assertstate.domain.snapshot import QueryResult
from assertstate.oracle.delta.engine import DeltaError, diff
from assertstate.oracle.snapshot.snapshot import _build_query_result


def _qr(rows_by_key: dict, **over: object) -> QueryResult:
    base = dict(
        query_id="q",
        rows_by_key=rows_by_key,
        row_count=len(rows_by_key),
        complete=True,
        truncated=False,
        pk_unique=True,
    )
    base.update(over)
    return QueryResult(**base)  # type: ignore[arg-type]


def test_diff_added_removed_changed() -> None:
    before = _qr({1: {"id": 1, "v": "a"}, 2: {"id": 2, "v": "b"}})
    after = _qr({2: {"id": 2, "v": "B"}, 3: {"id": 3, "v": "c"}})
    d = diff("q", before, after)
    assert set(d.added) == {3}
    assert set(d.removed) == {1}
    assert set(d.changed) == {2}
    assert d.changed[2] == ({"id": 2, "v": "b"}, {"id": 2, "v": "B"})


def test_diff_no_change() -> None:
    before = _qr({1: {"id": 1, "v": "a"}})
    after = _qr({1: {"id": 1, "v": "a"}})
    d = diff("q", before, after)
    assert not d.added and not d.removed and not d.changed


def test_diff_unusable_snapshot_raises() -> None:
    bad = _qr({}, pk_unique=False)
    good = _qr({1: {"id": 1}})
    with pytest.raises(DeltaError):
        diff("q", bad, good)
    with pytest.raises(DeltaError):
        diff("q", good, _qr({}, truncated=True, complete=False))


# --- snapshot guards (P0-08) ---
def test_build_query_result_clean() -> None:
    rows = [{"id": 1, "t": "acme"}, {"id": 2, "t": "globex"}]
    qr = _build_query_result("q", "id", rows, truncated=False)
    assert qr.usable is True
    assert set(qr.rows_by_key) == {1, 2}


def test_build_query_result_duplicate_key_unusable() -> None:
    rows = [{"t": "acme"}, {"t": "acme"}]  # key 't' duplicated
    qr = _build_query_result("q", "t", rows, truncated=False)
    assert qr.pk_unique is False
    assert qr.usable is False


def test_build_query_result_null_key_unusable() -> None:
    rows = [{"id": None, "t": "acme"}]
    qr = _build_query_result("q", "id", rows, truncated=False)
    assert qr.pk_unique is False
    assert qr.usable is False


def test_build_query_result_missing_key_column_unusable() -> None:
    rows = [{"other": 1}]
    qr = _build_query_result("q", "id", rows, truncated=False)
    assert qr.pk_unique is False


def test_build_query_result_truncated_unusable() -> None:
    qr = _build_query_result("q", "id", [{"id": 1}], truncated=True)
    assert qr.truncated is True
    assert qr.complete is False
    assert qr.usable is False
