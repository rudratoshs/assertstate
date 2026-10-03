"""Read-only API oracle probe (FEATURE-SPEC §4.2, §3.7). Observational only: GET/HEAD.

A POST/PATCH/DELETE from the probe is a programming error (the oracle must never mutate the
system it measures). Any transport/HTTP failure raises OracleError -> trial ERROR.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from assertstate.oracle.db_probe.probe import OracleError

_SAFE_METHODS = {"GET", "HEAD"}


@dataclass(frozen=True)
class ApiResult:
    status: int
    json: Any  # parsed JSON body, or None if absent/not JSON


class ApiProbe:
    def __init__(self, api_base: str, creds: str | None = None, *, timeout_s: float = 10.0) -> None:
        self._base = api_base.rstrip("/")
        self._creds = creds
        self._timeout = timeout_s

    def request(self, method: str, path: str) -> ApiResult:
        method = method.upper()
        if method not in _SAFE_METHODS:
            raise OracleError(f"api oracle is observational: {method} is not a safe method")
        url = self._base + (path if path.startswith("/") else "/" + path)
        req = urllib.request.Request(url, method=method)
        if self._creds:
            req.add_header("Authorization", self._creds)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status, body = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, body = exc.code, exc.read()
        except Exception as exc:
            raise OracleError(f"api oracle request failed: {exc}") from exc
        try:
            data = json.loads(body) if body else None
        except json.JSONDecodeError:
            data = None
        return ApiResult(status=status, json=data)
