"""YAML -> typed Contract (DEVELOPMENT.md §7; FEATURE-SPEC §2).

Pipeline: YAML -> parse -> schema -> typed construction (here) -> semantic -> executable.
P0 supports expect.db and forbid.db_delta only; api/http/external/shorthands are P1 and
are rejected with a clear message so P0 contracts stay honest.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from assertstate.contract.errors import ContractError, ValidationReport
from assertstate.contract.schema import validate_schema
from assertstate.domain.comparator import (
    LIST_COMPARATORS,
    NULLARY_COMPARATORS,
    NUMERIC_COMPARATORS,
    STRING_COMPARATORS,
    Comparator,
)
from assertstate.domain.contract import (
    Contract,
    DbDeltaPolicy,
    DbExpect,
    Eventually,
    Precondition,
    SettlementConfig,
    StatisticsConfig,
)
from assertstate.domain.targets import ExecutionBudget

_COMPARATOR_NAMES = {c.value for c in Comparator}
_DB_EXPECT_KEYS = {"query", "eventually"} | _COMPARATOR_NAMES


def _parse_duration_s(value: Any, where: str) -> float:
    """Accept 10, 10.0, '10', or '10s' -> seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip()
        if v.endswith("s"):
            v = v[:-1]
        try:
            return float(v)
        except ValueError:
            raise ContractError(f"{where}: cannot parse duration {value!r}")
    raise ContractError(f"{where}: cannot parse duration {value!r}")


def _to_decimal(value: Any, where: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ContractError(f"{where}: not a number: {value!r}")
    if not d.is_finite():
        raise ContractError(f"{where}: non-finite numbers are not allowed (fail-closed)")
    return d


def _parse_db_expect(entry: dict[str, Any], idx: int) -> DbExpect:
    where = f"expect[{idx}].db"
    body = entry["db"]
    if not isinstance(body, dict) or not body.get("query"):
        raise ContractError(f"{where}: must be a mapping with a `query`")

    unknown = set(body) - _DB_EXPECT_KEYS
    if unknown:
        raise ContractError(f"{where}: unknown keys {sorted(unknown)}")

    present = [k for k in body if k in _COMPARATOR_NAMES]
    if len(present) != 1:
        raise ContractError(f"{where}: exactly one comparator required, found {present or 'none'}")
    comp = Comparator(present[0])
    raw_val = body[present[0]]

    value: Any
    if comp in STRING_COMPARATORS:
        if isinstance(raw_val, float):
            raise ContractError(
                f"{where}.{comp.value}: quote money/amount values as strings "
                f'(e.g. "98.70"), not YAML floats (precision loss)'
            )
        value = str(raw_val)
    elif comp in NUMERIC_COMPARATORS:
        value = _to_decimal(raw_val, f"{where}.{comp.value}")
    elif comp in LIST_COMPARATORS:
        if not isinstance(raw_val, list):
            raise ContractError(f"{where}.in: operand must be a list")
        value = tuple(str(x) for x in raw_val)
    elif comp in NULLARY_COMPARATORS:
        value = None
    else:  # pragma: no cover - exhaustive
        raise ContractError(f"{where}: unhandled comparator {comp}")

    eventually = None
    ev = body.get("eventually")
    if ev is not None:
        if not isinstance(ev, dict) or "timeout_ms" not in ev or "poll_ms" not in ev:
            raise ContractError(f"{where}.eventually: needs timeout_ms and poll_ms")
        eventually = Eventually(timeout_ms=int(ev["timeout_ms"]), poll_ms=int(ev["poll_ms"]))

    return DbExpect(query=body["query"], comparator=comp, value=value, eventually=eventually)


def _parse_settle(raw: Any, where: str) -> SettlementConfig:
    if not isinstance(raw, dict) or "mode" not in raw:
        raise ContractError(f"{where}.settle: required mapping with a `mode`")
    mode = str(raw["mode"])
    timeout_s = (
        _parse_duration_s(raw["timeout"], f"{where}.settle.timeout") if "timeout" in raw else None
    )
    max_wait_s = (
        _parse_duration_s(raw["max_wait"], f"{where}.settle.max_wait")
        if "max_wait" in raw
        else None
    )
    return SettlementConfig(
        mode=mode, queue=raw.get("queue"), timeout_s=timeout_s, max_wait_s=max_wait_s
    )


def _parse_db_delta(entry: dict[str, Any], idx: int) -> DbDeltaPolicy:
    where = f"forbid[{idx}].db_delta"
    body = entry["db_delta"]
    if not isinstance(body, dict) or not body.get("query"):
        raise ContractError(f"{where}: must be a mapping with a `query`")
    if "settle" not in body:
        raise ContractError(f"{where}: `settle` is required (FEATURE-SPEC §5)")

    cw = body.get("changed_where")
    cw_before = cw_after = None
    if isinstance(cw, str):
        cw_after = cw  # shorthand: string == {after: <expr>}
    elif isinstance(cw, dict):
        cw_before = cw.get("before")
        cw_after = cw.get("after")
    elif cw is not None:
        raise ContractError(f"{where}.changed_where: must be a string or {{before, after}}")

    return DbDeltaPolicy(
        query=body["query"],
        settle=_parse_settle(body["settle"], where),
        added_where=body.get("added_where"),
        changed_where_before=cw_before,
        changed_where_after=cw_after,
        removed_where=body.get("removed_where"),
        max_added=int(body.get("max_added", 0)),
        max_changed=int(body.get("max_changed", 0)),
        max_removed=int(body.get("max_removed", 0)),
        key=body.get("key"),
    )


def _parse_expect(raw: list[Any]) -> tuple[DbExpect, ...]:
    out: list[DbExpect] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict) or len(entry) == 0:
            raise ContractError(f"expect[{idx}]: must be a non-empty mapping")
        if "db" in entry:
            out.append(_parse_db_expect(entry, idx))
        elif "api" in entry:
            raise ContractError(f"expect[{idx}].api: API oracle is P1, not supported in P0")
        else:
            raise ContractError(f"expect[{idx}]: unsupported entry {sorted(entry)} (P0: db only)")
    return tuple(out)


def _parse_forbid(raw: list[Any]) -> tuple[DbDeltaPolicy, ...]:
    out: list[DbDeltaPolicy] = []
    for idx, entry in enumerate(raw):
        if isinstance(entry, str):
            raise ContractError(
                f"forbid[{idx}]: `{entry}` (external/http shorthand) is P1, not supported in P0"
            )
        if not isinstance(entry, dict) or len(entry) == 0:
            raise ContractError(f"forbid[{idx}]: must be a non-empty mapping")
        if "db_delta" in entry:
            out.append(_parse_db_delta(entry, idx))
        elif "http" in entry or any(k.startswith("external") for k in entry):
            raise ContractError(f"forbid[{idx}]: http/external policy is P1, not supported in P0")
        else:
            raise ContractError(
                f"forbid[{idx}]: unsupported entry {sorted(entry)} (P0: db_delta only)"
            )
    return tuple(out)


def _parse_statistics(raw: dict[str, Any]) -> StatisticsConfig:
    return StatisticsConfig(
        trials=int(raw["trials"]),
        pass_threshold=float(raw["pass_threshold"]),
        confidence=float(raw.get("confidence", 0.95)),
        side=str(raw.get("side", "one_sided")),
        min_valid_trials=int(raw.get("min_valid_trials", 0)),
        max_error_rate=float(raw.get("max_error_rate", 1.0)),
        max_skip_rate=float(raw.get("max_skip_rate", 1.0)),
    )


def _parse_budget(raw: dict[str, Any]) -> ExecutionBudget:
    max_cost = raw.get("max_cost_usd")
    if isinstance(max_cost, float):
        raise ContractError(
            'budget.max_cost_usd: quote as a string (e.g. "0.10"), not a YAML float'
        )
    return ExecutionBudget(
        max_steps=int(raw["max_steps"]) if "max_steps" in raw else None,
        max_cost_usd=str(max_cost) if max_cost is not None else None,
        max_seconds=float(raw["max_seconds"]) if "max_seconds" in raw else None,
    )


def _parse_preconditions(raw: list[Any]) -> tuple[Precondition, ...]:
    out: list[Precondition] = []
    for idx, entry in enumerate(raw):
        if isinstance(entry, str):
            out.append(Precondition(description=entry))
        elif isinstance(entry, dict):
            out.append(
                Precondition(
                    description=str(entry.get("description", f"precondition[{idx}]")),
                    assert_query=entry.get("assert_query"),
                    assert_equals=(
                        str(entry["assert_equals"]) if "assert_equals" in entry else None
                    ),
                )
            )
        else:
            raise ContractError(f"preconditions[{idx}]: must be a string or mapping")
    return tuple(out)


def build_contract(raw: dict[str, Any]) -> Contract:
    """Typed construction. Assumes schema already validated. Raises ContractError on bad values."""
    return Contract(
        task=raw["task"],
        app=raw["app"],
        statistics=_parse_statistics(raw["statistics"]),
        expect=_parse_expect(raw.get("expect") or []),
        forbid=_parse_forbid(raw.get("forbid") or []),
        budget=_parse_budget(raw["budget"]) if raw.get("budget") else None,
        preconditions=_parse_preconditions(raw.get("preconditions") or []),
    )


def hash_contract(path: str | Path) -> str:
    """SHA-256 of the raw contract file (for RunMetadata provenance)."""
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_and_validate(path: str | Path) -> tuple[Contract | None, ValidationReport]:
    """Load + schema + typed + semantic. Returns (contract_or_None, report)."""
    from assertstate.contract.semantic import validate_semantics

    report = ValidationReport()
    text = Path(path).read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        report.errors.append(f"contract: invalid YAML: {exc}")
        return None, report

    schema_errors = validate_schema(raw)
    if schema_errors:
        report.errors.extend(schema_errors)
        return None, report

    try:
        contract = build_contract(raw)
    except ContractError as exc:
        report.errors.append(str(exc))
        return None, report

    report.extend(validate_semantics(contract))
    return (contract if report.ok else None), report
