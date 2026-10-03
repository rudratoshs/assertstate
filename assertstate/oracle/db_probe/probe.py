"""Read-only PostgreSQL oracle probe (DEVELOPMENT.md §13).

Observational only. Every failure mode raises OracleError, which the orchestrator
maps to a trial ERROR (never a silent PASS). The read-only property is proven by the
ROLE's lack of write privilege, NOT by the transaction read-only flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import errors as pgerrors
from psycopg.rows import dict_row

Row = dict[str, Any]


class OracleError(Exception):
    """Any oracle/infra failure (connect/auth/timeout/permission). -> trial ERROR."""


@dataclass(frozen=True)
class SelectResult:
    rows: list[Row]
    truncated: bool  # True if the result hit the cardinality cap (more rows existed)


class DbProbe:
    """A trusted, read-only accessor for one application database."""

    def __init__(self, dsn: str, *, statement_timeout_ms: int = 5000, default_cap: int = 10_000):
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._default_cap = default_cap

    def _connect(self, *, read_only: bool = True) -> psycopg.Connection[Row]:
        try:
            conn = psycopg.connect(self._dsn, autocommit=False, row_factory=dict_row)
        except pgerrors.InsufficientPrivilege as exc:  # pragma: no cover - auth edge
            raise OracleError(f"oracle connect denied: {exc}") from exc
        except psycopg.OperationalError as exc:
            raise OracleError(f"oracle unreachable/auth failure: {exc}") from exc
        try:
            # SET does not accept bound parameters; both values here are controlled literals
            # (an int we cast, and a fixed on/off), never user/agent input.
            ro = "on" if read_only else "off"
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {int(self._statement_timeout_ms)}")
                cur.execute(f"SET default_transaction_read_only = {ro}")
            conn.commit()
        except psycopg.Error as exc:
            conn.close()
            raise OracleError(f"oracle session setup failed: {exc}") from exc
        return conn

    def select(
        self, sql: str, params: tuple[Any, ...] = (), cap: int | None = None
    ) -> SelectResult:
        """Run a read-only parameterized SELECT. Fetches cap+1 to detect truncation."""
        cap = self._default_cap if cap is None else cap
        try:
            with self._connect(read_only=True) as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                fetched = cur.fetchmany(cap + 1)
        except pgerrors.QueryCanceled as exc:
            raise OracleError(f"oracle query timed out: {exc}") from exc
        except pgerrors.InsufficientPrivilege as exc:
            raise OracleError(f"oracle query denied (not SELECT-able): {exc}") from exc
        except psycopg.Error as exc:
            raise OracleError(f"oracle query failed: {exc}") from exc
        truncated = len(fetched) > cap
        return SelectResult(rows=list(fetched[:cap]), truncated=truncated)

    def verify_read_only(self, sentinel_table: str = "assertstate_readonly_probe") -> None:
        """Prove the role cannot write, by PRIVILEGE (not the read-only flag).

        We flip the session to READ WRITE first, then attempt an INSERT into a table the
        role has no grant on. A correct oracle role raises InsufficientPrivilege (42501).
        A successful INSERT, or any other outcome, is a configuration error -> OracleError.
        """
        try:
            conn = self._connect(read_only=False)  # test PRIVILEGE, not the read-only flag
        except OracleError:
            raise
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(f"INSERT INTO {sentinel_table} (id) VALUES ('probe')")
                except pgerrors.InsufficientPrivilege:
                    return  # correct: the role has no write privilege
                else:
                    raise OracleError(
                        f"read-only check FAILED: oracle role could INSERT into {sentinel_table} "
                        "— the role is not read-only (config error)"
                    )
                finally:
                    conn.rollback()  # discard the probe attempt either way
        except OracleError:
            raise
        except psycopg.Error as exc:
            raise OracleError(f"read-only check inconclusive: {exc}") from exc
        finally:
            conn.close()
