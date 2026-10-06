# AssertState — DEVELOPMENT.md (P0 Core Engine implementation blueprint) — v1.1

> **This document describes implementation mechanics, not product discovery or architectural redesign.**

> **v1.1 changelog (third review, 2026-10-02):** (1) backed INV-7 with a **real child sandbox** — a bare subprocess + filtered env only keeps Oracle objects/secrets out (INV-3/5/6); artifact-path and local-socket unreachability (adversarial tests 4–5) now require container/OS-level isolation primitives, stated explicitly (§4, §10). (2) **Fixed the Postgres read-only probe** — `CREATE TEMP TABLE` is allowed in a READ ONLY transaction and proves nothing; the probe now attempts an `INSERT` into a protected sentinel table the oracle role has no grant on, and requires rejection (§13, §19). (3) Typed `ComparatorValue` instead of `str | None` for `DbExpect.value` (§7). (4) Added the **explicit-`key:` rule** (present/non-null/deterministic/stable across baseline↔after) (§14, §17). (5) Reworded the determinism principle — verdict *evaluation* is pure over captured observations; oracle *acquisition*/settlement may do controlled I/O (§2, §23).

Implementation guide for the **AssertState P0 Core Engine**, derived from — and subordinate to — two frozen source documents. A software engineer (or coding agent) should be able to build P0 from this without reopening architectural decisions.

## Source-of-truth order
1. **[FEATURE-SPEC.md](FEATURE-SPEC.md) v2.3** — authoritative for product behavior, contract semantics, acceptance criteria, correctness requirements.
2. **[SYSTEM-DESIGN.md](SYSTEM-DESIGN.md) v2.2** — authoritative for architecture, component boundaries, trust model, lifecycle, security, phase boundaries. *(The source prompt cited v2.1; v2.2 is the current freeze-ready version and a strict superset — it adds the shared-staging gating rule and the boundary proof test. Built against v2.2.)*
3. **This file** — implementation instructions derived from (1) and (2). It does **not** redesign the product, reopen frozen decisions, or invent hosted-platform/UI/tenancy/REST-control-plane features (all post-launch / demand-driven, FEATURE-SPEC §17).

Anything not fixed by (1)/(2) is labelled **`OPEN IMPLEMENTATION DECISION`** with the smallest reasonable choice — never silently promoted to a product requirement. Any contradiction between (1) and (2) is labelled **`SPEC MISMATCH`** and reported in §41, never silently fixed here.

**Preserved terminology (exact):** Contract · Scenario · OracleTarget · BrowserTarget · ExecutionBudget · AgentTrace · BrowserObservations · RunMeasurements · Snapshot · Delta · TrialResult · RunVerdict · RunMetadata · RunManifest · EvidenceBundle · Execution Adapter · Environment Manager · Verifier · Policy Engine · Statistics Engine · Artifact Store.

**Terminology reconciliation (SYSTEM-DESIGN supersedes FEATURE-SPEC's pre-split names — not a mismatch, a resolved fix):**
- FEATURE-SPEC `AppTarget` → split into **OracleTarget** (trusted) + **BrowserTarget** (agent-visible).
- FEATURE-SPEC `Trace` → split into **AgentTrace** (untrusted), **BrowserObservations** (trusted, P1), **RunMeasurements** (trusted, P1).

---

## 1. Purpose and implementation scope
- **What this is:** the P0 build blueprint. It inherits all behavior from FEATURE-SPEC v2.3 and all structure from SYSTEM-DESIGN v2.2.
- **Frozen (do not reopen):** the trust model (real OS process boundary), the external-oracle verdict, deterministic scoring, the `db_delta` settlement contract, Wilson + completeness, fail-closed evidence, the phase boundaries.
- **Originally P0-deferred; SINCE SHIPPED at P1** (code authoritative — FEATURE-SPEC §16): BrowserObservations/network capture, CDP/proxy instrumentation, `bounded` settlement, HTTP policies, external-activity policies, API oracle, GitHub Action, HTML reporting.
- **Still deferred:** Stagehand/Playwright-MCP/JEV adapters, regression/model comparison, hosted infra, UI, users/orgs/roles. (`run_correlated` settlement + `destructive_action` gating now SHIPPED, P2.)
- **Definition of "P0":** "P0" here = the **first validation slice** (SYSTEM-DESIGN §19 / FEATURE-SPEC §16), the next implementation milestone. *(FEATURE-SPEC's `[P0 done]` phase tag refers only to the already-built contract loader + `validate`; everything else in this file's P0 is net-new.)*
- **"Done" for P0:** see §37 — mechanically: every acceptance-matrix row (§35) and every adversarial test (§36) passes, with deterministic verdicts and redacted reproducible evidence.

### P0 scope (inclusive)
Python core · Browser Use adapter (out-of-process) · Chromium · PostgreSQL · disposable isolated env via template/snapshot restore · declarative fixtures/seeding · read-only Postgres oracle · baseline + after Snapshot · PK/key validation · snapshot completeness guards · `db_delta` (`added_where`/`changed_where`/`removed_where`) · **`drain` settlement only** · deterministic Verifier · Wilson lower bound + completeness · PASS/FAIL/ERROR/SKIPPED (+ INCONCLUSIVE at Run level) · fail-closed JSON EvidenceBundle · provenance (RunMetadata) · local Artifact Store · CLI exit code.

### Scope beyond the original P0 slice
Shipped at P1 (code authoritative): BrowserObservations/network capture · CDP/proxy · `bounded` settlement · HTTP policy · external policies · API oracle · GitHub Action · HTML.
Still deferred (§40): other adapters · hosted infra · UI · users/orgs/roles.

---

## 2. Development principles (and their implementation consequence)
| Principle | Implementation consequence |
|---|---|
| False PASS is the cardinal failure | Every ambiguous/incomplete condition resolves to ERROR or INCONCLUSIVE, never PASS. |
| Authoritative application state is the oracle | The verdict reads only OracleTarget (Postgres, read-only) — never the agent's report. |
| Agent self-report never trusted | `AgentTrace.agent_claimed_done` is recorded as evidence and **excluded from the verdict function's inputs**. |
| Deterministic verdict evaluation | Verdict *evaluation* is deterministic over captured oracle observations (baseline, after Snapshots) + contract inputs — no randomness, no clock-dependence in the decision. Oracle *acquisition* and settlement may perform controlled I/O (reads, `eventually` polling, drain) **before** evaluation; that I/O produces the observations the pure evaluation consumes (§22, §23). |
| No LLM in the verdict path | The `verifier/` package imports no model client. Enforced by a dependency test (§34). |
| Trusted/untrusted boundary mechanically enforced | Adapter/agent/browser run in a separate OS process/container; only serialized values cross IPC (§4, §10). |
| Oracle is observational only | DB uses a read-only role; a write attempt must raise (verified at run setup / per-trial, §13). |
| Incomplete evidence fails closed | Truncated/non-unique/timeout Snapshot → ERROR (§14); redaction failure → emit nothing (§28). |
| Isolation is a correctness requirement | Fresh env per trial or the Wilson math is invalid (FEATURE-SPEC §9.3). Non-negotiable in P0. |
| Settlement is part of correctness | After-snapshot only after a proven `drain` (§18); unprovable drain → ERROR. |
| FAIL = contract violation | A completed workflow that violated `expect`/`forbid`. |
| ERROR = correctness could not be established | Infra/oracle/verifier/settlement failure. |
| SKIPPED = precondition could not be established | Seed/fixture could not be applied. |

---

## 3. Repository structure
Frozen stack: **Core Python · First adapter Browser Use · DB PostgreSQL · Browser Chromium** (SYSTEM-DESIGN §14). Layout below elaborates SYSTEM-DESIGN §14's flat `oracle/`/`verifier/` into sub-packages — see `OPEN IMPLEMENTATION DECISION: repo sub-structure` (§41).

```text
assertstate/
  cli.py                  # P0 · trusted · argument parsing, exit codes (§8)
  domain/                 # P0 · trusted · typed models (dataclasses/enums) shared everywhere (§7)
  contract/               # P0(done) · trusted · YAML→Contract loader + schema + semantic validate
  config/                 # P0 · trusted · assertstate.yaml → OracleTarget/BrowserTarget/statistics/redaction
  orchestrator/           # P0 · trusted · trial loop + lifecycle + outcome classification (§9)
  adapters/
    base.py               # P0 · trusted side defines the Protocol; untrusted side implements
    runner.py             # P0 · trusted · launches + supervises the untrusted subprocess (§10)
    browser_use/
      child.py            # P0 · UNTRUSTED · runs inside the child process (§11)
  oracle/
    db_probe/             # P0 · trusted · read-only Postgres access (§13)
    snapshot/             # P0 · trusted · Snapshot + guards (§14, §15)
    delta/                # P0 · trusted · db_delta engine (§16, §17)
    settlement/           # P0 · trusted · SettlementController (drain only) (§18)
    api_probe/            # P1 · trusted · (stub only in P0)
  instrumentation/        # P1 · trusted · BrowserObservations/RunMeasurements (NOT in P0)
  verifier/
    expect/               # P0 · trusted · expect.db evaluator (§22)
    policy_engine/         # P0 · trusted · DbDeltaPolicy; plug-in slots for P1+ (§23)
  stats/                  # P0 · trusted · Wilson + completeness (§26)
  env/                    # P0 · trusted · Environment Manager: template restore + seeding (§20, §21)
  evidence/               # P0 · trusted · EvidenceBundle + fail-closed redaction + provenance (§27–§30)
  reporters/              # P0 · trusted · exit code + JSON; JUnit/HTML P1 (§31)
  demo-app/               # P0 · the disposable payment app + controllable retry worker (§19)
  contracts/              # P0 · example Contracts (from scenarios.md)
tests/
  unit/ integration/ e2e/ adversarial/    # §33–§36
```

**Per-directory import rule (dependency-inversion guard):** `domain/` imports nothing internal. Everything may import `domain/`. `cli → orchestrator → {config, env, oracle, adapters/runner, verifier, stats, evidence, reporters}`. `verifier/` imports `domain/` + `oracle/` only — **never** `adapters/`, `stats/`, or any model client. `adapters/browser_use/child.py` imports **only** `domain/` serialization + Browser Use; it must not import `oracle/`, `config/`, or `orchestrator/` (enforced by test, §36). `evidence/` and `reporters/` never import `verifier/` logic that could change a verdict.

---

## 4. Dependency and trust-boundary rules
```text
TRUSTED PROCESS                         UNTRUSTED PROCESS / CONTAINER
  orchestrator                            adapters/browser_use/child.py
  config / domain                         Browser Use
  oracle (db_probe/snapshot/delta/settle) Chromium
  verifier / stats                      ───────────────────────────────
  evidence / artifact store               (reached ONLY via narrow IPC)
  env (Environment Manager)
  adapters/runner (parent side)
```
Rules, as **testable security invariants** (tests in §36):
- **INV-1** `adapters/browser_use/child.py` is never imported into the trusted process (only `runner.py` is, which spawns it).
- **INV-2** The child runs inside a **sandbox** (see below), not merely a plain subprocess.
- **INV-3** `OracleTarget` (and its DSN/creds) never crosses IPC and never enters the child's environment. *(Backed by subprocess + filtered env alone.)*
- **INV-4** No Python object crosses IPC — only serialized JSON values. *(Backed by JSON-only transport.)*
- **INV-5** Only `{task, browser_target, execution_budget, run_id}` enters the child.
- **INV-6** Only an `AgentTrace` (`{steps, agent_claimed_done}`) returns.
- **INV-7** Trusted-side files, the `.assertstate/` artifact dir, trusted sockets/IPC endpoints, and (P1) the CDP port are **unreachable** from the child. *(NOT backed by a plain subprocess — requires the sandbox in §10. This is what adversarial tests 4–5 depend on.)*
- **INV-8** The verdict function's signature contains no agent-reported field (`agent_claimed_done`, trace step counts, adapter-reported cost) as a gating input.

**Honest scope of a plain subprocess vs. the sandbox:** a separate subprocess with a filtered environment and a scratch `cwd` keeps trusted **Python objects and secrets** out of the child (INV-3/4/5/6) — but it does **not** by itself make arbitrary host paths, `/proc`, same-user resources, the artifact directory, or reachable local sockets inaccessible. **INV-2/INV-7, and adversarial tests 4–5, require a real sandbox** (§10): a container, or, if a raw process is used, the enumerated OS isolation primitives. Do not claim INV-7 from "it's a subprocess."

---

## 5. Project bootstrap and development environment
- **Python:** 3.11+ (`match`, typing). *(OPEN IMPLEMENTATION DECISION: pin 3.11; raise only if a dep requires it.)*
- **Packaging/deps:** `uv` + `pyproject.toml` (fast, solo-friendly). Fallback: `pip` + `venv`. *(OPEN IMPLEMENTATION DECISION.)*
- **Format/lint/types:** `ruff` (format+lint) + `mypy --strict` on `assertstate/`.
- **Tests:** `pytest` + `pytest-postgresql` (or a disposable Docker Postgres) for integration/e2e.
- **PostgreSQL:** local 15+ with permission to `CREATE DATABASE ... TEMPLATE` (needed for §20). Two roles: an owner/migrator role and a **read-only** oracle role (§13).
- **Browser:** Chromium via Browser Use's managed install; pin the Browser Use version (§11).
- **Env vars:** `ASSERTSTATE_*` prefix; secrets (`ORACLE_DSN`, browser creds) from env only, never files-in-repo. The child process receives a **filtered** env (§10) — `ORACLE_*` stripped.
- **`.gitignore`:** `.assertstate/`, `.venv/`, `*.evidence.zip`, raw traces, `__pycache__`, `.env`.
- **Local artifact dir:** `.assertstate/runs/` (§30), git-ignored.
- **Test config:** a `tests/conftest.py` providing a disposable Postgres fixture + the demo-app schema.

---

## 6. Configuration model (`assertstate.yaml`)
Implements FEATURE-SPEC §14 + SYSTEM-DESIGN §3.3. Distinguishes **trusted oracle config** from **agent-visible browser config**.
```yaml
apps:
  staging:
    browser:                       # → BrowserTarget (AGENT-VISIBLE)
      base_url: "https://staging.example.com"
      creds_ref: "env:STAGING_BROWSER_LOGIN"   # reference, resolved trusted-side, redacted in evidence
    oracle:                        # → OracleTarget (TRUSTED, never to agent)
      db_dsn: "env:ORACLE_DSN"                  # must resolve to a READ-ONLY role
      # api_base / api_creds_ref — P1, SHIPPED (read-only GET/HEAD API oracle; expect.api live)
    environment:
      strategy: template_restore               # P0 (§20)
      template_db: "assertstate_demo_template"
      reset_hook: null                          # BYO reset (optional)
statistics:                        # defaults, overridable per-Contract (§8/§26)
  confidence: 0.95
  side: one_sided
redaction:
  mode: allowlist                  # FAIL-CLOSED default (§28)
  allow_fields: []
canonicalizer: canon-v1
```
- **Required:** `apps.<name>.browser.base_url`, `apps.<name>.oracle.db_dsn`. `environment.strategy` is optional (defaults to `shared`).
- **Validation at load:** resolve secret refs; assert `redaction.mode == allowlist` unless explicitly overridden; assert `environment.strategy` is a known strategy. **Read-only oracle verification happens at run setup (per-trial), not at config load** — config loading is deliberately DB-free; a writable oracle role fails closed to a trial ERROR via the role-privilege probe (§13).
- **Persisted:** the resolved config *structure* (minus secrets) into RunMetadata. **Never persisted:** DSNs, credentials, secret values.
- **Config error → CLI failure:** any load/validation error → exit non-zero with a precise message; never a partial run.

---

## 7. Contract runtime model (`domain/`)
Transformation: `YAML → parse → typed Contract → schema validation → semantic validation → executable contract`. Contract semantics are **frozen by FEATURE-SPEC §2** — do not change them.

```python
# domain/contract.py  (sketch — field names authoritative)
from dataclasses import dataclass
from enum import Enum

class Comparator(Enum):
    EQUALS="equals"; EQ_CANONICAL="eq_canonical"; IN="in"
    LT="lt"; LTE="lte"; GT="gt"; GTE="gte"; REGEX="regex"; ABSENT="absent"; ANY="any"

# A comparator's operand is typed by the comparator (NOT a single str|None):
#   equals/eq_canonical/regex → str      (money/amounts kept as STRING, §2.3, parsed to Decimal at compare)
#   in                        → tuple[str, ...]
#   lt/lte/gt/gte             → Decimal  (numeric; fail-closed on non-finite, §22)
#   absent/any                → None     (no operand)
ComparatorValue = str | Decimal | tuple[str, ...] | None

@dataclass(frozen=True)
class DbExpect:            # expect.db — final-state read (§22)
    query: str
    comparator: Comparator
    value: ComparatorValue            # shape determined by `comparator` above; validated at load (§7 rules)
    eventually: "Eventually | None"    # polling; P0 supports it for db

@dataclass(frozen=True)
class SettlementConfig:    # §18 / FEATURE-SPEC §5
    mode: str                          # "drain" (P0) + "bounded" (P1) + "run_correlated" (P2) — all SHIPPED. run_correlated needs run_id_col + queue + timeout (app-cooperation); a non-runnable mode fails closed to ERROR.
    queue: str | None                  # drain: workflow-owned queue name
    timeout_s: float | None            # drain timeout → ERROR on expiry

@dataclass(frozen=True)
class DbDeltaPolicy:       # forbid.db_delta — causal diff (§16)
    query: str
    added_where: str | None
    changed_where_before: str | None
    changed_where_after: str | None
    removed_where: str | None
    max_added: int = 0
    max_changed: int = 0
    max_removed: int = 0
    settle: SettlementConfig = ...
    key: str | None = None             # natural/idempotency key when PK is not the diff key

@dataclass(frozen=True)
class ExecutionBudget:     # §25
    max_steps: int | None
    max_cost_usd: str | None           # string → Decimal
    max_seconds: float | None

@dataclass(frozen=True)
class StatisticsConfig:    # §26
    trials: int
    pass_threshold: float
    confidence: float = 0.95
    side: str = "one_sided"
    min_valid_trials: int = 0
    max_error_rate: float = 1.0
    max_skip_rate: float = 1.0

@dataclass(frozen=True)
class Contract:
    task: str
    app: str
    expect: tuple[DbExpect, ...]
    forbid: tuple[DbDeltaPolicy, ...]  # P0: db_delta only; http/external are P1
    budget: ExecutionBudget | None
    statistics: StatisticsConfig
    preconditions: tuple["Precondition", ...]
```

**Validation rules (from FEATURE-SPEC §2, §8):** comparator shape matches entry type; **the operand type matches the comparator** (`in`→list; `lt/lte/gt/gte`→numeric→Decimal; `equals/eq_canonical/regex`→string; `absent/any`→no operand) — a mismatch is a load error, so YAML representation can't diverge between implementers; **every `db_delta` has a valid `settle`** (P0: must be `drain`); amount values are strings (reject YAML floats for `eq_canonical` money); statistics param ranges (§26 guards); `expect` causality warning when an absolute expect is used without a baseline/isolation/delta (FEATURE-SPEC §5 "expect vs db_delta"). Examples for `expect.db`, `db_delta`, `settle: drain`, budget, statistics are in `contracts/` (mirroring FEATURE-SPEC §2 and §5.1/§5.2).

**`changed_where` parsing:** FEATURE-SPEC §5 — `changed_where: "<expr>"` means `{after: "<expr>"}`; `changed_where: {before, after}` maps to the two fields above.

---

## 8. CLI implementation (`cli.py`)
P0 commands (FEATURE-SPEC §14). No `init`, no hosted/API commands.

| Command | Args | stdout | stderr | Exit code |
|---|---|---|---|---|
| `assertstate validate <contract>` | contract path | validation summary (ok/errors) | parse/validation errors | 0 ok · 2 invalid |
| `assertstate run <contract> [--adapter A] [--app <name>] [--config FILE] [--scenario S] [--sandbox auto\|container\|off] [--run-id ID] [--trials N] [--json]` | contract path + options | RunVerdict (human; JSON with `--json`) | run/infra errors | **0 = Run PASS · 1 = Run FAIL · 2 = usage/invalid · 3 = INCONCLUSIVE · 4 = ERROR-dominated** |
| `assertstate report <run-id \| path> [--format json\|junit\|html\|summary]` | run id or `.assertstate/runs/<id>` | stored RunVerdict (json/junit/html, or a redacted GitHub step-summary) | not-found | 0 ok · 2 not found |

- `--adapter` is a run-time choice (FEATURE-SPEC §2.4), **not** in the Contract. Default `browser-use`; also `http`, `noop`, `demo`.
- Input validation: contract must `validate` clean before `run`; otherwise exit 2 without running.
- Artifact location printed on completion: `.assertstate/runs/<run-id>/`.
- `--json` emits the machine-readable RunVerdict to stdout; logs go to stderr (§32).

*(OPEN IMPLEMENTATION DECISION: exit-code map. FEATURE-SPEC §10 fixes only "0 all-pass / non-zero on fail/inconclusive." The 1/3/4 split is the smallest useful refinement; collapse to a single non-zero if simpler.)*

---

## 9. Run orchestration (`orchestrator/`)
`RunOrchestrator.run(contract, app) -> RunVerdict`. Lifecycle (SYSTEM-DESIGN §5), per stage: inputs → outputs → failure handling → outcome.

```text
load → validate → resolve OracleTarget+BrowserTarget → capture RunMetadata
for trial 1..N:
  isolate   → fresh env (template restore)        fail → ERROR (whole trial)
  seed      → apply fixtures                        fail → SKIPPED
  baseline  → Snapshot(before) + guards             truncated/non-unique/timeout → ERROR
  act       → runner.run(task, BrowserTarget, budget, run_id)   child crash/timeout → ERROR
              ← AgentTrace (agent_claimed_done recorded as EVIDENCE only)
  settle    → SettlementController.drain(...)        unprovable/timeout → ERROR
  after     → Snapshot(after) + guards              truncated/non-unique/timeout → ERROR
  verify    → expect AND policy_engine AND budget   oracle/verifier failure → ERROR
              → PASS | FAIL
  record    → TrialResult (+ evidence refs)
  cleanup   → drop env (failed cleanup logged, does not change verdict)
aggregate → Statistics Engine → RunVerdict (PASS|FAIL|INCONCLUSIVE)
emit      → EvidenceBundle (redacted) + reporters + artifact store
```
- **Attribution in P0 is always `causal`** (env is always isolated single-writer). The shared-staging `observed`/non-gating path (SYSTEM-DESIGN §6.5) never triggers in P0 but the gating check is still asserted (`attribution == causal`) so a future non-isolated run can't silently gate a `db_delta`.
- `AgentTrace.agent_claimed_done` enters only the EvidenceBundle, never `verify`.
- Cleanup failure never upgrades a verdict; it's logged and surfaced in evidence.

---

## 10. Out-of-process adapter runner (`adapters/runner.py`) — critical
Launches Browser Use in a child subprocess; this is where INV-1..INV-7 are enforced.
- **Run-path engagement (DoD §37):** the CLI's real (`--config`) run path engages the container sandbox **by default** (`--sandbox auto`): container when Docker is reachable, else a bare subprocess with a **loud, evidence-recorded** warning (`env_image=subprocess-fallback`) — the weaker posture is never silent. `--sandbox container` refuses to run if Docker is absent; `--sandbox off` forces the subprocess. The strict `--network none` profile is the adversarial INV-7 proof and the posture for network-free adapters; a real networked agent uses `--network bridge` (host-FS/privilege isolation and the stripped oracle credential still hold, so the trusted oracle stays unreachable). The bundled demo (`--app demo`) is a **host-coupled in-process fixture** proving the verdict logic, not the sandbox.
- **Sandbox (required for INV-2/INV-7, §4):** the child runs inside a **container** (recommended) — e.g. a minimal rootless container with: no bind-mount of the repo or `.assertstate/`, a private network (or egress limited to the app under test), a private PID/IPC namespace, a dedicated non-root UID, and no inherited file descriptors. **If a raw process is used instead of a container (P0 fallback),** the following OS primitives are *mandatory*, not optional: a **dedicated UID** with no read access to the trusted user's files or `.assertstate/`; **restrictive filesystem permissions** on all trusted paths; **no inherited file descriptors** (`close_fds=True`, pass only the one IPC fd); **private IPC/socket** reachable only via that fd (not a world-/user-readable path); and a **protected/hidden `/proc`** where feasible. *(OPEN IMPLEMENTATION DECISION §41: container vs. hardened-process for P0. The container is preferred because it makes tests 4–5 pass by construction; the hardened-process path must implement every primitive above or those tests cannot pass.)*
- **Process lifecycle:** parent spawns the sandboxed child with an explicit, filtered `env`, writes the request, reads one response, joins with timeout, then force-terminates (and tears the sandbox down).
- **Environment construction (secret filtering):** child env is built from an **allowlist** (e.g. `PATH`, Browser Use runtime vars, resolved `BROWSER_*` creds). **All `ORACLE_*`, DSNs, and AssertState trusted secrets are stripped.** Default-deny: unknown vars are not passed.
- **Filesystem isolation:** the child cannot reach trusted paths — enforced by the sandbox above (container: no mount; hardened-process: UID + permissions), **not** merely by setting `cwd` to a scratch dir. The `.assertstate/` artifact dir is never mounted/granted.
- **IPC mechanism:** length-prefixed JSON over a single parent-owned descriptor passed to the child (a pipe, or a socket whose only handle is that inherited fd). No world-/same-user-readable socket path. *(OPEN IMPLEMENTATION DECISION: stdin/stdout pipe for P0; an fd-passed unix socket for P1.)*
- **Serialization:** JSON only — no pickle (pickle would allow object/code crossing, violating INV-4).
- **Max message size:** request and response each capped (e.g. 8 MiB). Oversized response → discard → ERROR (§36 test).
- **Timeout:** hard wall-clock (`budget.max_seconds` + margin); on expiry kill the child → ERROR.
- **Crash handling:** non-zero child exit / no response / malformed JSON → ERROR (never FAIL, never PASS).
- **stdout/stderr:** child diagnostics captured to a redacted log; never parsed into the verdict.

**Request (into the child):**
```json
{ "task": "...", "browser_target": { "base_url": "...", "creds": "..." },
  "execution_budget": { "max_steps": 30, "max_cost_usd": "0.10", "max_seconds": 60 },
  "run_id": "..." }
```
```text
FORBIDDEN in the request: OracleTarget · DB DSN · oracle API creds · any trusted object/handle
```
**Response (the only permitted shape):**
```json
{ "steps": [ ... ], "agent_claimed_done": true }
```
Anything else (extra keys with trusted data, wrong types, missing keys) → reject → ERROR. Adversarial tests in §36 (items 1–8).

---

## 11. Browser Use adapter (`adapters/browser_use/child.py`) — UNTRUSTED
Runs inside the child process only.
- **Version pin:** pin Browser Use + Chromium in `pyproject.toml`; record the version in RunMetadata (§29).
- **Flow:** read request → construct Browser Use agent with `browser_target` → inject `task` → run under `execution_budget` (child-local step/time caps) → collect steps + the agent's done-claim → shut the browser down → emit `{steps, agent_claimed_done}`.
- **Credentials:** uses only `browser_target.creds` (agent-visible). It has no OracleTarget and no DB access (INV-3).
- **No verdict logic:** the adapter must not query the DB, must not evaluate `expect`/`forbid`, must not decide pass/fail. It only produces an AgentTrace.
- **Crash/timeout:** on its own failure, exit non-zero (parent maps to ERROR).

---

## 12. BrowserTarget (`domain/` + `config/`)
- Contains: `base_url`, agent-visible `creds` (resolved from `creds_ref`).
- **Never contains:** DB DSN, oracle API creds, or any internal oracle configuration.
- Credentials represented as **references** in config (`env:...`), resolved trusted-side, and **redacted** before entering any artifact (§28). Prefer passing a reference the child can use without the long-lived secret where the app allows it. *(OPEN IMPLEMENTATION DECISION: P0 passes the resolved login to the child since browser login needs it; it is redacted from evidence and stripped from logs.)*

---

## 13. PostgreSQL Oracle (`oracle/db_probe/`)
Implements OracleTarget's DB side (SYSTEM-DESIGN §3.7). Observational only.
- **Read-only connection** using the least-privilege role; `default_transaction_read_only = on` on the session.
- **Parameterized queries** only (no string interpolation of values).
- **Statement timeout** (`SET statement_timeout`) → on timeout classify ERROR.
- **Row/result limit** (cardinality cap) feeding Snapshot `row_count`/`truncated` (§14).
- **Connection lifecycle:** short-lived per Snapshot; pooled within a trial if useful.
- **Read-only verification (at run setup / per-trial) — role-privilege based, not transaction-mode based:** the proof is that the oracle **role lacks write privilege**, not that `default_transaction_read_only` is set (a session flag). **Do NOT use `CREATE TEMP TABLE` / temp-table writes** — PostgreSQL permits those inside a `READ ONLY` transaction, so they prove nothing. Instead attempt an `INSERT` into a **protected normal sentinel table** the oracle role has no grant on:
  ```sql
  BEGIN;
  SAVEPOINT ro_probe;
  INSERT INTO assertstate_readonly_probe(id) VALUES ('probe');  -- MUST raise: permission denied
  ROLLBACK TO SAVEPOINT ro_probe;
  ROLLBACK;
  ```
  The sentinel table (`assertstate_readonly_probe`) is created in the template by the migrator role with **no INSERT/UPDATE/DELETE grant to the oracle role** (§19). If the INSERT **succeeds** (or fails for any reason other than insufficient privilege) → config error (exit non-zero). Adversarial test §36 item 10.
- **Error classification:** connection failure, auth failure, timeout, permission denied → **ERROR** (never a silent pass).
- Verifier queries **must not mutate** — enforced by the read-only role + the load-time check.

---

## 14. Snapshot (`oracle/snapshot/`)
```python
@dataclass(frozen=True)
class Snapshot:
    query_id: str
    rows_by_key: dict[Hashable, dict]   # keyed by PK/`key:`
    row_count: int
    complete: bool
    truncated: bool
    pk_unique: bool
    taken_at: datetime
    consistency: str                    # "statement" (single query) | "repeatable_read" (multi) — §15
```
- **When taken:** baseline after isolate+seed; after post-settlement (§9).
- **Keying:** by the declared PK, or the Contract's `key:` for `db_delta` (FEATURE-SPEC §5.2).
- **Explicit `key:` rule (row identity must be well-defined):** when a `key:` is used instead of the PK, every result row's key value must be **present, non-null, deterministic, and stable between the baseline and after Snapshots**. A **null** key value → `pk_unique = False`-equivalent → **ERROR** (null identity is ambiguous and cannot be diffed). A key that changes meaning between baseline and after (non-deterministic/non-stable projection, see §17) → ERROR. This matters because the duplicate policy (FEATURE-SPEC §5.2) deliberately allows an explicit idempotency/natural key.
- **Duplicate-key detection:** if two result rows share a key → `pk_unique = False`.
- **Truncation detection:** if `row_count` reaches the cardinality cap → `truncated = True`.
- **Query timeout / malformed rows:** → ERROR (surfaced by the probe, §13).

**Hard rules (fail closed):**
```text
truncated == True  → ERROR → never PASS
pk_unique == False → ERROR → never PASS
```

---

## 15. Snapshot consistency (`oracle/snapshot/`)
Implements SYSTEM-DESIGN §6.7:
- **Single query:** read at the DB's own statement snapshot (`consistency="statement"`) — internally consistent by definition. **This is the P0 path** (each `db_delta`/`expect` query is independent).
- **Multiple related queries forming one Snapshot:** open **one read-only `REPEATABLE READ` transaction**, run all queries in it, commit/rollback at the end (`consistency="repeatable_read"`). Required before any cross-query invariant — **not needed in P0**, implemented as the mechanism for P1+.
- Independent queries must be **explicitly declared independent**; never silently claim cross-query atomicity.
- Transaction cleanup: always roll back the read-only txn (no writes to commit); release the connection.

---

## 16. `db_delta` engine (`oracle/delta/`)
```text
diff(before: Snapshot, after: Snapshot) -> Delta
  keys_before = before.rows_by_key.keys()
  keys_after  = after.rows_by_key.keys()
  added   = { k: after[k]            for k in keys_after  - keys_before }
  removed = { k: before[k]           for k in keys_before - keys_after }
  changed = { k: (before[k],after[k]) for k in keys_after & keys_before if before[k]!=after[k] }
```
- **Complexity:** O(n) over the keyed rows (dict set-ops); n bounded by the cardinality cap.
- **Predicate semantics (FEATURE-SPEC §5, exact):**
  - `added_where` → predicate on the **after-row** (present after, absent before).
  - `changed_where.before` → predicate on the **old row**; `changed_where.after` → the **new row** (both must hold for a changed match). Shorthand `changed_where: "<expr>"` = `{after: "<expr>"}`.
  - `removed_where` → predicate on the **before-row** (present before, absent after).
- **Max-count handling:** count matches per event set; a policy **fires** (→ FAIL) when matches `> max_added` / `> max_changed` / `> max_removed`. Default each is 0 when the corresponding `*_where` is present (FEATURE-SPEC §5).
- **Predicate evaluation:** a small, safe expression evaluator over row columns (equality/inequality/`!=` on string/number). *(OPEN IMPLEMENTATION DECISION: implement a restricted comparator AST — no arbitrary `eval`. §41.)*
- **Failure behavior:** malformed predicate at load → validation error; row/predicate type mismatch at runtime → ERROR (not FAIL).

---

## 17. `db_delta` query visibility (`oracle/delta/` + `contract/`)
Carries SYSTEM-DESIGN §6.6:
> A `db_delta` query establishes changes **only over the columns it projects**.
- `validate` emits a **warning** when a `*_where` references a column not in the projection, and a stronger warning that `db_delta(payments)` ≠ "all changes to payments."
- **Volatile/nondeterministic projections rejected** at load: `now()`, `random()`, `clock_timestamp()`, unstable ordering without a key. Only stable deterministic columns may appear.
- **Key requirement:** the projection must include the PK/`key:` used for diffing; missing → validation error. An explicit `key:` must resolve to a **present, non-null, deterministic, stable** column (enforced at load where statically knowable, and at Snapshot time per §14 — null/unstable key → ERROR).
- **Deterministic ordering/keying:** diffing is by key, not row order, so ordering is irrelevant — but the key must be present and unique (§14).
- **`SELECT *`:** permitted; it widens visibility (good for catching unexpected column mutations) at the cost of larger snapshots. Document the trade-off; do not require it.

---

## 18. P0 drain settlement (`oracle/settlement/`) — critical
The original P0 slice implemented **`drain` as the only correctness-valid settlement mode**. `bounded` **has since shipped at P1**: its causal start-point comes from the trusted parent-owned network capture (§3.8), which now exists; without that anchor `bounded` fails closed to ERROR (SYSTEM-DESIGN §6.3).

```python
class SettlementController:
    def drain(self, cfg: SettlementConfig) -> DrainResult: ...
```
**`drain` succeeds only when all hold (SYSTEM-DESIGN §6.3):**
```text
(a) no queued workflow-owned jobs
(b) no in-flight / active workflow-owned jobs
(c) no producer can still enqueue work for this run
(d) downstream writes covered by the drain contract are observable
```
- **Queue/worker interface:** a small `QueueProbe` the demo app implements (§19) — reports `queued`, `active`, and a `producers_closed` signal. *(OPEN IMPLEMENTATION DECISION: the P0 demo worker exposes an introspection table/endpoint the trusted side reads read-only; real apps supply an adapter in P1.)*
- **Polling:** poll (a)–(d) until all satisfied or `timeout_s` expires.
- **Observability (d):** confirm the worker's last committed write for this run is visible to the oracle role (e.g. a monotonic processed-marker), so the after-Snapshot can't precede a committed write.

**Failure classification (all ERROR, never FAIL — SYSTEM-DESIGN §6.3):**
```text
drain unverifiable (missing signal)     → ERROR
drain timeout                           → ERROR
drain partial evidence (some of a–d)    → ERROR
```
`bounded` is implemented at P1 (shipped); the drain-only rule above was the original P0 slice.

---

## 19. Demo application + controllable retry worker (`demo-app/`)
A deliberately tiny disposable Postgres payment app proving the thesis. Supports the controlled scenarios of the acceptance matrix (§35).
- **Schema (minimal):**
  ```sql
  tenants(id text primary key);
  payments(id bigserial primary key, invoice text, tenant_id text references tenants(id),
           amount numeric(12,2), status text, idempotency_key text, created_at timestamptz);
  payment_jobs(id bigserial primary key, invoice text, run_id text, state text,  -- queued|active|done
               process_after timestamptz, attempts int);
  run_markers(run_id text primary key, last_processed_job bigint);  -- drain observability (d)
  assertstate_readonly_probe(id text primary key);  -- sentinel for the read-only probe (§13)
  ```
  Grants (built once in the template by the migrator role): the **oracle role** gets `SELECT` on the app tables only, and **no `INSERT`/`UPDATE`/`DELETE` on `assertstate_readonly_probe`** (nor on anything else), so the §13 probe's INSERT is rejected with "permission denied."
- **Seed fixtures:** tenants (`acme`, `globex`); **baseline pinned to 0 payment rows for the target idempotency key** (FEATURE-SPEC §5.2 required fixture) so `max_added: 1` cannot pass against a pre-populated env.
- **Worker:** processes `payment_jobs`; **controllable delay** via `process_after`; **controllable duplicate** (re-enqueue) and **slow-retry** (duplicate committed after an early snapshot would be taken) to exercise `drain`.
- **Controllable fault injection** per scenario: correct · missing write · wrong value · duplicate write · slow-retry duplicate · cross-tenant INSERT · cross-tenant UPDATE.
- **Drain signal:** `payment_jobs` state + `run_markers` implement `QueueProbe` (§18).
- **Idempotency key + payment lifecycle:** `idempotency_key = invoice` (demo); lifecycle `queued → active → done`.
Keep it intentionally tiny — it is a test fixture, not a product.

---

## 20. Environment isolation (`env/`)
P0 strategy: **template/snapshot restore** (SYSTEM-DESIGN §9).
- **Creation:** `CREATE DATABASE assertstate_run_<run-id>_<trial> TEMPLATE assertstate_demo_template;`
- **Naming:** unique per trial (`<run-id>_<trial>`), so trials are independent (FEATURE-SPEC §9.3).
- **Init/migration:** the template DB is migrated + base-seeded once; per-trial DBs inherit it.
- **Seed:** per-trial scenario fixtures applied after restore (§21).
- **Cleanup:** `DROP DATABASE` per trial after evidence is recorded; **failed cleanup is logged, never changes the verdict**, and is surfaced in evidence.
- **Per-trial uniqueness:** enforced; a name collision → ERROR.
- **Transactional rollback is NOT the P0 default** — valid only when the application explicitly propagates the test transaction into its own connections (SYSTEM-DESIGN §9); the demo app does not, so template restore is used.

---

## 21. Fixtures / seeding (`env/`)
Per trial: `fresh env → seed → verify seed → baseline`.
- **Fixture format:** declarative (SQL files or a small YAML→SQL map per scenario). *(OPEN IMPLEMENTATION DECISION: SQL files keyed by scenario id for P0.)*
- **Seed verification:** after seeding, assert the declared preconditions hold (e.g. "0 payment rows for `invoice=bill-december`"). If a precondition cannot be established → **SKIPPED** (FEATURE-SPEC §8.1/§3).
- **Duplicate-scenario baseline:** explicitly pin 0 pre-existing rows for the idempotency key so `max_added: 1` is meaningful (FEATURE-SPEC §5.2).

---

## 22. Expect evaluator (`verifier/expect/`)
Implements P0 `expect.db` (FEATURE-SPEC §4.1, §2.3).
- **Query execution:** read-only probe (§13); the final-state SELECT after settlement.
- **Comparator application:** `equals` (strict, type-sensitive) · `eq_canonical` (via `canon-v1`; amounts/IBANs/emails domain-aware; money compared as strings/Decimal, never float) · `in` (canonical membership) · `lt/lte/gt/gte` (numeric; **fail-closed on non-finite** → ERROR/FAIL per comparator rule) · `regex` (fullmatch) · `absent` · `any`.
- **Multi-row:** first-row/aggregate per comparator (FEATURE-SPEC §4.1); NULL handled explicitly (NULL ≠ value unless comparator is `absent`).
- **AND semantics:** all `expect` entries must hold.
- **Query error:** → ERROR (not FAIL).
- **`eventually` polling:** supported for `db` in P0 (FEATURE-SPEC §4.5) — poll within `timeout_ms`/`poll_ms` before deciding.
- **Causality caveat:** an absolute `expect` does not prove causation; rely on isolation/baseline/`db_delta` when causality matters (FEATURE-SPEC §5). The `validate` warning (§7) enforces awareness.

---

## 23. Policy Engine — P0 subset (`verifier/policy_engine/`)
P0 implements **`db_delta` only**. Interface is deterministic and side-effect-free:
```python
class Policy(Protocol):
    def evaluate(self, before: Snapshot, after: Snapshot, attribution: str) -> PolicyResult: ...
# Registry:
#   DbDeltaPolicy   [P0]
#   HttpPolicy      [P1]  (needs BrowserObservations)
#   ExternalPolicy  [P1]
#   Authorization   [later]
#   Destructive     [later]
```
- **Gating rule (SYSTEM-DESIGN §6.5):** a `DbDeltaPolicy` gates **only under `attribution == "causal"`.** In P0 attribution is always causal, so it always gates; the check is asserted so a non-isolated future run cannot silently gate (observed → INCONCLUSIVE, never FAIL).
- No policy may perform I/O beyond reading the already-captured Snapshots; no model calls.

---

## 24. TrialResult and error taxonomy (`domain/`)
```text
PASS     = all expect hold AND no GATING forbid policy fires AND budget (gating subset) holds
FAIL     = the workflow COMPLETED and violated the contract (expect failed or a gating policy fired)
ERROR    = correctness could not be established (infra/oracle/verifier/settlement/snapshot)
SKIPPED  = a precondition could not be established (seed/fixture)
```
**Explicitly prevented (all → ERROR, never FAIL):**
```text
settlement uncertainty  → ERROR
oracle unavailable      → ERROR
incomplete snapshot     → ERROR
non-unique key          → ERROR
```
`agent_claimed_done` is never an input to this classification.

---

## 25. Budget enforcement (`verifier/` + `orchestrator/`)
FEATURE-SPEC §12. **Trust distinction is the crux:**
- **`max_seconds` — GATING in P0.** Measured by the harness (parent wall-clock around the child, §10). Exceed → the trial is a budget violation → FAIL (completed-but-over-budget) or the child is killed → ERROR if no verdict is possible. *(OPEN IMPLEMENTATION DECISION: timeout-kill → ERROR; natural over-run detected post-hoc → FAIL. §41.)*
- **`max_steps` and `max_cost_usd` — NON-GATING in P0.** `SPEC MISMATCH/LIMITATION (§41):` RunMeasurements is P1 (SYSTEM-DESIGN §3.8), so in P0 step-count and cost are only available from the **untrusted `AgentTrace`**. Gating on them would let an agent-reported metric into the verdict (violating INV-8). Therefore P0 **records** steps/cost from the trace as *evidence only* and does **not** gate on them. Gating moves to P1 when trusted RunMeasurements exist.
- Never use adapter self-reported cost for gating. If a cost dimension can't be trusted in P0, it is documented as a limitation (§39), not faked.

---

## 26. Statistics engine (`stats/`)
Implements FEATURE-SPEC §8.
```text
valid_trials = PASS + FAIL
pass_rate    = PASS / valid_trials              (undefined when valid_trials == 0)
wilson_lower = Wilson(PASS, valid_trials, confidence, side)
completeness: valid_trials >= min_valid_trials
              error_rate = ERROR/total   <= max_error_rate
              skip_rate  = SKIPPED/total <= max_skip_rate
Run PASS  iff completeness holds AND wilson_lower >= pass_threshold
Run FAIL  iff completeness holds AND wilson_lower <  pass_threshold
Run INCONCLUSIVE iff completeness fails OR valid_trials == 0
```
- **Guards (§7.4 SYSTEM-DESIGN):** `valid_trials == 0 → INCONCLUSIVE` (never `PASS/0`); validate `0 < confidence < 1`, `0 ≤ pass_threshold ≤ 1`, `0 ≤ max_error_rate ≤ 1`, `0 ≤ max_skip_rate ≤ 1`, `min_valid_trials ≤ trials` at load.
- Defaults `confidence=0.95`, `side=one_sided`.
- **Wilson numbers must match FEATURE-SPEC §8.3** (verified: 20/20 one-sided=0.881; 25/25=0.902; 30/30=0.917; 35/35 two-sided=0.901) — unit tests assert these exact values (§34).
- **Document (and the evidence states):** Wilson quantifies uncertainty under the trial model; it does **not** remove correlation.
- **No regression/version comparison in P0** (FEATURE-SPEC §8.5 is P2).

---

## 27. Evidence model (`evidence/`)
Per trial, recorded (SYSTEM-DESIGN §11):
```text
contract ref + hash · AgentTrace (incl. agent_claimed_done) · baseline Snapshot · after Snapshot ·
Delta · TrialResult · settlement info · attribution · provenance (RunMetadata)
```
- **Network evidence is absent in P0** and is represented **explicitly as out-of-scope** (`"browser_observations": {"status": "out_of_scope_p0"}`) — never a fake empty network trace.
- Settlement info records the drain signals (and, reconciling the two source docs, uses SYSTEM-DESIGN TrialResult field names `causal_start_at/started_at/completed_at/bound_or_drain_signal`; FEATURE-SPEC §5's `settle_started_at/settle_completed_at/settle_policy` are the same facts under their evidence names — see §41 note).

---

## 28. Fail-closed redaction (`evidence/`)
Pipeline: `raw internal result → allowlist filter → redaction → size limits → validation → write artifact`.
- **Allowlist (default-deny):** nothing leaves unless whitelisted. Never-by-default: credentials, cookies, auth headers, raw secrets, sensitive query values, PII in SQL `WHERE`, un-approved DB columns, oversized bodies.
- **Size limits:** cap row/body sizes; over-cap → truncate-and-mark (and the *data* truncation must not be confused with Snapshot truncation, which is ERROR).
- **Fail-closed:** if the redaction pipeline itself raises, **emit nothing** (no unredacted fallback). The run still produces a verdict + a redaction-failure notice; the raw bundle is not written.
- Tests in §34 (redaction) and §36 (item 9: redaction failure → nothing emitted).

---

## 29. Run provenance (`evidence/` → RunMetadata)
Capture (SYSTEM-DESIGN §4/§12): `run_id`, AssertState version, contract hash, scenario_id, adapter+version, model/provider, system-prompt hash, browser version, app git SHA, DB schema fingerprint, fixture version, env image, canonicalizer version, statistics config, settlement config, timestamp/tz.
- **P0-optional fields that must NOT be faked if unknown:** model/provider and system-prompt hash (depend on Browser Use's configured LLM — record if available, else `null`); app git SHA / env image for the demo app (record demo-app commit; `null` if N/A). An unknown value is `null`, never a placeholder that implies provenance it doesn't have.

---

## 30. Local Artifact Store (`evidence/` + `reporters/`)
```text
.assertstate/runs/<run-id>/
  run.json            # RunVerdict + RunMetadata
  contract.yaml       # the exact contract used
  trials/<trial-id>/  # agent_trace.json, baseline.json, after.json, delta.json, result.json (all redacted)
  evidence.zip        # the bundled, redacted artifact
  manifest.json       # sha256 of every file
```
- **Atomic writes:** write to a temp path, fsync, rename. **No overwrite** of an existing `<run-id>` (ids are unique).
- **Incomplete-run recovery:** a partially written run is marked `incomplete` in `run.json`; `report` surfaces that rather than pretending completeness.
- **Manifest:** SHA-256 per file; `report <run-id|path>` resolves by id under `.assertstate/runs/` or by explicit path.

---

## 31. Reporting (`reporters/`)
- **P0:** exit code (§8) + machine-readable JSON (`run.json`, `--json`). JUnit + HTML are **P1**.
- Reporters are pure formatters over the stored Run record; **they never alter a verdict** (import rule, §3; test §34).

---

## 32. Logging and diagnostics
- **Structured logging** (JSON lines) to **stderr**; verdict/JSON to **stdout**.
- Levels: DEBUG/INFO/WARN/ERROR; every line carries `run_id` + `trial_id`.
- **Secret filtering in logs:** a logging filter strips DSNs/creds/known secret patterns; child (adapter) logs are captured through the same filter so **oracle credentials can never appear** (they aren't in the child env anyway, INV-3, but defence-in-depth).
- Oracle/settlement/adapter logs are evidence-safe (redacted) before any are persisted.

---

## 33. Testing strategy (`tests/`)
```text
unit/        pure functions: comparators, delta, Wilson, completeness, snapshot guards, redaction, settlement SM
integration/ real Postgres: oracle read-only, snapshot/guards, template restore, seed→baseline, drain
e2e/         full orchestrator against the demo app: the acceptance matrix (§35)
adversarial/ the security/boundary suite (§36)
```

---

## 34. Unit-test matrix (required)
- Contract validation (schema + semantic + param ranges + money-as-string rejection of floats).
- Comparator behavior (each comparator incl. `eq_canonical` canon-v1, fail-closed non-finite, regex fullmatch, NULL).
- Configuration validation (read-only assertion path; redaction default allowlist).
- Snapshot completeness (`truncated → ERROR`), PK uniqueness (`non-unique → ERROR`), snapshot consistency mode selection.
- Delta classification (added/changed/removed) + predicate semantics (`added_where`/`changed_where{before,after}`/`removed_where`) + max-count thresholds.
- Settlement state machine (drain success; unverifiable/timeout/partial → ERROR; `bounded` success + fail-closed ERROR on a missing trusted anchor / unconfigured `max_wait`).
- Outcome classification (the §24 truth table, incl. the four ERROR-not-FAIL cases).
- Wilson calculation (exact values from FEATURE-SPEC §8.3) + completeness rules + `valid_trials==0 → INCONCLUSIVE`.
- Redaction (allowlist; fail-closed → nothing emitted).
- Artifact hashing (manifest SHA-256; atomic write).
- **Dependency tests:** `verifier/` imports no model client; reporters cannot change a verdict; `adapters/browser_use/child.py` not importable from the trusted process.

---

## 35. End-to-end P0 acceptance matrix (mandatory)
All run in an **isolated** env (attribution=causal). The agent reports DONE in the first seven; AssertState's verdict comes from the oracle.

| Scenario | Agent claims DONE | Actual application state | AssertState expected |
|---|---:|---|---|
| correct run | yes | correct | **PASS** |
| missing write | yes | absent | **FAIL** |
| wrong value | yes | wrong | **FAIL** |
| duplicate retry | yes | duplicate added | **FAIL** |
| slow retry | yes | later duplicate committed **before drain completes** | **FAIL** |
| wrong-tenant INSERT | yes | forbidden row added (`added_where`) | **FAIL** |
| wrong-tenant UPDATE | yes | forbidden tenant mutation (`changed_where`) | **FAIL** |
| oracle unavailable | irrelevant | unknown | **ERROR** |
| truncated snapshot | irrelevant | incomplete | **ERROR** |
| non-unique key | irrelevant | undefined diff | **ERROR** |
| seed impossible | irrelevant | precondition unavailable | **SKIPPED** |
| insufficient valid trials | mixed | incomplete run | **INCONCLUSIVE** |

The **slow-retry** row is the one that specifically demonstrates why P0 `drain` exists: without draining the worker queue, the duplicate would commit after an early after-snapshot and the run would false-PASS.

---

## 36. Adversarial security tests (required) — each with an explicit expected outcome
1. Malicious adapter tries to read `OracleTarget` → **unavailable** (not in child).
2. Malicious adapter tries to read the oracle DSN from env → **absent** (filtered, INV-3).
3. Malicious adapter inspects env vars → **only allowlisted (no `ORACLE_*`)**.
4. Malicious adapter accesses trusted artifact paths (`.assertstate/`) and arbitrary trusted-user files → **not reachable** (depends on the §10 sandbox; a bare subprocess would fail this).
5. Malicious adapter reaches the trusted IPC endpoint / trusted sockets beyond its own inherited fd → **denied** (depends on the §10 sandbox + fd-only IPC).
6. Adapter forges network/cost data in the response → **ignored** (verdict never reads them; extra keys rejected).
7. Malformed `AgentTrace` (missing/extra/typed-wrong keys) → **ERROR**.
8. Oversized IPC response (> cap) → **discarded → ERROR**.
9. Evidence redaction failure → **nothing emitted**; redaction-failure notice recorded.
10. Oracle query attempting mutation → **rejected by read-only role**; the run-setup (per-trial) role-privilege write-probe asserts it.
11. API oracle restricted to safe methods — a non-GET/HEAD request → **rejected** (observational-by-contract; `ApiProbe._SAFE_METHODS`). Shipped at P1.
12. Snapshot truncation bypass attempt (cap raised to hide a forbidden row via a narrow projection) → **`truncated`/projection warnings fire; truncated → ERROR**, and the projected-column warning (§17) is emitted.

*(1–5 are the SYSTEM-DESIGN §10 "boundary proof test"; until they pass, the §2/§4 boundary is "designed," not "enforced.")*

---

## 37. Definition of Done for P0 (mechanically checkable)
- [ ] All §34 unit tests pass.
- [ ] The process boundary is real **and sandboxed** (child in a container or hardened process with the §10 primitives; adversarial tests 4–5 pass, not just tests 1–3).
- [ ] Browser Use runs out-of-process; `child.py` not importable from the trusted process.
- [ ] Oracle credentials cannot reach the agent (tests 1–3, §36).
- [ ] Read-only oracle proven by **role-privilege** probe (INSERT into sentinel rejected), not by temp-table creation (§13).
- [ ] Baseline Snapshot taken after isolate+seed; after-Snapshot only after a proven `drain`.
- [ ] Snapshots fail closed (truncated/non-unique → ERROR).
- [ ] PK uniqueness enforced.
- [ ] `db_delta` catches added/changed/removed cases (incl. cross-tenant INSERT and UPDATE).
- [ ] Duplicate-scenario baseline is deterministic (0 rows pinned for the key).
- [ ] Agent self-report cannot influence the verdict (INV-8 test).
- [ ] Wilson calculation matches FEATURE-SPEC §8.3 exactly.
- [ ] Evidence is redacted fail-closed; redaction failure emits nothing.
- [ ] Local artifacts reproducible (manifest hashes stable across re-reads).
- [ ] CLI exit codes correct (§8).
- [ ] The full acceptance matrix (§35) and adversarial suite (§36) pass.

---

## 38. Implementation order (smallest dependency-respecting sequence)
For each step: prerequisites · modules · tests to add · completion condition.

1. **Project skeleton** — none · repo layout, tooling (§5) · smoke test · `ruff`/`mypy` green.
2. **Typed domain models** — 1 · `domain/` (§7, §24) · dataclass/enum unit tests · models import-clean.
3. **Contract loader/validator integration** — 2 · `contract/` · validation unit tests (§34) · `validate` passes/fails correctly.
4. **Configuration** — 2 · `config/` · read-only-assertion + allowlist tests · load errors → non-zero.
5. **Artifact store** — 2 · `evidence/` (store+manifest) · atomic-write + hashing tests · round-trip read.
6. **Demo DB schema + migrations + template** — 5 · `demo-app/` + `env/` template build · integration: template restore · per-trial DB created/dropped.
7. **DB oracle** — 4,6 · `oracle/db_probe/` · read-only + timeout + error-classification tests · mutation rejected.
8. **Snapshot + guards** — 7 · `oracle/snapshot/` · truncation/PK/consistency tests · fail-closed verified.
9. **Delta engine** — 8 · `oracle/delta/` · classification + predicate + max-count tests · matches §16.
10. **Demo queue/worker** — 6 · `demo-app/` worker + `QueueProbe` · controllable delay/duplicate/slow-retry · signals exposed.
11. **Drain controller** — 10 · `oracle/settlement/` · drain success + ERROR cases · §18 holds.
12. **Environment restore + seeding** — 6 · `env/` · seed→verify→baseline; seed-impossible → SKIPPED.
13. **Browser Use process runner** — 2 · `adapters/runner.py` · IPC/serialization/timeout/size + boundary tests 1–8 · INV-1..7 pass.
14. **Browser Use adapter (child)** — 13 · `adapters/browser_use/child.py` · produces AgentTrace; no DB access · tests 1–3 pass.
15. **Orchestrator** — 4–14 · `orchestrator/` · lifecycle wiring + outcome classification · one trial end-to-end.
16. **Expect evaluator** — 7,8 · `verifier/expect/` · comparator + eventually tests · expect.db works.
17. **`db_delta` policy** — 9,11 · `verifier/policy_engine/` · gating + attribution tests · policy fires correctly.
18. **Statistics** — 2 · `stats/` · Wilson + completeness + guards (§34) · exact numbers match.
19. **Evidence / redaction** — 5 · `evidence/` redaction · allowlist + fail-closed tests · nothing leaks.
20. **End-to-end acceptance suite** — 15–19 · `tests/e2e/` · the §35 matrix · all rows pass.
21. **Adversarial security suite** — 13,19 · `tests/adversarial/` · the §36 items · all pass.
22. **P0 validation** — 20,21 · — · the §37 checklist · P0 DONE.

---

## 39. Known limitations (honest; not bugs)
- The original P0 slice was **drain-based**; `bounded` settlement shipped at P1.
- The original P0 slice had **no network instrumentation**; P1 added trusted BrowserObservations → HTTP/external policies and the API oracle now ship.
- P0 does **not** claim shared-staging causality (isolated env only).
- **Budget:** only `max_seconds` is harness-trusted/gating in P0; `max_steps`/`max_cost_usd` are agent-reported → recorded as evidence, **non-gating** until P1 (§25).
- No `run_correlated` mutation audit in P0.
- No hosted control plane, no UI, no API service for AssertState itself.
These are deferred features (§40), not defects.

---

## 40. Future-phase hooks (where later work attaches — do not design here)
```text
P1  BrowserObservations + RunMeasurements (instrumentation/) → enables bounded settlement,
    HTTP/external policies (policy_engine/ slots), API oracle (oracle/api_probe/), trusted
    step/cost budget gating; GitHub Action; JUnit/HTML reporters.
P2  additional adapters (Stagehand/Playwright-MCP/JEV) behind the same runner; regression/model
    comparison (two-sample/McNemar). (run_correlated settlement + destructive_action gating SHIPPED.)
P3  hosted platform (users/orgs/roles, REST control plane, physical schema, UI) — post-launch, demand-driven.
```

---

## 41. SPEC MISMATCH / OPEN IMPLEMENTATION DECISION register
Format: Decision · Options · Recommendation · Why · What would change it.

**SPEC-MISMATCH-1 — `bound` vs `bounded` settlement mode name.** FEATURE-SPEC §5 wire value is `settle: { mode: bounded }`; SYSTEM-DESIGN §6.3 prose named the mode `bound`. · **Resolved (2026-10-04):** the wire value is **`bounded`** (FEATURE-SPEC is authoritative for contract semantics, rule 1); SYSTEM-DESIGN prose has been reconciled to `bounded` (only the dated v2.1 changelog line retains the old spelling as a historical record). Code uses `bounded` throughout.

**SPEC-MISMATCH-2 — settlement evidence field names.** FEATURE-SPEC §5 records `settle_started_at/settle_completed_at/settle_policy`; SYSTEM-DESIGN §4 TrialResult uses `causal_start_at/started_at/completed_at/bound_or_drain_signal`. · **Recommendation:** use SYSTEM-DESIGN's TrialResult field names (authoritative for the data model) and note the FEATURE-SPEC names as evidence aliases. · Why: one data model, one set of names. · Changes it: a source-doc edit unifying them.

**LIMITATION-1 — budget gating in P0 (see §25).** `max_steps`/`max_cost_usd` are only agent-reported in P0 (RunMeasurements is P1) → non-gating. · **Recommendation:** gate only `max_seconds` in P0; defer the rest to P1 trusted measurement. · Why: INV-8 forbids agent-reported metrics in the verdict. · Changes it: P1 instrumentation.

**OID-1 — repo sub-structure.** SYSTEM-DESIGN §14 is flat (`oracle/`, `verifier/`); this file nests sub-packages. · **Recommendation:** keep the nesting (§3) for testability. · Why: isolates db_probe/snapshot/delta/settlement for unit tests. · Changes it: nothing architectural — purely layout.

**OID-2 — IPC transport.** Options: stdin/stdout pipe · fd-passed unix socket. · **Recommendation:** pipe for P0, fd-passed socket for P1. · Why: least code that still enforces INV-4/INV-5 and keeps the endpoint off any user-readable path. · Changes it: a need for concurrency.

**OID-5 — child sandbox mechanism (backs INV-2/INV-7, §10).** Options: (a) rootless container (no repo/`.assertstate` mount, private net/PID/IPC ns, dedicated UID, no inherited fds); (b) hardened raw process (dedicated UID + restrictive FS perms + `close_fds` + fd-only IPC + protected `/proc`). · **Recommendation:** container for P0 — it makes adversarial tests 4–5 pass by construction and is less error-prone than assembling the primitives by hand. · Why: INV-7 is a security claim; a bare subprocess does not back it. · Changes it: an environment where containers are unavailable → then the hardened-process primitives are *all* mandatory, or tests 4–5 cannot pass and the boundary is not "enforced." · **Resolved (2026-10-04):** option (a) **Docker container**, implemented in `adapters/runner.py` (`mode="container"`) and engaged by the real run path via `--sandbox auto` (§10); the strict `--network none` variant backs adversarial tests 4–5, a `--network bridge` variant serves networked agents. Verified end-to-end for network-free adapters (the INV-7 suite runs real containers); the networked-agent image (Chrome) + egress policy is the remaining P1 hardening (`ASSERTSTATE_SANDBOX_IMAGE`), command-construction-tested here.

**OID-3 — predicate evaluator for `*_where`.** Options: restricted comparator AST · SQL-side filtering. · **Recommendation:** restricted AST over row dicts (no `eval`). · Why: deterministic, safe, testable. · Changes it: predicate complexity beyond equality/inequality.

**OID-4 — Python version, package manager, fixture format, exit-code granularity, drain QueueProbe shape** — smallest choices stated inline (§5, §8, §18, §21); revisit only on concrete need.

---

## Correctness guards — the bug classes this design defends against (cross-reference)
**False PASS** — each prevented by a named rule:
| Bug | Prevented by |
|---|---|
| Agent says DONE but write never happened | verdict reads oracle, not `agent_claimed_done` (§9, INV-8) |
| Verifier trusts the trace | `verifier/` has no adapter/trace-gating input (§3, §23) |
| Snapshot truncated | `truncated → ERROR` (§14) |
| Duplicate key pre-existing | baseline pinned to 0 rows for the key (§21, FEATURE-SPEC §5.2) |
| Cross-tenant UPDATE missed (only INSERT checked) | `changed_where` (§16, FEATURE-SPEC §5.1) |
| Async retry after an early snapshot | `drain` settlement before after-snapshot (§18) |
| Projected columns omit a forbidden mutation | projected-column rule + `validate` warning (§17) |
| Oracle itself mutates state | read-only role + load-time write-probe (§13) |
| Shared-staging delta mistaken for causal | gating requires `attribution==causal` (§23); P0 always isolated |
| Incomplete settlement treated as FAIL | settlement failure → ERROR (§18, §24) |

**Trust-boundary violations** — explicitly enforced: `Agent/Adapter ≠ Oracle` (INV-3); `AgentTrace ≠ BrowserObservations` (P0 has no BrowserObservations; trace is untrusted, §27); `agent-reported metrics ≠ trusted RunMeasurements` (§25); `BrowserTarget creds ≠ OracleTarget creds` (§12).

**Statistical misuse** — prevented: no `PASS/0` (`valid_trials==0 → INCONCLUSIVE`, §26); ERRORs/SKIPs can't vanish (capped by `max_error_rate`/`max_skip_rate`, §26); Wilson not used for regression (deferred to P2, §26); correlation not treated as independence (isolation + disclosed residual correlation, §2/§26).

---

## P0 BUILD CONTRACT
```text
Input:
  FEATURE-SPEC v2.3
  SYSTEM-DESIGN v2.2   (prompt cited v2.1; v2.2 is the current freeze-ready superset)

Build:
  AssertState P0 Core Engine

Must prove:
  an agent trajectory can report success
  while AssertState independently determines the actual application outcome
  and catches the specified forbidden side effects under isolated, drained execution

Must not build:
  hosted platform · UI · generic eval platform · network/red-team platform · other agent adapters

Success:
  all P0 acceptance (§35) and adversarial (§36) tests pass
  with deterministic verdicts and redacted, reproducible evidence (§37)
```

---

## Internal consistency review (performed against FEATURE-SPEC v2.3 + SYSTEM-DESIGN v2.2)
- ✅ Every P0 component (§1 scope) exists in the repo plan (§3).
- ✅ Every SYSTEM-DESIGN P0 component has an implementation module (orchestrator/oracle/verifier/stats/env/evidence/reporters/adapters).
- ✅ Every FEATURE-SPEC first-slice acceptance requirement (§16) maps to a test row (§35).
- ✅ The P0 core (oracle + `db_delta` + `drain` + isolation) stands on its own; P1 then added instrumentation, API oracle, and `bounded` settlement (all shipped) without changing the P0 verdict path.
- ✅ No adapter receives OracleTarget (INV-3; §10, §11; tests §36.1–3).
- ✅ INV-7 (artifact/socket unreachability) is backed by the §10 sandbox, not merely by "it's a subprocess" (tests §36.4–5); the honest scope of a plain subprocess is stated (§4).
- ✅ No oracle probe mutates, and the read-only proof is **role-privilege based** (INSERT into a non-granted sentinel rejected) — not `CREATE TEMP TABLE`, which PostgreSQL allows in READ ONLY (§13, §19).
- ✅ No incomplete snapshot can PASS (§14 fail-closed).
- ✅ No unverifiable settlement can PASS (§18 → ERROR).
- ✅ No settlement uncertainty becomes FAIL (§18, §24).
- ✅ No agent-reported metric enters the verdict (INV-8; §25 budget limitation).
- ✅ No shared-staging observed delta presented as causal (§23 gating rule; P0 always isolated).
- ✅ No unredacted sensitive evidence can be emitted (§28 fail-closed).
- ✅ No architecture silently changed — all divergences from the source docs are logged in §41.
- ⚠️ Two **SPEC MISMATCH** items between the source docs (bound/bounded; settlement field names) and one P0 **LIMITATION** (budget gating) are reported in §41 rather than fixed here, per rule 7.

---

## References
[FEATURE-SPEC.md](FEATURE-SPEC.md) v2.3 · [SYSTEM-DESIGN.md](SYSTEM-DESIGN.md) v2.2 · [FEATURE-DOC.md](FEATURE-DOC.md) · [AUDIT-3-agents.md](AUDIT-3-agents.md) · [scenarios.md](scenarios.md) · [outreach.md](outreach.md).
