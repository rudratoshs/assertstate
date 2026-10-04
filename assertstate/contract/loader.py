"""YAML -> typed Contract (DEVELOPMENT.md §7; FEATURE-SPEC §2).

Pipeline: YAML -> parse -> schema -> typed construction (here) -> semantic -> executable.
expect: db | api | ui. forbid: db_delta | http | external_* | the named shorthands
`duplicate`/`touch_other_tenant` (which compile to db_delta here). `ui` reads a TRUSTED
parent-side DOM probe (render: html = server-rendered, js = headless Chrome for SPAs; minimal
selector subset), never the agent's browser (INV-8).
"""

from __future__ import annotations

import re
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
    EXT_DATA_TRANSFER,
    EXT_NAVIGATION,
    EXT_REQUEST,
    ApiExpect,
    Contract,
    DbDeltaPolicy,
    DbExpect,
    Eventually,
    ExternalPolicy,
    HttpMatch,
    HttpPolicy,
    Precondition,
    SettlementConfig,
    StatisticsConfig,
    UiExpect,
)
from assertstate.domain.targets import ExecutionBudget

_COMPARATOR_NAMES = {c.value for c in Comparator}
_DB_EXPECT_KEYS = {"query", "eventually"} | _COMPARATOR_NAMES
_UI_EXPECT_KEYS = {"selector", "path", "render", "eventually"} | _COMPARATOR_NAMES

# --- SQL-safety for shorthands that BUILD SQL from fields (new validation; raw db_delta has none,
# because there the author owns the whole trusted query). Identifiers are whitelisted; literals are
# single-quoted with ' doubled — the same escaping the restricted predicate language uses, so a
# literal is safe in both the SQL query and in added_where/changed_where predicates. ---
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _ident(x: Any, where: str) -> str:
    s = str(x)
    if not _IDENT_RE.match(s):
        raise ContractError(f"{where}: {s!r} is not a valid SQL identifier")
    return s


def _sql_literal(x: Any, where: str) -> str:
    s = str(x)
    if "\\" in s or "\x00" in s:
        raise ContractError(f"{where}: value may not contain a backslash or NUL byte")
    return "'" + s.replace("'", "''") + "'"


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


def _comparator_value(comp: Comparator, raw_val: Any, where: str) -> Any:
    if comp in STRING_COMPARATORS:
        if isinstance(raw_val, float):
            raise ContractError(
                f"{where}: quote money/amount values as strings "
                f'(e.g. "98.70"), not YAML floats (precision loss)'
            )
        return str(raw_val)
    if comp in NUMERIC_COMPARATORS:
        return _to_decimal(raw_val, where)
    if comp in LIST_COMPARATORS:
        if not isinstance(raw_val, list):
            raise ContractError(f"{where}: operand must be a list")
        return tuple(str(x) for x in raw_val)
    if comp in NULLARY_COMPARATORS:
        return None
    raise ContractError(f"{where}: unhandled comparator {comp}")  # pragma: no cover


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
    value = _comparator_value(comp, body[present[0]], f"{where}.{comp.value}")

    eventually = None
    ev = body.get("eventually")
    if ev is not None:
        if not isinstance(ev, dict) or "timeout_ms" not in ev or "poll_ms" not in ev:
            raise ContractError(f"{where}.eventually: needs timeout_ms and poll_ms")
        eventually = Eventually(timeout_ms=int(ev["timeout_ms"]), poll_ms=int(ev["poll_ms"]))

    return DbExpect(query=body["query"], comparator=comp, value=value, eventually=eventually)


def _parse_ui_expect(entry: dict[str, Any], idx: int) -> UiExpect:
    where = f"expect[{idx}].ui"
    body = entry["ui"]
    if not isinstance(body, dict) or not body.get("selector"):
        raise ContractError(f"{where}: must be a mapping with a `selector`")
    unknown = set(body) - _UI_EXPECT_KEYS
    if unknown:
        raise ContractError(f"{where}: unknown keys {sorted(unknown)}")
    present = [k for k in body if k in _COMPARATOR_NAMES]
    if len(present) != 1:
        raise ContractError(f"{where}: exactly one comparator required, found {present or 'none'}")
    comp = Comparator(present[0])
    value = _comparator_value(comp, body[present[0]], f"{where}.{comp.value}")
    eventually = None
    ev = body.get("eventually")
    if ev is not None:
        if not isinstance(ev, dict) or "timeout_ms" not in ev or "poll_ms" not in ev:
            raise ContractError(f"{where}.eventually: needs timeout_ms and poll_ms")
        eventually = Eventually(timeout_ms=int(ev["timeout_ms"]), poll_ms=int(ev["poll_ms"]))
    render = str(body.get("render", "html"))
    if render not in ("html", "js"):
        raise ContractError(f"{where}.render: must be 'html' or 'js', got {render!r}")
    return UiExpect(
        selector=str(body["selector"]),
        comparator=comp,
        value=value,
        path=str(body.get("path", "")),
        render=render,
        eventually=eventually,
    )


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
        # None when omitted (event-set not policed); an explicit value (incl. 0) makes it policed.
        max_added=int(body["max_added"]) if "max_added" in body else None,
        max_changed=int(body["max_changed"]) if "max_changed" in body else None,
        max_removed=int(body["max_removed"]) if "max_removed" in body else None,
        key=body.get("key"),
    )


_API_EXPECT_KEYS = {"request", "jsonpath", "eventually"} | _COMPARATOR_NAMES
_EXTERNAL_KINDS = {EXT_NAVIGATION, EXT_REQUEST, EXT_DATA_TRANSFER}


def _parse_api_expect(entry: dict[str, Any], idx: int) -> ApiExpect:
    where = f"expect[{idx}].api"
    body = entry["api"]
    if not isinstance(body, dict) or not body.get("request") or not body.get("jsonpath"):
        raise ContractError(f"{where}: must be a mapping with `request` and `jsonpath`")
    unknown = set(body) - _API_EXPECT_KEYS
    if unknown:
        raise ContractError(f"{where}: unknown keys {sorted(unknown)}")
    present = [k for k in body if k in _COMPARATOR_NAMES]
    if len(present) != 1:
        raise ContractError(f"{where}: exactly one comparator required, found {present or 'none'}")
    comp = Comparator(present[0])
    value = _comparator_value(comp, body[present[0]], f"{where}.{comp.value}")
    ev = body.get("eventually")
    eventually = (
        Eventually(timeout_ms=int(ev["timeout_ms"]), poll_ms=int(ev["poll_ms"]))
        if isinstance(ev, dict)
        else None
    )
    return ApiExpect(
        request=str(body["request"]),
        jsonpath=str(body["jsonpath"]),
        comparator=comp,
        value=value,
        eventually=eventually,
    )


def _parse_http(entry: dict[str, Any], idx: int) -> HttpPolicy:
    where = f"forbid[{idx}].http"
    body = entry["http"]
    m = body.get("match") if isinstance(body, dict) else None
    if not isinstance(m, dict) or "path" not in m:
        raise ContractError(f"{where}.match: required mapping with a `path`")
    status = tuple(int(s) for s in (m.get("status") or []))
    match = HttpMatch(method=m.get("method"), path_glob=str(m["path"]), status=status)
    body_matches = tuple(
        str(bm["jsonpath"]) for bm in (body.get("body_matches") or []) if "jsonpath" in bm
    )
    return HttpPolicy(match=match, body_matches=body_matches)


def _parse_external(entry: Any, idx: int) -> ExternalPolicy:
    where = f"forbid[{idx}]"
    if isinstance(entry, str):
        if entry not in _EXTERNAL_KINDS:
            raise ContractError(f"{where}: unknown external policy {entry!r}")
        return ExternalPolicy(kind=entry)
    kind = next(k for k in entry if k in _EXTERNAL_KINDS)
    cfg = entry[kind] or {}
    if not isinstance(cfg, dict):
        raise ContractError(f"{where}.{kind}: must be a mapping")
    domains = tuple(str(d) for d in (cfg.get("domains") or cfg.get("deny_domains") or []))
    return ExternalPolicy(
        kind=kind,
        allow_domains=tuple(str(d) for d in (cfg.get("allow_domains") or [])),
        deny_domains=domains,
        body_match=cfg.get("body_match"),
    )


def _parse_duplicate(entry: dict[str, Any], idx: int) -> DbDeltaPolicy:
    """`duplicate` shorthand (FEATURE-SPEC §5.2) -> db_delta that caps NEW rows for one key.

    `key` is the WHERE-scope column (e.g. invoice); the DIFF key is `id_col` (default `id`),
    set on DbDeltaPolicy.key so the diff keys by identity, not by the WHERE column.
    """
    where = f"forbid[{idx}].duplicate"
    body = entry["duplicate"]
    if not isinstance(body, dict):
        raise ContractError(f"{where}: must be a mapping")
    unknown = set(body) - {"table", "key", "value", "max_added", "id_col", "settle"}
    if unknown:
        raise ContractError(f"{where}: unknown field(s) {sorted(unknown)}")
    for req in ("table", "key", "value", "settle"):
        if req not in body:
            raise ContractError(f"{where}: `{req}` is required")
    table = _ident(body["table"], f"{where}.table")
    key = _ident(body["key"], f"{where}.key")
    id_col = _ident(body.get("id_col", "id"), f"{where}.id_col")
    value_lit = _sql_literal(body["value"], f"{where}.value")
    return DbDeltaPolicy(
        query=f"SELECT {id_col} FROM {table} WHERE {key} = {value_lit}",
        settle=_parse_settle(body["settle"], where),
        max_added=int(body.get("max_added", 1)),
        key=id_col,
    )


def _parse_touch_other_tenant(entry: dict[str, Any], idx: int) -> DbDeltaPolicy:
    """`touch_other_tenant` shorthand (FEATURE-SPEC §5.1) -> db_delta with BOTH an added check
    (a row added outside the tenant) and a changed check (a row re-pointed to another tenant).

    Optional `where` scopes the projection (author-owned raw SQL, same trust as db_delta.query);
    without it the whole table is projected, which truncates -> ERROR on non-small tables.
    """
    where = f"forbid[{idx}].touch_other_tenant"
    body = entry["touch_other_tenant"]
    if not isinstance(body, dict):
        raise ContractError(f"{where}: must be a mapping")
    unknown = set(body) - {
        "table",
        "tenant_col",
        "tenant",
        "id_col",
        "where",
        "allow_full_scan",
        "settle",
    }
    if unknown:
        raise ContractError(f"{where}: unknown field(s) {sorted(unknown)}")
    for req in ("table", "tenant_col", "tenant", "settle"):
        if req not in body:
            raise ContractError(f"{where}: `{req}` is required")
    # Fail-closed against silent whole-table truncation->ERROR: require a row scope, unless the
    # author explicitly accepts a full scan (fine for small/isolated tables, e.g. the demo).
    if not body.get("where") and not body.get("allow_full_scan"):
        raise ContractError(
            f"{where}: a `where` row-scope is required (a whole-table projection truncates -> "
            "ERROR on large tables); set `allow_full_scan: true` only for small/isolated tables"
        )
    table = _ident(body["table"], f"{where}.table")
    tenant_col = _ident(body["tenant_col"], f"{where}.tenant_col")
    id_col = _ident(body.get("id_col", "id"), f"{where}.id_col")
    tenant_lit = _sql_literal(body["tenant"], f"{where}.tenant")
    query = f"SELECT {id_col}, {tenant_col} FROM {table}"
    if body.get("where"):
        query += f" WHERE {body['where']}"  # author-owned raw SQL (same trust as db_delta.query)
    return DbDeltaPolicy(
        query=query,
        settle=_parse_settle(body["settle"], where),
        added_where=f"{tenant_col} != {tenant_lit}",
        changed_where_before=f"{tenant_col} = {tenant_lit}",
        changed_where_after=f"{tenant_col} != {tenant_lit}",
        max_added=0,
        key=id_col,
    )


def _parse_expect(raw: list[Any]) -> tuple[Any, ...]:
    out: list[Any] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict) or len(entry) == 0:
            raise ContractError(f"expect[{idx}]: must be a non-empty mapping")
        if "db" in entry:
            out.append(_parse_db_expect(entry, idx))
        elif "api" in entry:
            out.append(_parse_api_expect(entry, idx))
        elif "ui" in entry:
            # §4.6 DOM fallback: read by a TRUSTED parent-side DOM probe (not the agent's browser),
            # bounded to server-rendered HTML + a minimal selector subset (oracle/dom_probe).
            out.append(_parse_ui_expect(entry, idx))
        else:
            raise ContractError(f"expect[{idx}]: unsupported entry {sorted(entry)} (db | api)")
    return tuple(out)


def _parse_forbid(raw: list[Any]) -> tuple[Any, ...]:
    out: list[Any] = []
    for idx, entry in enumerate(raw):
        if isinstance(entry, str):
            out.append(_parse_external(entry, idx))
        elif not isinstance(entry, dict) or len(entry) == 0:
            raise ContractError(f"forbid[{idx}]: must be a non-empty mapping or external shorthand")
        elif "db_delta" in entry:
            out.append(_parse_db_delta(entry, idx))
        elif "duplicate" in entry:
            out.append(_parse_duplicate(entry, idx))
        elif "touch_other_tenant" in entry:
            out.append(_parse_touch_other_tenant(entry, idx))
        elif "http" in entry:
            out.append(_parse_http(entry, idx))
        elif any(k in _EXTERNAL_KINDS for k in entry):
            out.append(_parse_external(entry, idx))
        else:
            raise ContractError(
                f"forbid[{idx}]: unsupported entry {sorted(entry)} "
                "(db_delta | duplicate | touch_other_tenant | http | external_*)"
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
