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
#: Runnable settlement modes: drain (P0) + bounded (P1). run_correlated stays P2/deferred.
RUNNABLE_SETTLE_MODES = frozenset({SETTLE_DRAIN, SETTLE_BOUNDED})


@dataclass(frozen=True)
class Eventually:
    """Eventual-consistency polling for db/api reads (FEATURE-SPEC §4.5)."""

    timeout_ms: int
    poll_ms: int


@dataclass(frozen=True)
class SettlementConfig:
    """When the after-snapshot may be taken (FEATURE-SPEC §5a; DEVELOPMENT §18)."""

    mode: str  # one of SETTLE_MODES; runnable: drain (P0) + bounded (P1)
    queue: str | None = None  # drain: workflow-owned queue name
    timeout_s: float | None = None  # drain: timeout -> ERROR on expiry
    max_wait_s: float | None = (
        None  # bounded: documented propagation bound from last causal request
    )

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
class DbDeltaPolicy:
    """forbid.db_delta — a causal before/after diff (FEATURE-SPEC §5; DEVELOPMENT §16)."""

    query: str
    settle: SettlementConfig
    added_where: str | None = None
    changed_where_before: str | None = None
    changed_where_after: str | None = None
    removed_where: str | None = None
    max_added: int = 0
    max_changed: int = 0
    max_removed: int = 0
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


ExpectEntry = DbExpect | ApiExpect
ForbidEntry = DbDeltaPolicy | HttpPolicy | ExternalPolicy


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
    expect: tuple[ExpectEntry, ...] = field(default_factory=tuple)  # db (P0) | api (P1)
    forbid: tuple[ForbidEntry, ...] = field(default_factory=tuple)  # db_delta | http | external
    budget: ExecutionBudget | None = None
    preconditions: tuple[Precondition, ...] = field(default_factory=tuple)
