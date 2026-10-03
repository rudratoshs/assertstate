"""Fail-closed redaction + JSON-safe serialization for evidence (DEVELOPMENT §28).

Sensitive keys (credentials/DSNs/secrets) are masked by default. If redaction itself
raises, callers must emit NOTHING rather than an unredacted artifact.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

MASK = "***REDACTED***"
_SENSITIVE = ("cred", "dsn", "password", "secret", "token", "authorization", "cookie", "api_key")
_MAX_STR = 4096


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in _SENSITIVE)


def json_safe(obj: Any) -> Any:
    """Convert dataclasses/enums/Decimal/datetime/Mapping/tuple into JSON-serializable data."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        if isinstance(obj, str) and len(obj) > _MAX_STR:
            return obj[:_MAX_STR] + "...<truncated>"
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return json_safe(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): (MASK if _is_sensitive(str(k)) else json_safe(v)) for k, v in obj.items()}
    if hasattr(obj, "items"):  # Mapping / MappingProxyType
        return {str(k): (MASK if _is_sensitive(str(k)) else json_safe(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in obj]
    return str(obj)
