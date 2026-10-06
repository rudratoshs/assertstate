# AssertState — P0 Implementation Backlog

> **This is a task/issue backlog, not a design document.** It turns [DEVELOPMENT.md](DEVELOPMENT.md) v1.1 §38's 22-step implementation order into concrete, executable tasks to hand to a coding agent. It adds **no new architecture** — every requirement here traces to a frozen source section. Where a task needs a choice the docs left open, it cites the existing `OPEN IMPLEMENTATION DECISION` (DEVELOPMENT.md §41); it does not invent new ones.

**Frozen inputs (do not reopen):** [FEATURE-SPEC.md](FEATURE-SPEC.md) v2.3 · [SYSTEM-DESIGN.md](SYSTEM-DESIGN.md) v2.2 (confirmed on disk) · [DEVELOPMENT.md](DEVELOPMENT.md) v1.1.

**Goal of P0:** prove the thesis — *an agent can report success while AssertState independently determines the real application outcome and catches the specified forbidden side-effects under isolated, drained execution* (DEVELOPMENT.md P0 BUILD CONTRACT).

**How to use:** work tasks in ID order unless the dependency graph permits parallelism (below). A task is not Done until its Definition of Done is mechanically satisfied. Every task's tests are written *in that task*, not deferred.

---

## Dependency graph / critical path
```
P0-01 skeleton
  └─ P0-02 domain models
       ├─ P0-03 contract loader/validator ─┐
       ├─ P0-04 config ───────────┐        │
       ├─ P0-05 artifact store     │        │
       └─ P0-18 statistics         │        │
P0-06 demo DB+template ◀───────────┘        │
  ├─ P0-07 DB oracle ◀── P0-04               │
  │    └─ P0-08 snapshot+guards              │
  │         └─ P0-09 delta engine            │
  ├─ P0-10 demo queue/worker                 │
  │    └─ P0-11 drain controller             │
  └─ P0-12 env restore + seeding             │
P0-13 adapter process runner ◀── P0-02       │
  └─ P0-14 Browser Use child                 │
P0-15 orchestrator ◀── P0-03..P0-14 ─────────┘
  └─ P0-X1 DRAIN WIRING (integration)   ← the heart of the P0 correctness claim
P0-16 expect evaluator ◀── P0-07,08
P0-17 db_delta policy  ◀── P0-09,11
P0-19 evidence/redaction ◀── P0-05
P0-20 e2e acceptance suite ◀── P0-15,16,17,18,19,X1
P0-21 adversarial suite ◀── P0-13,19
P0-22 P0 validation ◀── P0-20,21
```
**Parallelizable early:** P0-03/04/05/18 after P0-02; P0-06 can start immediately after P0-01. **Critical path:** 01→02→06→07→08→09→(17)→15→X1→20→22.

---

## P0-01 — Project skeleton
- **Purpose:** a runnable, typed, linted Python project (DEVELOPMENT.md §3, §5).
- **Prerequisites:** none.
- **Files/modules:** `pyproject.toml`, `assertstate/` package tree (empty packages per §3), `tests/`, `.gitignore`, `conftest.py` stub.
- **Implementation requirements:** Python 3.11+; `uv` + `pyproject` (OID-4); `ruff` (format+lint); `mypy --strict` on `assertstate/`; `pytest`; `.gitignore` covers `.assertstate/`, `.venv/`, `*.evidence.zip`, `.env`.
- **Security/correctness invariants:** none yet (scaffold).
- **Tests required:** a smoke test importing the package; CI-style `ruff` + `mypy` run.
- **Acceptance criteria:** `ruff`, `mypy --strict`, `pytest` all green on an empty project.
- **Definition of Done:** repo layout matches §3 exactly; tooling green.
- **Dependencies:** —

## P0-02 — Typed domain models
- **Purpose:** the shared typed vocabulary used everywhere (DEVELOPMENT.md §7, §24).
- **Prerequisites:** P0-01.
- **Files/modules:** `domain/` — `contract.py`, `targets.py` (OracleTarget, BrowserTarget, ExecutionBudget), `trace.py` (AgentTrace; BrowserObservations/RunMeasurements declared, P1-inert), `snapshot.py`, `delta.py`, `result.py` (TrialResult, outcome enum), `verdict.py` (RunVerdict), `metadata.py` (RunMetadata), `manifest.py` (RunManifest), `comparator.py` (Comparator enum + `ComparatorValue`).
- **Implementation requirements:** dataclasses + enums per §7; `ComparatorValue = str | Decimal | tuple[str,...] | None`; money as string→Decimal; `SettlementConfig.mode` accepts `"drain"` (P0), parses `"bounded"`/`"run_correlated"` but marks them unsupported in P0.
- **Security/correctness invariants:** `domain/` imports nothing internal (dependency-inversion root, §3); INV-8 encoded structurally — the verdict-input types exclude `agent_claimed_done`/trace-step-count/adapter-cost as gating fields.
- **Tests required:** construction/immutability tests; enum completeness; `ComparatorValue` shape helpers.
- **Acceptance criteria:** every type in the §4/§7 data model exists with the frozen field names.
- **Definition of Done:** `mypy --strict` clean; no internal imports in `domain/`.
- **Dependencies:** P0-01.

## P0-03 — Contract loader / validator integration
- **Purpose:** YAML → typed `Contract` → schema + semantic validation (DEVELOPMENT.md §7; FEATURE-SPEC §2, §8). *(Contract loader/`validate` is `[P0 done]` per FEATURE-SPEC — this task integrates/hardens it against the v1.1 model.)*
- **Prerequisites:** P0-02.
- **Files/modules:** `contract/loader.py`, `contract/schema.py`, `contract/semantic.py`.
- **Implementation requirements:** parse pipeline `YAML→parse→typed→schema→semantic→executable`; operand type must match comparator (§7 rules); every `db_delta` has a valid `settle` (P0: `drain`); reject YAML floats for `eq_canonical` money; statistics param ranges (§26); `expect` causality warning (FEATURE-SPEC §5); `changed_where` string↔{before,after} normalization.
- **Security/correctness invariants:** invalid contract never reaches `run` (CLI exit 2, §8).
- **Tests required:** valid/invalid contract fixtures; comparator-operand mismatch; float-money rejection; missing `settle`; param-range failures; causality warning emitted.
- **Acceptance criteria:** `assertstate validate` passes good contracts, fails bad ones with precise messages.
- **Definition of Done:** §34 "contract validation" + "comparator behavior" unit rows pass.
- **Dependencies:** P0-02.

## P0-04 — Configuration
- **Purpose:** `assertstate.yaml` → OracleTarget/BrowserTarget/statistics/redaction/env config (DEVELOPMENT.md §6).
- **Prerequisites:** P0-02.
- **Files/modules:** `config/loader.py`, `config/secrets.py`.
- **Implementation requirements:** required/optional fields per §6; secret refs (`env:...`) resolved trusted-side; `redaction.mode` defaults `allowlist` (fail-closed); known P0 `environment.strategy` only; split trusted oracle config from agent-visible browser config.
- **Security/correctness invariants:** secrets never persisted (§6); oracle DSN never placed where it could enter the child env (feeds INV-3 at P0-13).
- **Tests required:** secret resolution; allowlist default; unknown-strategy rejection; missing-required-field → non-zero.
- **Acceptance criteria:** config errors become CLI failures; no partial runs.
- **Definition of Done:** §34 "configuration validation" passes.
- **Dependencies:** P0-02.

## P0-05 — Artifact store
- **Purpose:** local `.assertstate/runs/<run-id>/` with atomic writes + manifest (DEVELOPMENT.md §30).
- **Prerequisites:** P0-02.
- **Files/modules:** `evidence/store.py`, `evidence/manifest.py`.
- **Implementation requirements:** layout per §30; atomic write (temp→fsync→rename); no overwrite of an existing run-id; `incomplete` marking; SHA-256 manifest; `report` lookup by id or path.
- **Security/correctness invariants:** artifact dir path is a trusted-only location (never mounted into the child, see P0-13).
- **Tests required:** atomic-write; manifest hashing; incomplete-run surfacing; round-trip read.
- **Acceptance criteria:** a written run re-reads identically; manifest hashes stable.
- **Definition of Done:** §34 "artifact hashing" passes.
- **Dependencies:** P0-02.

## P0-06 — Demo DB schema + migrations + template
- **Purpose:** the disposable payment app DB + the restore template (DEVELOPMENT.md §19, §20).
- **Prerequisites:** P0-01.
- **Files/modules:** `demo-app/schema.sql`, `demo-app/grants.sql`, `env/template.py`.
- **Implementation requirements:** tables `tenants/payments/payment_jobs/run_markers/assertstate_readonly_probe` (§19); build template DB once; migrator role owns objects; **oracle role: SELECT on app tables only, NO write grant on `assertstate_readonly_probe`** (§13, §19).
- **Security/correctness invariants:** the grant model is what makes the §13 read-only probe meaningful.
- **Tests required:** template builds; oracle role can SELECT; oracle role INSERT into sentinel → permission denied.
- **Acceptance criteria:** `CREATE DATABASE ... TEMPLATE` works from the template.
- **Definition of Done:** integration test confirms grants + template.
- **Dependencies:** P0-01.

## P0-07 — PostgreSQL Oracle
- **Purpose:** the trusted read-only Postgres oracle (DEVELOPMENT.md §13).
- **Prerequisites:** P0-04, P0-06.
- **Files/modules:** `oracle/db_probe/`.
- **Implementation requirements:** read-only connection (`default_transaction_read_only = on`); parameterized SELECT only; `statement_timeout`; cardinality cap feeding Snapshot `row_count/truncated`; short-lived connections; **role-privilege read-only verification at config load** (INSERT into `assertstate_readonly_probe` inside a savepoint MUST raise; **never** `CREATE TEMP TABLE`, §13); error classification (conn/auth/timeout/permission → ERROR).
- **Security/correctness invariants:** oracle never mutates (role + load probe); all failure modes → ERROR, never silent pass.
- **Tests required:** oracle role cannot INSERT (sentinel); parameterization; timeout → ERROR; auth failure → ERROR; cardinality cap sets `truncated`.
- **Acceptance criteria:** the four "Must prove" facts hold (no INSERT; no mutation; timeout→ERROR; auth→ERROR).
- **Definition of Done:** integration tests green; §36 item 10 wired.
- **Dependencies:** P0-04, P0-06.

## P0-08 — Snapshot + guards
- **Purpose:** `Snapshot` with fail-closed completeness/key guards (DEVELOPMENT.md §14, §15).
- **Prerequisites:** P0-07.
- **Files/modules:** `oracle/snapshot/`.
- **Implementation requirements:** `rows_by_key`, `row_count`, `complete`, `truncated`, `pk_unique`, `taken_at`, `consistency`; single-query statement snapshot (P0 path); REPEATABLE-READ multi-query mechanism implemented but unused in P0; **explicit-`key:` rule** (present/non-null/deterministic/stable; null key → ERROR, §14).
- **Security/correctness invariants:** `truncated==True → ERROR`; `pk_unique==False → ERROR`; null explicit key → ERROR. Never PASS on any of these.
- **Tests required:** truncation→ERROR; duplicate key→ERROR; null `key:`→ERROR; statement vs REPEATABLE-READ selection.
- **Acceptance criteria:** no incomplete/ambiguous snapshot can proceed to a PASS.
- **Definition of Done:** §34 "snapshot completeness/PK/consistency" rows pass.
- **Dependencies:** P0-07.

## P0-09 — Delta engine
- **Purpose:** `diff(before, after) -> Delta` with exact predicate semantics (DEVELOPMENT.md §16, §17).
- **Prerequisites:** P0-08.
- **Files/modules:** `oracle/delta/`.
- **Implementation requirements:** O(n) keyed set-diff → added/changed/removed; predicate semantics (`added_where`=after-row, `changed_where.before`/`.after`, `removed_where`=before-row); max-count thresholds (default 0 when `*_where` present); **restricted comparator AST** for `*_where` (no `eval`, OID-3); projected-column visibility rule + volatile-projection rejection + key-in-projection requirement (§17).
- **Security/correctness invariants:** a forbidden mutation outside the projection is impossible to catch — enforced by the §17 validation warnings, not silently assumed; runtime type mismatch → ERROR not FAIL.
- **Tests required:** added/changed/removed classification; `{before,after}` cross-tenant steal; max-count thresholds; projected-column warning; volatile-projection rejection.
- **Acceptance criteria:** cross-tenant INSERT (added) and UPDATE (changed) both detected.
- **Definition of Done:** §34 "delta classification + predicate semantics" pass.
- **Dependencies:** P0-08.

## P0-10 — Demo queue / worker
- **Purpose:** controllable async retry worker so `drain` has a real queue (DEVELOPMENT.md §19).
- **Prerequisites:** P0-06.
- **Files/modules:** `demo-app/worker.py`, `demo-app/queue_probe.py`.
- **Implementation requirements:** process `payment_jobs` (`queued→active→done`); controllable `process_after` delay; controllable duplicate + slow-retry injection; `run_markers.last_processed_job`; `QueueProbe` reporting `queued`, `active`, `producers_closed` (§18).
- **Security/correctness invariants:** worker writes are the "run-caused" writes the oracle must observe post-drain; the processed-marker enables drain condition (d).
- **Tests required:** each fault-injection mode produces the intended DB state; slow-retry commits a duplicate after a would-be-early snapshot.
- **Acceptance criteria:** all seven §35 scenarios are producible on demand.
- **Definition of Done:** worker + QueueProbe drive every acceptance-matrix state.
- **Dependencies:** P0-06.

## P0-11 — Drain controller
- **Purpose:** the only P0-valid settlement mode (DEVELOPMENT.md §18).
- **Prerequisites:** P0-10.
- **Files/modules:** `oracle/settlement/`.
- **Implementation requirements:** `SettlementController.drain(cfg)`; verify conditions (a) no queued, (b) no active, (c) `producers_closed`, (d) processed-marker observable to the oracle role; poll to `timeout_s`; **`bounded` NOT implemented in P0**.
- **Security/correctness invariants:** drain unverifiable / timeout / partial evidence → **ERROR, never FAIL** (§18, §24).
- **Tests required:** drain success; each of unverifiable/timeout/partial → ERROR; `bounded` rejected.
- **Acceptance criteria:** after-snapshot only proceeds on a proven drain.
- **Definition of Done:** §34 "settlement state machine" passes.
- **Dependencies:** P0-10.

## P0-12 — Environment restore + seeding
- **Purpose:** per-trial isolation + fixtures (DEVELOPMENT.md §20, §21).
- **Prerequisites:** P0-06.
- **Files/modules:** `env/restore.py`, `env/seed.py`.
- **Implementation requirements:** `CREATE DATABASE ... TEMPLATE` per trial, unique naming; apply scenario fixtures; verify seed → unestablishable precondition → **SKIPPED**; duplicate-scenario baseline pinned to 0 rows for the key (§21); `DROP DATABASE` cleanup; failed cleanup logged, never changes verdict; transactional rollback NOT the P0 default (§20).
- **Security/correctness invariants:** trials independent (Wilson validity, FEATURE-SPEC §9.3); seed failure never becomes FAIL.
- **Tests required:** per-trial unique DB; seed→baseline; seed-impossible → SKIPPED; duplicate baseline deterministic.
- **Acceptance criteria:** fresh isolated env every trial; cleanup robust.
- **Definition of Done:** integration tests green.
- **Dependencies:** P0-06.

## P0-13 — Adapter process runner (sandbox + IPC)
- **Purpose:** launch the untrusted agent out-of-process behind a real sandbox (DEVELOPMENT.md §4, §10). **Security-critical.**
- **Prerequisites:** P0-02.
- **Files/modules:** `adapters/base.py` (Protocol), `adapters/runner.py`.
- **Implementation requirements:** **sandbox per OID-5** — container (recommended) or hardened process (dedicated UID + restrictive FS perms + `close_fds` + fd-only IPC + protected `/proc`); filtered child env (allowlist; strip all `ORACLE_*`/DSNs/secrets); JSON-only length-prefixed IPC over one parent-owned fd; request/response size caps; hard wall-clock timeout; crash/malformed/oversized → ERROR; child stdout/stderr captured to a redacted log.
- **Security/correctness invariants:** INV-1..INV-7 (§4). Request carries only `{task, browser_target, execution_budget, run_id}`; response only `{steps, agent_claimed_done}`. No Python object crosses (no pickle).
- **Tests required:** the §36 boundary suite 1–8 (ORACLE_DSN/env/artifact-path/socket inaccessible; forged metrics ignored; malformed/oversized → ERROR).
- **Acceptance criteria:** adversarial tests 1–8 pass — the boundary is *enforced*, not just designed.
- **Definition of Done:** §36.1–8 green; `child.py` not importable from trusted process.
- **Dependencies:** P0-02.

## P0-14 — Browser Use child adapter
- **Purpose:** the first (untrusted) Execution Adapter (DEVELOPMENT.md §11).
- **Prerequisites:** P0-13.
- **Files/modules:** `adapters/browser_use/child.py`.
- **Implementation requirements:** read IPC request; construct Browser Use agent with `browser_target`; inject task; run under budget (child-local caps); collect steps + done-claim; shut browser down; emit `{steps, agent_claimed_done}`; pin Browser Use + Chromium versions.
- **Security/correctness invariants:** no DB access, no OracleTarget, no verdict logic (INV-3); only `browser_target.creds`.
- **Tests required:** produces a valid AgentTrace; cannot import `oracle/`/`config/`; crash → non-zero exit → parent ERROR.
- **Acceptance criteria:** runs a task end-to-end in the sandbox, returns AgentTrace.
- **Definition of Done:** adversarial tests 1–3 pass through the real adapter.
- **Dependencies:** P0-13.

## P0-15 — Orchestrator
- **Purpose:** the trial loop + lifecycle + outcome classification (DEVELOPMENT.md §9, §24).
- **Prerequisites:** P0-03,04,05,07,08,09,11,12,13,14.
- **Files/modules:** `orchestrator/`.
- **Implementation requirements:** lifecycle `isolate→seed→baseline→act→settle→after→verify→record→cleanup`; capture RunMetadata (§29, unknown→null never faked); `agent_claimed_done` → evidence only; outcome classification per §24 (the four ERROR-not-FAIL cases; SKIPPED; FAIL=completed violation); attribution always `causal` in P0 (assert isolated).
- **Security/correctness invariants:** INV-8 (no agent-reported field gates); cleanup failure never upgrades a verdict.
- **Tests required:** one full trial per outcome class; ERROR-not-FAIL cases; attribution==causal asserted.
- **Acceptance criteria:** a single trial runs end-to-end and classifies correctly.
- **Definition of Done:** §34 "outcome classification" passes against the real loop.
- **Dependencies:** P0-03..P0-14.

## P0-X1 — DRAIN WIRING (integration) — the heart of the P0 correctness claim
- **Purpose:** prove the full causal settlement chain end-to-end, not just the pieces (reviewer-requested; DEVELOPMENT.md §18, §19, §35 slow-retry row).
- **Prerequisites:** P0-10, P0-11, P0-12, P0-15.
- **Files/modules:** `tests/integration/test_drain_wiring.py` (+ any glue in `orchestrator`/`oracle/settlement` exposed by the test).
- **Implementation requirements:** one integration test demonstrating the chain:
  ```
  agent action → run-owned job enqueued → worker active → slow retry →
  producer closure (producers_closed) → queue drained (no queued/active) →
  processed marker observable to oracle → after snapshot → db_delta sees the duplicate → FAIL
  ```
  Must bind `run_id` ownership, queue ownership, `producers_closed`, and `last_processed_job` together.
- **Security/correctness invariants:** without drain, the slow-retry duplicate commits after an early after-snapshot → false PASS; this test proves drain closes that race (the core P0 claim).
- **Tests required:** this single end-to-end drain test (slow-retry duplicate) → **FAIL**; and a control where the correct run drains cleanly → **PASS**.
- **Acceptance criteria:** slow-retry → FAIL and correct run → PASS, both via the real drain path.
- **Definition of Done:** the chain above passes as one test; gates P0-20.
- **Dependencies:** P0-10, P0-11, P0-12, P0-15.

## P0-16 — Expect evaluator
- **Purpose:** P0 `expect.db` final-state assertions (DEVELOPMENT.md §22).
- **Prerequisites:** P0-07, P0-08.
- **Files/modules:** `verifier/expect/`.
- **Implementation requirements:** read-only SELECT after settlement; comparator application (`equals`/`eq_canonical` canon-v1/`in`/`lt..gte` fail-closed non-finite/`regex` fullmatch/`absent`/`any`); money as string→Decimal; multi-row first-row/aggregate; NULL explicit; AND semantics; `eventually` polling for db; causality caveat honored via load warning.
- **Security/correctness invariants:** query error → ERROR; evaluation deterministic over captured reads (acquisition may poll, §2 reworded).
- **Tests required:** each comparator; eventually polling; NULL; AND of multiple asserts; query error → ERROR.
- **Acceptance criteria:** expect.db passes/fails correctly against the demo app.
- **Definition of Done:** §34 "comparator behavior" + expect tests pass.
- **Dependencies:** P0-07, P0-08.

## P0-17 — db_delta policy
- **Purpose:** the P0 Policy Engine subset (DEVELOPMENT.md §23).
- **Prerequisites:** P0-09, P0-11.
- **Files/modules:** `verifier/policy_engine/`.
- **Implementation requirements:** `Policy` protocol (deterministic, side-effect-free over captured Snapshots); `DbDeltaPolicy` using the delta engine; registry slots for HttpPolicy/ExternalPolicy/Authorization/Destructive (P1+); **gating only under `attribution=="causal"`** (observed → INCONCLUSIVE, §6.5) — asserted even though P0 is always causal.
- **Security/correctness invariants:** no I/O beyond reading captured Snapshots; no model calls; `verifier/` imports no model client (dependency test).
- **Tests required:** policy fires on added/changed/removed per thresholds; gating-attribution assertion; registry extensibility smoke.
- **Acceptance criteria:** wrong-tenant INSERT and UPDATE both produce FAIL.
- **Definition of Done:** §34 "delta/predicate" + policy gating tests pass.
- **Dependencies:** P0-09, P0-11.

## P0-18 — Statistics engine
- **Purpose:** Wilson lower bound + completeness → RunVerdict (DEVELOPMENT.md §26; FEATURE-SPEC §8).
- **Prerequisites:** P0-02.
- **Files/modules:** `stats/`.
- **Implementation requirements:** `valid_trials=PASS+FAIL`; `wilson_lower=Wilson(PASS, valid_trials, confidence, side)`; completeness (`min_valid_trials`/`max_error_rate`/`max_skip_rate`); defaults `confidence=0.95`/`side=one_sided`; guards (`valid_trials==0 → INCONCLUSIVE`; param ranges at load); **no** regression/comparison in P0.
- **Security/correctness invariants:** no `PASS/0`; ERRORs/SKIPs capped not laundered; Wilson not used for regression; correlation disclosed in output.
- **Tests required:** exact Wilson numbers (20/20=0.881, 25/25=0.902, 30/30=0.917, 35/35 two-sided=0.901); completeness → INCONCLUSIVE; zero-valid → INCONCLUSIVE.
- **Acceptance criteria:** verdicts match FEATURE-SPEC §8.3 exactly.
- **Definition of Done:** §34 "Wilson + completeness" rows pass.
- **Dependencies:** P0-02.

## P0-19 — Evidence / redaction
- **Purpose:** fail-closed EvidenceBundle + provenance (DEVELOPMENT.md §27, §28, §29).
- **Prerequisites:** P0-05.
- **Files/modules:** `evidence/bundle.py`, `evidence/redact.py`, `evidence/provenance.py`.
- **Implementation requirements:** per-trial record (contract hash, AgentTrace, baseline, after, Delta, TrialResult, settlement, attribution, RunMetadata); network evidence explicitly `out_of_scope_p0` (not a fake empty trace); redaction pipeline `raw→allowlist→redact→size-limit→validate→write`; **fail-closed** (pipeline error → emit nothing); RunMetadata unknown fields → null, never faked; settlement fields use SYSTEM-DESIGN names (§27 note).
- **Security/correctness invariants:** nothing sensitive leaves unless whitelisted; redaction failure never emits an unredacted bundle.
- **Tests required:** allowlist masks creds/cookies/headers/PII; redaction failure → nothing written; provenance null-not-faked.
- **Acceptance criteria:** a run emits a redacted, hashed, self-describing bundle.
- **Definition of Done:** §34 "redaction" + §36 item 9 pass.
- **Dependencies:** P0-05.

## P0-20 — End-to-end acceptance suite
- **Purpose:** prove the thesis empirically (DEVELOPMENT.md §35).
- **Prerequisites:** P0-15, P0-16, P0-17, P0-18, P0-19, P0-X1.
- **Files/modules:** `tests/e2e/test_acceptance_matrix.py`.
- **Implementation requirements:** every §35 row: correct→PASS; missing/wrong/duplicate/slow-retry/cross-tenant-INSERT/cross-tenant-UPDATE→FAIL; oracle-unavailable/truncated/non-unique→ERROR; seed-impossible→SKIPPED; insufficient-valid→INCONCLUSIVE. Agent reports DONE in the first seven.
- **Security/correctness invariants:** verdict always from the oracle; slow-retry demonstrates why drain exists (overlaps P0-X1).
- **Tests required:** the full 12-row matrix, reproducible over N trials with a reported Wilson interval, attribution=causal.
- **Acceptance criteria:** every matrix row yields its expected verdict.
- **Definition of Done:** the §35 matrix passes.
- **Dependencies:** P0-15,16,17,18,19,X1.

## P0-21 — Adversarial security suite
- **Purpose:** prove the trust boundary + fail-closed behavior (DEVELOPMENT.md §36).
- **Prerequisites:** P0-13, P0-19.
- **Files/modules:** `tests/adversarial/`.
- **Implementation requirements:** all 12 §36 items, each with an explicit expected outcome (boundary 1–5 depend on the §10 sandbox; forged metrics ignored; malformed/oversized → ERROR; redaction failure → nothing; oracle mutation rejected; unsafe API config rejected; truncation/projection → ERROR+warnings).
- **Security/correctness invariants:** the boundary is enforced, not documented.
- **Tests required:** the 12 items.
- **Acceptance criteria:** all 12 pass.
- **Definition of Done:** §36 suite green.
- **Dependencies:** P0-13, P0-19.

## P0-22 — P0 validation
- **Purpose:** confirm the Definition of Done (DEVELOPMENT.md §37).
- **Prerequisites:** P0-20, P0-21.
- **Files/modules:** `tests/` aggregate run + a short `P0-VALIDATION-REPORT.md` (results only — not a design doc).
- **Implementation requirements:** run the full suite; fill the §37 checklist mechanically; record the Wilson interval on the correct-run scenario.
- **Security/correctness invariants:** every §37 box checked by a passing test, not by assertion.
- **Tests required:** the whole pyramid green.
- **Acceptance criteria:** §37 checklist fully satisfied.
- **Definition of Done:** P0 is DONE; proceed to launch/outreach (FEATURE-SPEC §17 / outreach.md), not more docs.
- **Dependencies:** P0-20, P0-21.

---

## Out of scope for this backlog (do NOT create)
Per DEVELOPMENT.md §40 + FEATURE-SPEC §17: no `API-DESIGN.md` / `DB-DESIGN.md` / `UI-DESIGN.md` / `SECURITY-DESIGN.md`; no BrowserObservations/CDP, `bounded` settlement, HTTP/external policies, API oracle, other adapters, GitHub Action, HTML, `run_correlated`, hosted platform, UI, users/orgs/roles. Those are P1–P3, later phases. **After P0-22, the next artifact is code's validation result + the direct launch (FEATURE-SPEC §17 / outreach.md) — not another specification.**

## References
[FEATURE-SPEC.md](FEATURE-SPEC.md) v2.3 · [SYSTEM-DESIGN.md](SYSTEM-DESIGN.md) v2.2 · [DEVELOPMENT.md](DEVELOPMENT.md) v1.1 · [scenarios.md](scenarios.md) · [outreach.md](outreach.md).
