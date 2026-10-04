# AssertState — Core Engine System Design (v2.2, freeze-ready)

Engineering design for the **core verification engine** specified in [FEATURE-SPEC.md](FEATURE-SPEC.md) (v2.3). This is **how the engine is built**; the feature doc is **what it does**. Where they disagree, FEATURE-SPEC wins.

> **Scope: the OSS core engine only.** The **hosted platform** — users/orgs/roles/tenancy, the REST API, the physical control-plane database schema, and the UI/UX — is **NOT designed here**; it is deferred until WTP is validated (§20). Calling this the "whole system" would be dishonest: it is the acceptance-engine architecture, which is correctly serverless today.

> **v2 changelog (post-review, 2026-10-02):** fixed the adapter↔oracle trust-boundary leak (adapter no longer receives oracle credentials); split untrusted `AgentTrace` from trusted `BrowserObservations`/`RunMeasurements`; made snapshot truncation fail-closed + PK-uniqueness checked; made the API oracle explicitly read-only; tightened `drain`, the settlement causal start-point, and `run_correlated` (mutation/audit record); corrected the Wilson/correlation wording + empty-N/param guards; added the full Policy Engine (forbidden_action/authorization/destructive/external); scoped transactional-rollback isolation (app must propagate the TX); added run provenance metadata + local artifact store; froze the stack (Python core / Browser Use / Postgres / Chromium); retitled Core Engine + deferred the hosted product.

> **v2.1 changelog (second review, 2026-10-02):** made the adapter boundary a **real OS process/container boundary** with narrow IPC, not an in-process plugin (the logical trust boundary is now mechanically enforced); resolved the **P0 settlement contradiction** by making P0 `drain`-only (`bound` needs trusted request timing → P1); made the API oracle **observational by application contract** (dedicated read-only endpoints / read-only service identity + allowlist), with GET/HEAD only a default restriction; added **instrumentation tamper-resistance** (agent cannot reach the CDP control channel; append-only verifier-owned observation buffer); classified **settlement-guarantee-unavailable → ERROR** (never FAIL); stated **`db_delta` visibility = projected columns only** + rejected volatile projections; defined **snapshot consistency** (single-query statement snapshot; multi-query = one REPEATABLE READ read-only txn).

> **v2.2 changelog (third review → FREEZE-READY, 2026-10-02):** closed the last semantic gap — a **`db_delta` policy gates only under causal attribution**; on shared staging an observed delta is **evidence-only / non-gating** (gating-but-observed → INCONCLUSIVE, never FAIL), so FAIL keeps meaning "the workflow violated the contract" (`expect`/`http`/`external_*` stay gating, being this-run-attributed by construction). Added the **boundary proof test** (adversarial malicious-adapter integration test: ORACLE_DSN / artifact dir / IPC socket / CDP port / trusted paths all inaccessible) as the enforcement proof of §2. No architecture change — this is the freeze point; next validation = building P0 and attacking it.

**One-line purpose:** run a browser agent against an app, then decide pass/fail from an **independent read of the application's own state** (DB/API) and **causally-attributed side-effects**, as a statistical CI gate that emits a redacted evidence bundle.

---

## 1. Goals & constraints
**Goals:** correctness of the verdict above all (false PASS is the cardinal sin) · deterministic scoring (no LLM in pass/fail) · framework-neutral (agent is a swappable, out-of-process adapter) · statistically honest (Wilson + completeness) · security-grade (read-only oracle, hardened CI, fail-closed evidence) · small/swappable/solo-maintainable.

**Hard constraints (from validation):**
- Side-effect verdicts use **before/after causal deltas with a settlement guarantee** (`bounded` | `drain` | `run_correlated`), never post-run counts.
- Causal attribution only under an **isolated environment**; shared staging = *observed delta*, labeled.
- **Oracle credentials never reach the untrusted agent** — enforced by a real process/container boundary, not just logical separation (§2).
- Oracle probes are **observational by contract** (read-only DB role; API via read-only service identity + endpoint allowlist, GET/HEAD as default restriction).
- Settlement is correctness-valid only as **`drain` (P0)** / **`bounded` with trusted causal timing (P1, shipped)** / **`run_correlated` (P2)**; an unprovable settlement is **ERROR, never FAIL**.
- A **truncated** snapshot can never produce PASS.

**Non-goals:** browser engine, LLM eval/leaderboards, trace viewer/replay, red-team platform, runtime action-blocking (FEATURE-SPEC §15).

---

## 2. Architecture & the trust boundary

```
     ┌══════════════ TRUSTED PROCESS (orchestrator / oracle / verifier) ══════════════┐
 CLI ─▶ Loader+Validator ─▶ Run Orchestrator ─▶ Verifier(Policy Engine) ─▶ Stats ─▶ Evidence ─▶ Reporters
                                 │        ▲            ▲
                                 │        │            │ reads only
                                 │   OracleTarget (read-only DB + read-only API)  ◀────────┘
                                 │   Instrumentation (CDP/proxy) → verifier-owned append-only buffer
                                 │   Environment Manager (isolate/seed/reset)
     └══════════════════════════ │ ════════════════════════════════════════════════════┘
                                 │ NARROW IPC — in: {task, BrowserTarget, ExecutionBudget, run_id}
                                 │             out: {AgentTrace} ONLY.  No Python objects cross.
     ┌──────────────────── ▼ ──── UNTRUSTED PROCESS / CONTAINER ────────────────────────┐
     │   Execution Adapter ─▶ Agent ─▶ Browser Runner (Chromium)  → returns AgentTrace    │
     └───────────────────────────────────────────────────────────────────────────────── ┘
```

**The boundary is the whole design, and it is a real OS boundary — not just a logical one.** The agent/adapter/browser may do anything, so the untrusted side runs in its **own subprocess or container**, not inside the trusted Python process:
- Only **{task, `BrowserTarget`, `ExecutionBudget`, run_id}** cross *in*, and only an **`AgentTrace`** crosses *out*, over a narrow IPC channel (serialized values, not live objects). No trusted-side Python object, `OracleTarget` reference, env var, or file handle is reachable from the untrusted side.
- Rationale: an in-process plugin can read `os.environ`, module globals, the `OracleTarget` object, and process memory regardless of any "logical" separation. The process/container boundary is what makes "oracle creds never reach the agent" **mechanically enforceable** instead of aspirational. The DB oracle's read-only role is defence-in-depth on top, not the primary control.
- The verdict is computed by the **trusted** side from: the **OracleTarget** reads + trusted **BrowserObservations** (captured by the trusted instrumentation process, §3.8) + the contract. The agent's `AgentTrace` is recorded as evidence but **never trusted for pass/fail** (its `agent_claimed_done` is explicitly ignored).

---

## 3. Components

### 3.1 CLI
`validate` / `run` / `report`. Exit 0 (all PASS) / non-zero (any FAIL or INCONCLUSIVE). Delegates to the orchestrator.

### 3.2 Contract Loader + Validator `[P0 done]`
YAML → typed `Contract`; schema + semantic validation (comparator shapes; every `db_delta` requires a valid `settle`; `expect` causality warning; param ranges §7.4). Rejects invalid contracts before any run.

### 3.3 Config Loader
Loads `assertstate.yaml`: named **OracleTarget** (read-only db_dsn, read-only api_base+creds) and **BrowserTarget** (base_url, browser creds) per app; allow/deny domains; default `statistics`; canonicalizer version; reset hook; redaction policy. Secrets from env. Verifies the DB role is read-only (attempt a write in a savepoint, assert rejection) and the API oracle is observational-by-contract (read-only service identity + endpoint allowlist; GET/HEAD default restriction, §3.7).

### 3.4 Run Orchestrator
Owns the trial loop + per-trial sequence (§5). Enforces isolation, classifies PASS/FAIL/ERROR/SKIPPED, feeds the Statistics Engine. The orchestrator — not the adapter — holds the OracleTarget and drives all oracle reads.

### 3.5 Execution Adapter (out-of-process, UNTRUSTED)
The adapter runs in the **untrusted subprocess/container** (§2), reached over narrow IPC — NOT loaded into the trusted process. The authored interface is still a simple protocol:
```python
class ExecutionAdapter(Protocol):
    name: str
    # Runs INSIDE the untrusted process. Receives only serialized BrowserTarget;
    # never an OracleTarget, DSN, or trusted-side object.
    def run(self, task: str, browser: BrowserTarget, budget: ExecutionBudget) -> AgentTrace: ...
```
The trusted orchestrator launches the untrusted process (its own env, no oracle secrets), serializes `{task, BrowserTarget, budget, run_id}` across the IPC boundary, and reads back **only** an `AgentTrace` (steps + `agent_claimed_done`). **It does not return network/cost used for the verdict** (those come from the trusted instrumentation process, §3.8). A new adapter is "untrusted code" by definition, so adapter authorship never widens the trust surface. Browser Use first.

### 3.6 Browser Runner
The Chromium instance the adapter drives (local in P1). Replaceable. Trusted **BrowserObservations** attach here (CDP/proxy), independent of the adapter.

### 3.7 OracleTarget (the trusted oracle) — read-only, observational
- **DB probe:** read-only, least-privilege role; parameterized SELECTs for snapshots + `expect` reads; statement timeout; result-cardinality guard (§6.2).
- **API probe:** **observational by application contract**, not by HTTP method. The invariant is *the oracle must not alter the system it measures* — and GET/HEAD alone does not prove that (a GET can lazy-init, increment, or write audit/log rows). So the API oracle requires **one of**: (a) dedicated read-only oracle endpoints the app guarantees are side-effect-free, or (b) a dedicated **read-only service identity** + an **endpoint allowlist**. GET/HEAD-only is layered on top as a *default restriction* (POST/PATCH/DELETE from a probe is a config error), not as the proof of non-mutation. Separate oracle credentials. *Rule: oracle probes may never mutate application state.*

### 3.8 Trusted instrumentation (not from the adapter) — tamper-resistant
- **BrowserObservations** `[P1]`: network events + request/response timing, captured via CDP/proxy at the Browser Runner, within a declared boundary (Service-Worker gaps disclosed). Feeds `http`/`external_*` policies. (Excluded from the first slice, §19.)
- **RunMeasurements** `[P1]`: wall-time, action count, token/cost — measured by the harness, not reported by the agent (so budget checks can't be gamed).
- **Tamper resistance (what makes "trusted" real):** the CDP/proxy **control channel is reachable only by the trusted instrumentation**, never by the agent (the agent gets a launched browser, not the debugging endpoint). The observation stream is **append-only into a verifier-owned buffer** on the trusted side; the untrusted process cannot read, rewrite, or truncate it. Without this, "trusted" would be only a label.

### 3.9 Verifier → Policy Engine
Given baseline + after snapshots + OracleTarget + BrowserObservations + contract → a TrialResult. The Verifier orchestrates deterministic evaluators (no LLM):
```
Verifier
 ├── expect evaluator        # db/api final-state reads (+ eventually polling)
 ├── settlement controller   # bounded | drain | run_correlated  (§6.3)
 └── Policy Engine (forbid)
      ├── db_delta            # settled before/after diff (§6)   [P1]
      ├── http                # 200-with-error-body etc.         [P1, needs BrowserObservations]
      ├── external_request / external_top_level_navigation / external_data_transfer  [P1]
      ├── forbidden_action    # tool/action outside allowed set  [P1] *
      ├── authorization       # stayed in scope                  [P1] *
      └── destructive_action  # approval observed before irreversible op  [P2]
```
> \* `forbidden_action` / `authorization` are **semantics, not separate policy kinds**. They are
> realized by `db_delta` (an out-of-scope or wrong-tenant write — seed contracts 06 and 04) and by
> the `external`/`http` policies (a forbidden request — seed 08): a trusted read of the application's
> own state IS the authorization check. There is no trace-based "forbidden action" gate, which would
> violate INV-8 (the agent's self-reported actions never decide the verdict).

### 3.10 Statistics Engine
TrialResults → RunVerdict: Wilson lower bound over valid trials + completeness; separate two-sample/paired comparison for regression/model-swap (§7).

### 3.11 Environment Manager
Per-trial isolation (seed → run → reset). Pluggable strategies (§9). Owns the disposable demo env in the first slice. Isolation = correctness (uncorrelated trials + causal attribution).

### 3.12 Evidence Builder (fail-closed redaction)
Assembles the redacted bundle (§11) with run provenance (§4) + scope statement + manifest hashes. Allowlist redaction runs here before anything is written.

### 3.13 Reporters
JUnit, HTML, exit code — pure formatters over the Run record + artifact store (§13).

---

## 4. Data model

```
Contract                 # parsed YAML (FEATURE-SPEC §2): task, app, expect[], forbid[], budget, statistics, preconditions[]

OracleTarget             # TRUSTED, never crosses the IPC boundary to the agent
  db_dsn_readonly, api_base, api_creds_readonly (read-only service identity),
  api_endpoint_allowlist   # observational-by-contract (§3.7); GET/HEAD is a default restriction, not the proof
BrowserTarget            # given to the agent
  base_url, browser_creds
ExecutionBudget          # max_steps, max_cost_usd, max_seconds

AgentTrace               # UNTRUSTED (from adapter)
  steps[], agent_claimed_done
BrowserObservations      # TRUSTED instrumentation
  network[] { method,url,status,req_body,resp_body,timing }, last_causal_request_completed_at
RunMeasurements          # TRUSTED harness measurement
  wall_seconds, action_count, cost_usd

Snapshot                 # oracle read set at a point in time
  taken_at
  queries: { query_id -> { rows_by_pk, row_count, complete: bool, truncated: bool, pk_unique: bool } }

Delta                    # diff(before, after) per db_delta query, by PK
  added[], changed[{pk,before,after}], removed[]

TrialResult
  outcome: PASS|FAIL|ERROR|SKIPPED
  expect_results[], policy_results[], budget_results
  settlement { mode, causal_start_at, started_at, completed_at, bound_or_drain_signal }
  attribution: causal | observed
  refs: { agent_trace, browser_obs, baseline, after }
  reason

RunVerdict
  verdict: PASS|FAIL|INCONCLUSIVE
  total_trials, valid_trials, pass, fail, error, skipped
  pass_rate, wilson_lower, confidence, side, pass_threshold, error_rate, skip_rate
  per_trial[]

RunMetadata (provenance — recorded with every run)   # §12 reproducibility
  run_id, assertstate_version, contract_hash, scenario_id
  adapter_name+version, agent/model/provider, system_prompt_hash
  browser_version, app_build_git_sha, db_schema_fingerprint
  fixture_version, env_image, canonicalizer_version
  statistics_config, settlement_config, timestamp_tz

RunManifest              # run config, NOT the contract
  targets[], contracts[globs], statistics_overrides?
```

---

## 5. Run lifecycle (per trial, `trials: N`)
```
load+validate · resolve OracleTarget+BrowserTarget · capture RunMetadata · for trial 1..N:
  1. ISOLATE    Environment Manager: fresh/isolated env (single-writer for causal attribution)
  2. SEED       apply preconditions/fixtures; impossible → SKIPPED
  3. BASELINE   OracleTarget: baseline Snapshot for every db_delta query (fail if truncated/pk-not-unique → ERROR)
  4. ACT        Adapter.run(task, BrowserTarget, budget)   [untrusted; NO oracle creds]
                  Browser Runner executes; BrowserObservations + RunMeasurements captured independently
                  returns AgentTrace (claimed_done recorded, ignored for verdict)
                  executor/infra failure → ERROR
  5. SETTLE     settlement controller: drain (queue-state, needs no causal clock); bounded (P1, shipped)
                  from last_causal_request_completed_at (needs trusted instrumentation); P2 = run_correlated.
                  settlement guarantee unprovable (drain unverifiable / bound source absent / timeout) → ERROR (not FAIL)
  6. AFTER      OracleTarget: after Snapshot (post-settlement; truncation/pk guards again)
  7. VERIFY     expect (reads + eventually) AND Policy Engine (delta/http/external/forbidden/authz) AND budget
                  PASS iff all expect hold AND no GATING policy fired AND budget ok; else FAIL; oracle/verifier failure → ERROR
                  attribution = causal (isolated env) | observed (shared staging)
                  GATING rule: a db_delta policy may gate only under causal attribution; on shared staging an
                  observed db_delta is evidence-only (non-gating) — it can never PASS/FAIL (§6.5)
  8. RECORD     TrialResult (+ evidence refs)
after loop:
  9. AGGREGATE  Statistics Engine → RunVerdict
 10. EMIT       Evidence Builder (redact) + Reporters + artifact store
```

---

## 6. The `db_delta` engine (core correctness)

### 6.1 Snapshot
Per `db_delta.query`, the result set keyed by the declared PK/`key:`, via the read-only probe. Baseline after isolate/seed, after post-settlement.

### 6.2 Completeness & key guards (fail-closed)
- A snapshot carries `row_count`, `complete`, `truncated`. The DB probe's result cap exists for safety, but **a truncated snapshot → ERROR/INCONCLUSIVE, never PASS** (a forbidden row beyond the cap must never be silently missed). Caps must be set above the expected working-set, or the query narrowed.
- The declared PK/`key:` is **validated unique** in the result (a join can duplicate keys); non-unique → ERROR (the diff is undefined otherwise).

### 6.3 Settlement controller
`diff` is only valid after causally-complete writes are observable. Each mode and the phase it is valid in:
- **`drain`** (**P0, the only correctness-valid mode in the first slice**) — observes **queue/worker state directly**, so it needs no causal-start timestamp and therefore no browser instrumentation. Defined precisely: **(a) no queued workflow-owned jobs AND (b) no in-flight/active workflow-owned jobs AND (c) no producer can still enqueue work for this run AND (d) all downstream writes covered by the drain contract are observable.** An "empty queue" alone is insufficient.
- **`bounded`** (**P1, SHIPPED — needs trusted instrumentation**) — wait a documented `max_wait` that covers **app + worker + read-replica propagation**, **starting from the last causal browser-originated request completion** (`BrowserObservations.last_causal_request_completed_at`), NOT from "agent said DONE." Because that causal clock comes from trusted instrumentation (§3.8), `bounded` is only correctness-valid once instrumentation is present; the original P0 slice had no such source and used `drain`, and P1 added the trusted parent-owned capture that supplies it. Without the anchor, `bounded` fails closed to ERROR. The bound guarantee is an environmental assumption recorded in evidence.
- **`run_correlated`** (P2+) — the long-term-correct design. Does NOT rely on a `run_id` column on new rows (that misses UPDATE/DELETE of pre-existing rows). Instead uses an **application mutation/audit record** `{mutation_id, run_id, table, pk, op(INSERT|UPDATE|DELETE), before, after, ts}`; the diff is computed from mutations tagged with this run, removing temporal inference. Requires app cooperation.
- `poll_until_stable` — optional heuristic layered on the above, **never the sole guarantee**.
- **Settlement failure is ERROR, never FAIL.** If the required guarantee cannot be established — drain cannot be verified, the `bounded` causal-start source is absent, or settlement times out — the trial is **ERROR** ("could not establish correctness"), never FAIL. FAIL is reserved for "the workflow actually violated the contract."

### 6.4 Diff & predicates
`diff(before, after)` by PK → added/changed/removed (§4). Predicate semantics (FEATURE-SPEC §5): `added_where` on the after-row; `changed_where: {before, after}` (string = after-only); `removed_where` on the before-row; each with `max_added`/`max_changed`/`max_removed` (default 0).

### 6.5 Attribution scope — and the gating rule
Isolated single-writer env → Delta == run-caused → **causal** verdict. Shared staging (concurrent writers) → **observed** delta; RunVerdict/evidence labeled `attribution: observed`. Never claim causality the environment can't back.

**Gating rule (so FAIL keeps meaning "the workflow violated the contract"):** a `db_delta` policy is **acceptance-gating only under causal attribution**. On shared staging an observed delta might have been caused by another developer or a background job, so a fired observed `db_delta` is **emitted as evidence but is non-gating** — it can produce neither PASS nor FAIL. If a contract's `db_delta` is marked gating but the environment can only provide `observed` attribution, that policy yields **INCONCLUSIVE** (causal verdict not established), never a FAIL.
- Note: `expect` final-state reads and `http`/`external_*` policies are *this-run-attributed by construction* (final observed state / this browser's own captured requests), so they can still gate on shared staging; only `db_delta`, which relies on *environmental* causal attribution, is subject to this restriction.

### 6.6 Query visibility (avoid the projected-column false PASS)
A `db_delta` query only observes **the columns it projects**. `SELECT id, tenant_id FROM payments` can detect added/removed rows and tenant changes, but **cannot** see `amount` change — so a forbidden `amount` mutation would silently PASS. Therefore:
- The contract documents, and `validate` warns, that **a `db_delta` query establishes changes only over its projected columns** — `db_delta(payments)` does NOT mean "all changes to `payments`." To police a column, project it (or `SELECT *` the governed subset).
- **Volatile/nondeterministic projections are rejected** at load (e.g. `now()`, `random()`, unstable ordering without a key): they would produce spurious before/after diffs. Only stable, deterministic columns may appear in a snapshot projection.

### 6.7 Snapshot consistency
- **Single query:** read at the DB's own statement snapshot — internally consistent by definition.
- **Multi-query snapshot (one baseline/after built from several queries):** either taken inside **one read-only `REPEATABLE READ` transaction** (so all queries see the same DB state — required before any cross-query invariant), **or** the queries are declared **independent observations** with no cross-query atomicity claimed. The first slice uses independent observations per policy; the REPEATABLE-READ mode is required when multi-query invariants are added.

---

## 7. Statistics engine

### 7.1 Trial classification — PASS/FAIL/ERROR/SKIPPED.
### 7.2 Acceptance gate — `valid_trials = PASS+FAIL`; `wilson_lower = Wilson(PASS, valid_trials, confidence, side)`; completeness (`valid_trials ≥ min_valid_trials`, `error_rate ≤ max_error_rate`, `skip_rate ≤ max_skip_rate`) else INCONCLUSIVE; PASS iff completeness AND `wilson_lower ≥ pass_threshold`. Defaults `confidence=0.95`, `side=one_sided`. `error_rate=ERROR/total`, `skip_rate=SKIPPED/total`.
### 7.3 What Wilson does and doesn't do (corrected wording)
Wilson **quantifies uncertainty of a binomial proportion under the stated trial model; it does NOT remove correlation among trials.** A fresh env removes inherited-side-effect correlation, but common model/provider/system-prompt/browser/infra effects remain and are **disclosed** alongside the interval, not assumed away.
### 7.4 Guards
- `valid_trials == 0` → INCONCLUSIVE; never compute `PASS/0`.
- Validate at load: `0 < confidence < 1`, `0 ≤ pass_threshold ≤ 1`, `0 ≤ max_error_rate ≤ 1`, `0 ≤ max_skip_rate ≤ 1`, `min_valid_trials ≤ trials`.
### 7.5 Regression / version comparison (distinct from the gate)
Two-sample difference-in-proportions + CI (independent runs) or paired McNemar (same scenarios). Never inferred from Wilson-interval overlap.

---

## 8. Execution adapter interface
`run(task, BrowserTarget, ExecutionBudget) -> AgentTrace` (§3.5), executed **in the untrusted subprocess/container** across narrow IPC (§2). Browser Use `[P1 first]`; Stagehand/Playwright MCP/JEV `[P2]` (JEV thin). An adapter is registered (entry-point/config) but **launched out-of-process** — registration never means in-process loading. The core trusts no adapter output for the verdict, and **no adapter ever receives OracleTarget or any trusted-side object**.

---

## 9. Environment & isolation
Isolation is correctness (uncorrelated trials + causal attribution). Strategies, by robustness:
- **Template/snapshot restore** (`CREATE DATABASE … TEMPLATE`) — **P1 default** for the demo env.
- **Container-per-trial** — strongest, slowest.
- **BYO reset hook** (`reset_cmd`).
- **Transactional rollback** — **only valid when the application explicitly propagates the test transaction** into its own request handling. A TX around the AssertState process does NOT wrap the app's separate DB connections (Postgres transactions are session-scoped), so this is opt-in per app, not a generic default.
Seeding: declarative fixtures post-isolation; failed seed → SKIPPED.

---

## 10. Security architecture
- **Trust boundary (§2) is a real process/container boundary:** the agent/adapter/browser run out-of-process; only `{task, BrowserTarget, budget, run_id}` cross in and only `AgentTrace` crosses out, over narrow IPC. No oracle object, DSN, env var, or file handle is reachable from the untrusted side — enforcement, not intent.
- **Read-only oracle:** DB SELECT-only on specific schema/views + timeout + cardinality cap; API oracle observational **by application contract** (read-only endpoints or read-only service identity + allowlist), with GET/HEAD-only as a default restriction on top (§3.7); all verified at config load.
- **Instrumentation tamper resistance (§3.8):** CDP/proxy control channel unreachable by the agent; observations append-only into a verifier-owned buffer.
- **CI threat model (FEATURE-SPEC §10.1):** fork PRs get no staging secrets; secrets only on trusted branches/protected envs; PR contract/query changes run in an unprivileged sandbox until maintainer approval; CI egress default-deny + app allowlist.
- **Fail-closed redaction (§11).**
- **Boundary proof test (required before the boundary is called "enforced"):** a deliberately **malicious adapter** must fail to reach any trusted-side secret or channel — `ORACLE_DSN`/oracle creds from env, the trusted artifact/evidence directory, the trusted IPC socket, the CDP/debug port, and trusted-process filesystem paths — **all inaccessible**. This is the proof of §2, run as an adversarial integration test (§19), not another architecture change.

---

## 11. Evidence bundle (redacted)
```
run.json        # RunVerdict + RunMetadata provenance (§4, §12)
contract.yaml
trials/<id>/ { agent_trace.json, browser_obs.json, baseline.json, after.json, result.json }  # all redacted
scope.txt       # establishes … ; does NOT establish … ; attribution: causal|observed
manifest.json   # sha256 of every file
```
Redaction is **allowlist / fail-closed**: nothing sensitive leaves unless whitelisted (credentials, headers, cookies, query text with PII, SQL result fields all masked by default; body-size caps). P3: signed bundle.

---

## 12. Reproducibility (RunMetadata)
Every run records the full provenance block in §4 (assertstate/adapter/model/system-prompt-hash/browser/app-git-sha/db-schema-fingerprint/fixture/env-image/canonicalizer versions + stats & settlement config + timestamp/tz). Without it, the evidence shows *what* happened but not enough to reproduce *why*.

---

## 13. Artifact store & `report`
No server in OSS core, so runs persist locally:
```
.assertstate/runs/<run-id>/ { run.json, contract.yaml, trials/, evidence.zip }
```
`assertstate report <run-id | path>` formats a stored run (JUnit/HTML). The store is an interface (local filesystem now; object store later for hosted).

---

## 14. Tech stack (FROZEN for the first slice) & repo layout
- **Core: Python.** **First adapter: Browser Use.** **DB: PostgreSQL.** **Browser: Chromium.** TypeScript is a later *integration surface*, not a P0 architecture choice. (The adapter abstraction matters precisely because Browser Use/Stagehand/JEV evolve fast.)
```
assertstate/
  cli.py
  contract/      # loader+schema+validate [P0 done]
  config/        # OracleTarget, BrowserTarget, secrets, redaction policy
  orchestrator/  # trial loop, outcome classification, RunMetadata capture
  adapters/      # browser_use/ (p1), stagehand/ playwright_mcp/ jev/ (p2)
  oracle/        # db_probe(ro), api_probe(ro), snapshot(+guards), delta, settlement
  instrumentation/ # browser_observations (cdp/proxy), run_measurements
  verifier/      # expect, policy_engine(db_delta/http/external/forbidden/authz/destructive), comparators
  stats/         # wilson, completeness, regression
  env/           # isolation strategies, seeding, reset hooks
  evidence/      # redaction(fail-closed), bundler, manifest, provenance
  reporters/     # junit, html, exit code, artifact store
  demo-app/      # disposable Postgres app + controllable async retry worker (first slice)
  contracts/     # example contracts (scenarios.md)
```
License Apache-2.0.

---

## 15. Extensibility
New adapter → implement `ExecutionAdapter` (gets `BrowserTarget` only). New oracle source → a read-only probe behind OracleTarget (event-log/Kafka, S3, second DB); `db_delta`/`expect` generalize to any keyed state source. New policy/comparator → register in the Policy/comparator registry (must be deterministic). The "external application oracle" (DB + API + invariants + event/log + network) is the extensibility spine.

---

## 16. Failure modes
| Failure | Classified | Handling |
|---|---|---|
| Agent/executor crash | ERROR | excluded from Wilson; capped by `max_error_rate` |
| Seed can't be established | SKIPPED | capped by `max_skip_rate` |
| Oracle DB/API unreachable | ERROR | never a silent pass |
| Snapshot truncated / PK not unique | ERROR | never PASS (§6.2) |
| Async write after settlement | prevented | `bounded`/`drain`/`run_correlated` (§6.3) |
| Settlement guarantee unavailable (drain unverifiable / bound source absent / timeout) | ERROR | cannot establish correctness; never FAIL (§6.3) |
| Forbidden column not in query projection | prevented at authoring | `db_delta` sees projected columns only; `validate` warns (§6.6) |
| Concurrent writer (shared staging) | labeled | `attribution: observed` |
| Gating `db_delta` fires on shared staging (maybe another writer) | INCONCLUSIVE | observed delta is non-gating evidence; never FAIL (§6.5) |
| Adapter reports fake network/cost | prevented | verdict uses trusted BrowserObservations/RunMeasurements, not AgentTrace |
| Flaky run-to-run | expected | N-trial Wilson *quantifies* (does not remove) uncertainty; correlation disclosed |
| valid_trials == 0 | INCONCLUSIVE | no `PASS/0` |

---

## 17. One-trial sequence (detail)
```
Orchestrator        Env Mgr     Adapter/Browser(UNTRUSTED)   Instrumentation   OracleTarget(RO)   Verifier
   │ isolate ─────────▶│                                                                           │
   │ seed ────────────▶│                                                                           │
   │ baseline ──────────────────────────────────────────────────────────────▶ rows(before)+guards │
   │ run(task,BrowserTarget,budget) ─▶│ acts                                                       │
   │                                   │ ─▶ network/timing ─▶ BrowserObservations                   │
   │◀── AgentTrace(claimed_done) ──────│                                                           │
   │ settle: P0 drain(queue state) · P1 bound(from last_causal_request) … wait …                   │
   │ after ─────────────────────────────────────────────────────────────────▶ rows(after)+guards  │
   │ verify(before,after,browser_obs,contract) ──────────────────────────────────────────────────▶│ expect+policies
   │◀── TrialResult(attribution) ─────────────────────────────────────────────────────────────────│
   │ record ─▶ artifact store                                                                       │
```

---

## 18. Open design questions
- Default isolation per app type (template restore vs container).
- `run_correlated` requires an app-side mutation/audit record — worth it for shared-staging causality; scope in P2.
- Canonicalizer (`canon-v1`) coverage set — versioned, extend per domain.
- Apps with **no** drain signal and **no** documented propagation bound: a *causal* verdict may be impossible — state this honestly (offer only `observed`).

---

## 19. First-slice design (what gets built first)
Minimal set to prove the thesis (FEATURE-SPEC §16): `contract`(done) + `orchestrator` (launching the untrusted agent **out-of-process**, §2) + `adapters/browser_use` + `oracle/{db_probe(ro), snapshot(+guards), delta, settlement(drain only)}` + `verifier/{expect, db_delta}` + `stats/{wilson, completeness, guards}` + `env/{postgres template-restore, seed}` + `evidence/{redact(fail-closed), json, provenance}` + artifact store + exit code.
- **The original P0 slice used `drain` as the only correctness-valid settlement mode** (it observes queue state and needs no causal clock). `bounded` shipped at P1 once the trusted browser instrumentation that supplies its causal start-point was added; absent that anchor it fails closed to ERROR. This resolves the former P0 settlement contradiction.
- **Deferred past the original P0 slice, SINCE SHIPPED at P1:** BrowserObservations/network capture (and therefore `bounded`), http/external policies, API oracle, GitHub Action, HTML. (`forbidden_action`/`authorization` are realized via `db_delta`+external/http, not separate kinds — §3.9.) **Still deferred:** other adapters (Stagehand/Playwright-MCP/JEV), `run_correlated`, cross-version/cross-agent comparison.
- **Phasing:** **P0** proves oracle + `db_delta` + `drain` settlement + isolation. **P1 (shipped)** added trusted instrumentation → `bounded` + http/external policies + API oracle + container sandbox on the run path. **P2** adds `run_correlated` + cross-version/cross-agent comparison.
- **Demo app:** tiny Postgres-backed payment workflow + a **controllable async retry worker** (so `drain` has a real, observable queue to settle against).
- **Acceptance (functional):** inject wrong-value / missing / duplicate-on-slow-retry / cross-tenant-INSERT / cross-tenant-UPDATE failures → AssertState FAILs each (agent reports DONE), PASSes the correct run, reproducibly over N trials with a reported Wilson interval, `attribution: causal`. This is the empirical validation.
- **Acceptance (security — the boundary proof test):** a malicious test adapter attempts to read `ORACLE_DSN`/oracle creds, the trusted artifact dir, the trusted IPC socket, the CDP/debug port, and trusted-process paths → **every attempt fails**. Until this passes, the §2 boundary is "designed," not "enforced."

---

## 20. Platform / Hosted product design — DEFERRED (not yet designed)
The hosted product (`[P3]`, gated on WTP) is **out of scope for this doc** and explicitly not designed yet. When WTP is validated, it will need its own design for:
- **Identity & tenancy:** User / Organization / Project / Role / Membership / ServiceAccount.
- **REST API:** `POST /projects/:id/app-targets`, `POST /contracts`, `POST /runs`, `GET /runs/:id`, `GET /runs/:id/evidence`, … with auth, error model, idempotency, pagination.
- **Control-plane physical schema:** actual PostgreSQL tables/columns/PKs/indexes/FKs, migrations, retention, evidence/object storage.
- **UI/UX:** dashboard, contract editor, run/trial detail, failure inspection, evidence browser, project/app-target settings.
- **Multi-run infra:** parallel cloud runs, regression history, signed evidence, SSO/RBAC.
Listing these here keeps the doc honest: this file is the **engine**, not the platform.

---

## 21. References
[FEATURE-SPEC.md](FEATURE-SPEC.md) · [FEATURE-DOC.md](FEATURE-DOC.md) · [AUDIT-3-agents.md](AUDIT-3-agents.md) · [scenarios.md](scenarios.md) · [outreach.md](outreach.md).
