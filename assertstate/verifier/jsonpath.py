"""Minimal JSONPath for expect.api and http body_matches (no dependency).

Supports `$`, `$.key`, `$.a.b`, `$.a[0].b`. Returns (found, value). Deliberately small —
enough for status/error-field extraction; richer paths are a follow-up if needed.
"""

from __future__ import annotations

import re
from typing import Any

_SEG = re.compile(r"\.(?P<key>[A-Za-z_][\w]*)|\[(?P<idx>\d+)\]")


class JsonPathError(Exception):
    """A JSONPath expression was malformed."""


def extract(path: str, obj: Any) -> tuple[bool, Any]:
    """Return (found, value). found is False if any segment is missing/out of range."""
    if not path.startswith("$"):
        raise JsonPathError(f"jsonpath must start with '$': {path!r}")
    rest = path[1:]
    consumed = 0
    cur = obj
    for m in _SEG.finditer(rest):
        if m.start() != consumed:
            raise JsonPathError(f"unparseable jsonpath near {rest[consumed:]!r}")
        consumed = m.end()
        key, idx = m.group("key"), m.group("idx")
        if key is not None:
            if not isinstance(cur, dict) or key not in cur:
                return (False, None)
            cur = cur[key]
        else:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return (False, None)
            cur = cur[i]
    if consumed != len(rest):
        raise JsonPathError(f"unparseable jsonpath: {path!r}")
    return (True, cur)
