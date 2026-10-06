"""The typed, executable Contract (DEVELOPMENT.md §7; FEATURE-SPEC §2).

Contract semantics are frozen by FEATURE-SPEC v2.3 — do not change them here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from assertstate.domain.comparator import Comparator, ComparatorValue
from assertstate.domain.targets import ExecutionBudget

# Settlement modes (FEATURE-SPEC §5 wire values). NOTE SPEC-MISMATCH-1 (DEVELOPMENT §41):
# FEATURE-SPEC uses "bounded"; SYSTEM-DESIGN prose says "bound". The wire value is "bounded".
SETTLE_DRAIN = "drain"
SETTLE_BOUNDED = "bounded"
SETTLE_RUN_CORRELATED = "run_correlated"
SETTLE_MODES = frozenset({SETTLE_DRAIN, SETTLE_BOUNDED, SETTLE_RUN_CORRELATED})
#: Runnable settlement modes: drain (P0) + bounded (P1) + run_correlated (P2, app-cooperation).
RUNNABLE_SETTLE_MODES = frozenset({SETTLE_DRAIN, SETTLE_BOUNDED, SETTLE_RUN_CORRELATED})


@dataclass(frozen=True)
class Eventually:
    """Eventual-consistency polling for db/api reads (FEATURE-SPEC §4.5)."""

    timeout_ms: int
    poll_ms: int


@dataclass(frozen=True)
class SettlementConfig:
    """When the after-snapshot may be taken (FEATURE-SPEC §5a; DEVELOPMENT §18)."""

    mode: str  # one of SETTLE_MODES; runnable: drain (P0) + bounded (P1) + run_correlated (P2)
    queue: str | None = None  # drain / run_correlated: workflow-owned queue name
    timeout_s: float | None = None  # drain / run_correlated: timeout -> ERROR on expiry
    max_wait_s: float | None = (
        None  # bounded: documented propagation bound from last causal request
    )
    run_id_col: str | None = None  # run_correlated: the column the app stamps with the run id

    @property
    def runnable(self) -> bool:
        return self.mode in RUNNABLE_SETTLE_MODES


@dataclass(frozen=True)
class DbExpect:
    """expect.db — a final-state read (FEATURE-SPEC §4.1, §2.2)."""

    query: str
    comparator: Comparator
    value: ComparatorValue  # shape determined by `comparator` (validated at load)
    eventually: Eventually | None = None


@dataclass(frozen=True)
class ApiExpect:
    """expect.api — an authenticated read-only API assertion (FEATURE-SPEC §4.2)."""

    request: str  # "GET /customers/acme/payments/latest" (method + path; GET/HEAD only)
    jsonpath: str
    comparator: Comparator
    value: ComparatorValue
    eventually: Eventually | None = None


@dataclass(frozen=True)
class UiExpect:
    """expect.ui — a DOM fallback (FEATURE-SPEC §4.6, `[P2, fallback only]`).

    Read by a TRUSTED, agent-independent DOM probe (the parent GETs the app page itself), so it
    never reads the agent's browser and never violates INV-8. Bounded to server-rendered HTML +
    a minimal CSS-selector subset (see oracle/dom_probe).
    """

    selector: str
    comparator: Comparator
    value: ComparatorValue
    path: str = ""  # page path appended to the app base_url (default: the base page)
    render: str = "html"  # "html" = server-rendered (zero-dep); "js" = headless Chrome (SPA)
    eventually: Eventually | None = None


@dataclass(frozen=True)
class DbDeltaPolicy:
    """forbid.db_delta — a causal before/after diff (FEATURE-SPEC §5; DEVELOPMENT §16)."""

    query: str
    settle: SettlementConfig
    added_where: str | None = None
    changed_where_before: str | None = None
    changed_where_after: str | None = None
    removed_where: str | None = None
    # None => that event-set is NOT policed (ignored). An explicit cap (including 0) or a
    # *_where predicate makes it policed; 0 then means "zero allowed" (strictest), not "ignore".
    max_added: int | None = None
    max_changed: int | None = None
    max_removed: int | None = None
    key: str | None = None  # natural/idempotency key when the PK is not the diff key


@dataclass(frozen=True)
class HttpMatch:
    method: str | None  # None = any
    path_glob: str  # supports a trailing '*'
    status: tuple[int, ...]  # match if response status is in this set (empty = any)


@dataclass(frozen=True)
class HttpPolicy:
    """forbid.http — a network-trace predicate (FEATURE-SPEC §4.4), e.g. 200-with-error-body.

    Fires when a captured request matches `match` AND any `body_matches` jsonpath is PRESENT
    in the response body. Requires trusted network capture (observations).
    """

    match: HttpMatch
    body_matches: tuple[str, ...] = ()


# external-activity kinds (FEATURE-SPEC §5.3)
EXT_NAVIGATION = "external_top_level_navigation"
EXT_REQUEST = "external_request"
EXT_DATA_TRANSFER = "external_data_transfer"


@dataclass(frozen=True)
class ExternalPolicy:
    """forbid.external_* — browser left the app's domains / sent data out (FEATURE-SPEC §5.3)."""

    kind: str  # one of EXT_NAVIGATION / EXT_REQUEST / EXT_DATA_TRANSFER
    allow_domains: tuple[str, ...] = ()  # if set, any other domain fires
    deny_domains: tuple[str, ...] = ()  # if set, these domains fire
    body_match: str | None = None  # data_transfer: a substring that, if sent, fires (best-effort)


@dataclass(frozen=True)
class TrajectoryCheck:
    """A required ordering of browser-observable requests (FEATURE-SPEC §3, `[P2, secondary]`).

    "Must call X before Y." Evaluated over the TRUSTED network capture (BrowserObservations),
    NEVER the agent's trace (INV-8), and gating ONLY when a trusted capture is present. Secondary:
    it never replaces the db/api oracle verdict.
    """

    steps: tuple[HttpMatch, ...]  # each a method?/path_glob matcher (status ignored here)
    ordered: bool = True  # True: each step must occur after the prior completes; False: all occur


@dataclass(frozen=True)
class DestructiveActionPolicy:
    """forbid.destructive_action — an irreversible op must not occur WITHOUT an observed approval
    (FEATURE-SPEC §5.6, `[P2]`).

    State-verified, INV-8-safe: it fires when an in-scope row is REMOVED in the trusted before/after
    diff (a delete, or an update that moves the row OUT of the `where` scope — the scope is applied
    in the SQL, so a row that leaves it drops from the after-snapshot) AND no approval record is
    present in the trusted state (`approval_query` returns no row satisfying `approval_where`). The
    approval evidence is read independently from the app's own state — NEVER from the agent's
    trace/claim (a trace-based approval gate would violate INV-8). Gating only under CAUSAL
    attribution, like db_delta. (An in-place destructive UPDATE that keeps the row in-scope is a
    `changed`, not a removal, so it is not caught by this removal-based check.)
    """

    query: str  # projects the destructive table's key, scoped by `where` (before/after diff)
    settle: SettlementConfig
    approval_query: str  # trusted read that returns approval rows
    where: str | None = None  # the destructive scope; a row leaving it (delete/move-out) = removal
    approval_where: str | None = None  # which approval rows count (None = any row present)
    key: str | None = None  # diff key (default "id")


ExpectEntry = DbExpect | ApiExpect | UiExpect
ForbidEntry = DbDeltaPolicy | HttpPolicy | ExternalPolicy | DestructiveActionPolicy


@dataclass(frozen=True)
class StatisticsConfig:
    """Wilson acceptance gate + completeness (FEATURE-SPEC §8; DEVELOPMENT §26)."""

    trials: int
    pass_threshold: float
    confidence: float = 0.95
    side: str = "one_sided"  # one_sided | two_sided
    min_valid_trials: int = 0
    max_error_rate: float = 1.0
    max_skip_rate: float = 1.0


@dataclass(frozen=True)
class Precondition:
    """A seed/fixture assertion that must hold before a trial (FEATURE-SPEC §3)."""

    description: str
    assert_query: str | None = None
    assert_equals: str | None = None


@dataclass(frozen=True)
class Contract:
    task: str
    app: str
    statistics: StatisticsConfig
    expect: tuple[ExpectEntry, ...] = field(default_factory=tuple)  # db (P0) | api (P1) | ui (P2)
    forbid: tuple[ForbidEntry, ...] = field(default_factory=tuple)  # db_delta | http | external
    budget: ExecutionBudget | None = None
    preconditions: tuple[Precondition, ...] = field(default_factory=tuple)
    trajectory: tuple[TrajectoryCheck, ...] = field(default_factory=tuple)  # P2, trusted-net only
