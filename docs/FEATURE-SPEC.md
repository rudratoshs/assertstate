# AssertState — Detailed Feature Specification (v2.3, validated)

> **v2.3 changelog (v2.2 re-validation, 2026-10-02):** corrected the settlement overclaim — `poll_until_stable` alone does NOT close the async race; settlement is correctness-valid **only** under a documented propagation `bound`, queue `drain`, or `run_correlated` tagging (§5a). Added precise `added/changed/removed_where` predicate semantics (before/after rows), a `removed_where` example, a required baseline-fixture note for duplicate checks, explicit error/skip denominators, and softened "none packages" → "we did not identify in the reviewed set." Verdict: **architecturally sound; settlement contract now honestly specified.**

> **v2.2 changelog (2-agent validation + review, 2026-10-02):** fixed the two blocking `db_delta` holes — (a) **settlement policy** for async/retry writes *(see v2.3 correction: valid only under bound/drain/run_correlated)*, (b) **`changed_where`/`removed_where`** so cross-tenant UPDATEs are caught, not just INSERTs; clarified `expect` = final-state vs `db_delta` = causal-change (causality requires isolation OR a baseline OR a delta); scoped causal attribution to isolated envs (observed-delta-only on shared staging); **disclosed prior art** (backend-state grading is established — BreakingWeb + academic sandboxes — differentiation is the *productized combination*, not the primitive); re-anchored the LangSmith/eval distinction on *trajectory-vs-external-state* (not "LLM vs not"); unified `max_added`; clarified `targets:` as a run manifest; money literals as strings; redaction default fail-closed; cut network capture from the first slice. Verdict going in: **architecturally coherent; oracle semantics now specified for correctness.**

> **AssertState is a deterministic acceptance harness for autonomous browser workflows: the agent may choose how to act, but only authoritative application state and explicit side-effect policies determine whether the workflow passed.**

> **Name `AssertState` (pkg `assertstate`).** Chosen after two collisions were verified and rejected: `agent-contracts` (taken — relari/vahwali) and `Groundline` (taken — usegroundline.com, live, same evidence/AI-trust space). `assertstate` verified clear on **GitHub org, npm, PyPI, and no live .com/.io** (2026-10-02). Only remaining step before public launch: a **trademark search** (non-blocking for internal docs).

> **Document status: build specification for a WTP-gated OSS experiment** — NOT a validated SaaS opportunity. The problem is well-evidenced; willingness-to-pay is unproven. Build gated on §17.

**v2 changelog (from review, 2026-10-02):** fixed Wilson statistics (confidence + sided + realistic N); defined trial-outcome aggregation (PASS/FAIL/ERROR/SKIPPED/INCONCLUSIVE); added eventual-consistency polling; made `duplicate`/`touch_other_tenant` compile to explicit SQL; split `external_domain_navigation` into navigation vs request vs data-transfer; made `http_200_with_error_body` configurable; moved adapter selection out of the contract; added CI secret/threat model + evidence redaction; reframed state-isolation as experiment validity; scoped all "nobody/only/unique" claims to "none identified in the 10-competitor review"; added BreakingWeb as primary evidence.

**Companion docs:** [FEATURE-DOC.md](FEATURE-DOC.md) (10-competitor matrix) · [AUDIT-3-agents.md](AUDIT-3-agents.md) (go/no-go) · [scenarios.md](scenarios.md) · [outreach.md](outreach.md).

**Research basis:** competitor "context" boxes are grounded in the two 2026-10-02 feature-extraction passes (Relari, MS ASSERT, Promptfoo, Momentic, Giskard, LangSmith, Braintrust, Laminar, Playwright+Test Agents, OSS cluster — the cluster includes EvalView/state-eval/agent-eval-workbench/groundtruth, detailed in [AUDIT-3-agents.md](AUDIT-3-agents.md)). Claims of absence are scoped to **that reviewed set**, never universal.

**Phase tags:** `[P0]` done · `[P1]` MVP · `[P2]` reach · `[P3]` commercial-only-if-WTP-proven.

---

## 0. The product in one layer

| Layer | Strong tools (reviewed) |
|---|---|
| Agent execution | Browser Use / Stagehand / JEV |
| Browser test automation | Playwright |
| Agent trajectory eval | LangSmith / Braintrust / EvalView |
| Agent security / red-team | Promptfoo / Giskard |
| Agent observability / replay | Laminar |
| Behavioral policy / regression | Microsoft ASSERT |
| **External application oracle** | **← AssertState** |

AssertState's oracle is the **external application state** (DB + API + business invariants + event/log state + network side-effects), not the agent's trajectory or self-report. "backend SQL" is just its first implementation.

> **Prior-art disclosure (honest):** backend/application-state grading of browser-agent tasks is **NOT novel** — it is established in research (our own citation **BreakingWeb** defines tasks by target backend state with positive obligations + invariants; academic sandboxes **WASP / SecureWebArena / Thinkingbox / LegacyWorld** grade backend state too), and Playwright can assert server-side state via API testing. The differentiation is **not the primitive** — it is the *productized combination for real write-capable browser-agent workflows*: a framework-neutral, deterministic, isolated acceptance harness that packages external-state assertions + side-effect policy + a statistical gate + redacted evidence, reusable across agents. Whether that packaging is worth paying for is the open question (§17), not whether the oracle idea is new.

### Design principles (apply to every feature)
1. **Authoritative application state is the oracle** — never the agent's `DONE`, never the trajectory.
2. **Deterministic scoring over the right evidence source** — no LLM in the pass/fail path; typed predicates over live application state. The defensible axis is **trajectory/tool-call evidence vs independently-observed external application state**, NOT "LLM vs deterministic grader." _(LangSmith/Braintrust now ship deterministic code graders too — but they assert over the agent's trajectory/tool-calls, not an independent read of your app's backend. A deterministic grader on the wrong evidence source still doesn't answer "did the application state actually change.")_
3. **Statistically honest** — N-trial Wilson lower bound at a defined confidence; never a single run or a bare mean (§8).
4. **Framework-neutral** — one contract, swappable execution adapter (§6).
5. **Experiment validity first** — trials must be independent; state isolation is correctness, not convenience (§9).
6. **Security-grade handling** — read-only oracle, redacted evidence, hardened CI (§10–§11).
7. **Lead on the productized combination**, not any single "unique" primitive (§15, §18).

---

## 1. Core concepts / data model
- **Contract `[P0]`** — declarative YAML for one workflow: task + oracle assertions + side-effect policy + budget + statistics. Framework-neutral (no adapter inside it — §2.4).
- **Scenario** — Contract + fixtures/seed + environment binding; one Contract → many Scenarios.
- **AppTarget `[P1]`** — the oracle access layer: a **read-only, least-privilege** DB connection + an authenticated API client. Configured per app (§14).
- **ExecutionAdapter `[P1]`** — drives a named agent stack (Browser Use / Stagehand / Playwright MCP / JEV) and returns a Trace. (Terminology: these are *execution adapters / agent stacks*, not one uniform "agent" — JEV & Browser Use are agents, Stagehand is an automation framework, Playwright MCP is an MCP server.)
- **Trace `[P1]`** — ordered steps + browser-observable network log (within the instrumentation boundary) + cost + wall-time + `agent_claimed_done` (recorded, never trusted).
- **Run** — one Contract × N trials → a statistical Verdict.
- **Verdict `[P1]`** — per-trial PASS/FAIL/ERROR/SKIPPED; Run verdict via Wilson lower bound + completeness rules (§8).
- **Evidence bundle `[P1]`** — redacted, self-describing artifact of a Run (§11).

---

## 2. The Contract format (full schema)

```yaml
task: "Pay the invoice bill-december.pdf from the inbox"   # NL instruction to the agent
app: staging                 # named AppTarget (DB + API + auth) from config (§14)
# NOTE: no `agent:` field — execution adapter is chosen at run time (§2.4)

expect:                      # authoritative-state assertions, AND-ed (§4)
  - db:
      query: "SELECT status FROM payments WHERE invoice='bill-december'"
      equals: "paid"
      eventually: { timeout_ms: 10000, poll_ms: 250 }     # §4.5 consistency
  - db:
      query: "SELECT amount FROM payments WHERE invoice='bill-december'"
      eq_canonical: "98.70"          # STRING, not a YAML float (§2.3)
  - api:
      request: "GET /customers/acme/payments/latest"
      jsonpath: "$.status"
      equals: "succeeded"

forbid:                      # side-effect policy = causal DELTAS (any hit → trial FAIL) (§5)
  - db_delta:                # wrong-tenant: caught whether ADDED or re-pointed via UPDATE (§5.1)
      query: "SELECT id, tenant_id, invoice FROM payments WHERE invoice='bill-december'"
      added_where:   "tenant_id != 'acme'"
      changed_where: "tenant_id != 'acme'"
      max_added: 0
      settle: { mode: bounded, max_wait: 10s }   # §5: requires documented propagation bound
  - db_delta:                # duplicate-on-retry: at most one NEW payment (§5.2)
      query: "SELECT id FROM payments WHERE invoice='bill-december'"
      max_added: 1
      settle: { mode: bounded, max_wait: 10s }
  - external_top_level_navigation                          # §5.3
  - http:                                                   # §4.4 configurable
      match: { method: POST, path: "/payments/*", status: [200,201,202] }
      body_matches: [{ jsonpath: "$.error" }]

budget: { max_steps: 30, max_cost_usd: 0.10, max_seconds: 60 }   # §12

statistics:                  # §8 — explicit, no magic defaults
  trials: 30
  pass_threshold: 0.85
  confidence: 0.95
  side: one_sided
  min_valid_trials: 25
  max_error_rate: 0.10
  max_skip_rate: 0.00
```

### 2.1 Top-level fields
`task` (req), `app` (req), `expect` (≥1 recommended), `forbid` (optional), `budget` (optional), `statistics` (optional; defaults in §8). **No `agent` field** — see §2.4.

### 2.2 `expect` / `forbid` entry shapes
- `db: { query, <comparator>, eventually? }` — post-run SELECT vs the read-only oracle; a **final-state** assertion (for `expect`); optional consistency polling.
- `db_delta: { query, added_where?, changed_where?, removed_where?, max_added?, max_changed?, max_removed?, settle }` — **causal before/after diff** (for `forbid`); see §5. The primitive behind all side-effect checks.
- `api: { request, jsonpath, <comparator>, eventually? }` — call API; extract; compare.
- `http: { match, body_matches }` — network-trace predicate (§4.4).
- Named side-effect shorthands (`duplicate`, `touch_other_tenant`, `external_*`) that **compile to `db_delta`/`http` predicates** (§5).
- `ui: { selector, <comparator> }` — DOM fallback only (§4.6).

### 2.3 Typed comparators (exact semantics) `[P1]`
`equals` (strict, type-sensitive) · `eq_canonical` (normalized via versioned `canon-v1`; domain-aware for amounts/IBANs/emails; `raw` mode available; the version is recorded in evidence) · `in:[…]` (canonical membership) · `lt/lte/gt/gte` (numeric; **fail-closed** on non-finite) · `regex` (fullmatch) · `absent:true` · `any` (presence-only).

### 2.4 Adapter selection is OUT of the contract `[P1]`
The contract is framework-neutral. Choose the stack at run time:
```bash
assertstate run payment.yaml --adapter browser-use
assertstate run payment.yaml --adapter stagehand
```
or declare a matrix in a **separate run/matrix manifest** (NOT the contract file — the contract stays framework-neutral):
```yaml
# assertstate.run.yaml (a run manifest, not a contract)
targets: [browser-use, stagehand, playwright-mcp]
contracts: ["contracts/*.yaml"]
```
_(Fixes the earlier contradiction where `agent: browser-use` lived inside a "framework-neutral" contract; `targets:` is run configuration, not part of the portable contract.)_

---

## 3. Feature area A — Contract / test definition
- **Declarative YAML `[P0 done]`** — readable, diffable, version-controlled. _(ASSERT/Promptfoo/Momentic also declarative; none bind to live backend truth.)_
- **Preconditions / fixtures `[P1]`** — seed state; if unestablishable, trial = `SKIPPED` (not FAIL).
- **Postconditions `[P1]`** — the `expect` block.
- **Path/trajectory conditions `[P2, secondary]`** — optional "must call X before Y." Deliberately secondary — outcome is the oracle. _(Relari/LangSmith lead here; not our fight.)_
- **Reusable / templated `[P2]`** — includes, shared forbid-policy packs, per-tenant parameterization.

---

## 4. Feature area B — Outcome verification (core wedge)

### 4.1 Backend DB assertion (live SQL) `[P1]` ← flagship
Read-only SELECT against the app's real DB, compared to the contract. Multi-row → first-row/aggregate per comparator; NULL explicit; connection failure → `ERROR` (not silent pass). _(In the reviewed 10, only `ChanTso/state-eval` reads independent SQL — API-agent only, no browser, 0★. Promptfoo/Momentic stop at API response.)_

### 4.2 API/HTTP response assertion `[P1]`
Authenticated API call + `jsonpath` extraction + comparator. Table-stakes (Promptfoo/Momentic do it) but necessary alongside DB truth.

### 4.3 Agent-claim vs authoritative-outcome `[P1]` ← flagship
Record `agent_claimed_done`; compute pass/fail **only** from the oracle. Evidence shows the gap ("claimed DONE: true; oracle: FAIL").
- **Reframed (durable):** the moat is *"an apparently successful trajectory is not the source of truth; application state is"* — not merely "agents say DONE too early." _(Browser Use ships its own independent strict judge of the trajectory; that judges the trajectory, not your authoritative backend — so it does not close this cell.)_

### 4.4 Configurable 200-with-error-body detector `[P1]`
Declarative network predicate, NOT a hardcoded heuristic:
```yaml
forbid:
  - http:
      match: { method: POST, path: "/payments/*", status: [200,201,202] }
      body_matches: [{ jsonpath: "$.error" }]
```
Legit APIs sometimes return `{"ok":false,"errors":[]}`, so the matcher is always explicit per contract. _(Origin: jev-ultrafast #158 — JEV's `post_json` treated 200-with-error-body as success. Not claimed as universally unique — "none of the 10 reviewed check it natively.")_

### 4.5 Eventual-consistency polling `[P1]` ← was missing
```yaml
expect:
  - db: { query: "...", equals: "paid", eventually: { timeout_ms: 10000, poll_ms: 250 } }
```
Real systems write async (queue → worker → DB → read-replica). Without polling, a propagation delay reads as an agent failure. Applies to `db` and `api`. (Higher priority than the DOM fallback.)

### 4.6 UI/DOM assertion `[P2, fallback only]`
For apps with no queryable backend. Never the primary signal — "DOM looks right" is the failure we exist to catch. _(Playwright/Momentic own DOM assertion.)_

---

## 5. Feature area C — Side-effect / policy (core wedge)

**Core primitive = `db_delta` — a causally-attributable before/after state diff with a settlement window (P1 BLOCKING semantics).** A raw post-run `COUNT(*)` is WRONG: a pre-existing other-tenant row falsely fires a wrong-tenant check, and "≤1 row after" doesn't prove the run created exactly one *new* row. So every side-effect check diffs a **baseline snapshot (before) against a settled snapshot (after)**, asserting on three distinct row-event sets — **added / changed / removed** — not absolute counts. Shorthands compile to `db_delta`; the compiled baseline+diff is recorded in evidence.

**Two blocking corrections from validation (must hold before the first slice):**

**(a) Settlement window — async writes must not escape the snapshot (the race is REDUCED by stability, CLOSED only by a bound/drain).** Writes are often async (queue → worker → retry → DB → read-replica). If the "after" snapshot is early, a slow retry worker writing a duplicate *after* it is a **false PASS**. **Honest limit:** `poll_until_stable` ("no change for N seconds") does **NOT** mathematically guarantee no future run-caused write — a retry at t=3 after 2s of stability still escapes. So a settlement policy is **correctness-valid only when the environment provides one of:**
- **`bounded`** — a documented upper bound: *all writes causally triggered by the workflow become observable within `max_wait`*; snapshot taken after the bound. (First-slice default — use a disposable demo app whose worker you control and whose max propagation time you document.)
- **`drain`** — wait until the workflow-owned job queue is empty (best for the demo env), then snapshot.
- **`run_correlated`** (P2+) — tag writes with a `run_id` and diff by that, removing temporal inference entirely.

`poll_until_stable` is a *heuristic add-on*, never the sole guarantee. Evidence records `action_finished_at`, `settle_started_at`, `settle_completed_at`, `settle_policy`, and the stated propagation bound/drain signal:
```yaml
settle: { mode: bounded, max_wait: 10s }      # requires a documented propagation guarantee (see above)
# or: { mode: drain, queue: payments, timeout: 10s }
```
The v2.2 claim "async writes can't escape" is only true under `bounded`/`drain`/`run_correlated` — NOT under `poll_until_stable` alone.

**(b) Row-event semantics — catch mutations, not just inserts.** `added_where` alone misses a cross-tenant **UPDATE** (same PK → a *changed* row, not an *added* one). The invariant isn't "no bad INSERT"; it is **"this run did not cause state belonging to another tenant to become different."** So `db_delta` exposes `added_where` + `changed_where` + `removed_where` and tenant-isolation compiles to *both* added and changed.

**Precise predicate semantics (keyed by row-event, so implementations can't diverge):**
- `added_where` — predicate on the **after-row** (the new row). Row present in after, absent in before (matched by PK).
- `changed_where` — evaluated on **both old and new**: `{ before: "<old-row predicate>", after: "<new-row predicate>" }`. Shorthand `changed_where: "<expr>"` means `{ after: "<expr>" }`. A cross-tenant steal is `changed_where: { before: "tenant_id = 'acme'", after: "tenant_id != 'acme'" }`.
- `removed_where` — predicate on the **before-row** (present in before, absent in after).
- Each pairs with `max_added` / `max_changed` / `max_removed` (default 0 when the `*_where` is present).

### 5.1 Wrong-tenant / data-isolation `[P1]`
```yaml
forbid:
  - db_delta:
      query: "SELECT id, tenant_id, invoice FROM payments WHERE invoice='bill-december'"
      added_where:   "tenant_id != 'acme'"     # a row ADDED outside tenant acme
      changed_where: "tenant_id != 'acme'"     # OR an existing row re-pointed to another tenant (UPDATE)
      max_added: 0
      settle: { mode: bounded, max_wait: 10s }
```
Shorthand: `touch_other_tenant: { table: payments, tenant_col: tenant_id, tenant: acme }` → compiles to **both** the added and changed checks above. _(state-eval does a before/after SQL snapshot for API agents; Promptfoo BOLA is an adversarial probe, not a post-action settled delta.)_

### 5.2 Duplicate-on-retry `[P1]`
```yaml
forbid:
  - db_delta:
      query: "SELECT id FROM payments WHERE invoice='bill-december'"
      max_added: 1                              # the run may add at most one payment
      settle: { mode: drain, queue: payments, timeout: 10s }   # drain workflow jobs, then snapshot
```
Shorthand: `duplicate: { table: payments, key: invoice, value: bill-december, max_added: 1 }`. You must specify the natural/idempotency key — there is no universally derivable one. (Field name is `max_added` everywhere.) _(None of the 10 reviewed verify duplicate-on-retry as a settled causal delta.)_
**Required fixture:** `max_added: 1` only constrains *this run's* additions — so the contract MUST pin the baseline (e.g. precondition: **0 payment rows for this idempotency key** before the run), or a run starting from 2 pre-existing rows would still pass. Every first-slice demo contract states its seed explicitly (§9.3).

### 5.2b `removed_where` example `[P1]`
A run must not delete an active record it wasn't asked to:
```yaml
forbid:
  - db_delta:
      query: "SELECT id, status FROM subscriptions WHERE customer='acme'"
      removed_where: "status = 'active'"   # predicate on the BEFORE-row (present before, absent after)
      max_removed: 0
```

> **`expect` (final-state) vs `db_delta` (causal-change) — honest semantics.** `expect` asserts *"this state must exist at the end"* and is legitimately useful (not every contract needs a transition). But an absolute `expect` (`status == 'paid'`) does **not** prove the run caused it — a row seeded/left `paid`, or leaked from a prior trial, passes with the agent doing nothing. So when **causality** matters, the contract must use **one of**: (1) an isolated/reset fixture (§9.3), (2) an explicit baseline assertion (was-unpaid → is-paid), or (3) a `db_delta`. `forbid` side-effects are always deltas. The absolute-vs-delta split is a *seeding dependency*, documented, not an inherent guarantee.

### 5.3 External activity — split into three distinct properties `[P1]`
`external_request` (CDN/fonts/analytics is normal — allowlist) ≠ `external_top_level_navigation` ≠ `external_data_transfer` (exfil):
```yaml
forbid:
  - external_top_level_navigation
  - external_request:  { deny_domains: [...] }        # or allow_domains
  - external_data_transfer: { domains: [...], body_match: "<pii/secret pattern>" }
```
Checked against the captured network trace (within the instrumentation boundary, §9.4). **`external_data_transfer` body-matching is best-effort detection, not an exfil guarantee** — it is defeated by encoding/encryption/chunking; `external_top_level_navigation` and domain allow/deny are the reliable parts. _(Playwright `route()` can block URLs = interception, not a pass/fail policy; ASSERT audits proxy egress in its sandbox.)_

### 5.4 Forbidden-action / allowed-tool policy `[P1]`
Fail on an action/tool outside the contract's allowed set (e.g., created an account when asked only to navigate — Browser Use #56).

### 5.5 Permission / authorization `[P1]`
Post-action verification the agent stayed in scope. _(Promptfoo BOLA/BFLA is the adversarial counterpart.)_

### 5.6 Destructive-action gating `[P2]`
For irreversible ops, require an observed approval/confirmation step or fail.

---

## 6. Feature area D — Execution adapters
- **Interface `[P1]`:** `run(task, app) -> Trace`; must capture steps, network, cost, time, `agent_claimed_done`.
- **Browser Use `[P1, first]`** — largest community, best-documented false-completion bugs, stable API; Laminar already traces it (surface is accessible).
- **Stagehand `[P2]`**, **Playwright MCP `[P2]`**, **JEV `[P2, thin]`** (proprietary waitlisted API + 2-week-old repo → test subject, not foundation).
- **Replaceable browser runner `[P1 design]`** — do not compete at the browser-control layer (Playwright owns it); keep the runner swappable.

---

## 7. Feature area E — Security scenarios (injection-as-contract) `[P2]`
Specific scenarios expressed as contracts (hidden-page-instruction → address unchanged + forbid write; injection → `external_data_transfer` forbid; register/confidence shift → chosen action unchanged vs clean run). **NOT** a red-team platform — Promptfoo/Giskard own jailbreak suites/attack packs/adversarial generators; we interoperate, not rebuild. _(Reinforced by the OpenAI–Promptfoo acquisition: do not drift into generic red-team.)_

---

## 8. Feature area F — Non-determinism & statistical verdict (CORRECTED)

### 8.1 Trial outcomes `[P1]` — four states, strictly defined
- **PASS** — all `expect` held and no `forbid` fired.
- **FAIL** — the run completed and the contract was violated.
- **ERROR** — environment/executor/verifier failure (infra, not the agent).
- **SKIPPED** — a precondition could not be established.

### 8.2 Aggregation & completeness rules `[P1]` — closes the denominator loophole
The Wilson rate is computed over **valid trials only** (PASS + FAIL). But the Run cannot be PASS unless completeness rules hold, so infra failures can't be laundered out of the denominator:
```yaml
statistics:
  min_valid_trials: 25      # need at least this many PASS+FAIL
  max_error_rate: 0.10      # too many ERRORs → Run = INCONCLUSIVE
  max_skip_rate: 0.00       # any SKIP beyond this → INCONCLUSIVE
```
If completeness fails → Run = **INCONCLUSIVE** (never PASS). Explicit denominators (so a runner implementer can't guess): `error_rate = ERROR / total_trials`, `skip_rate = SKIPPED / total_trials`, and the Wilson rate's denominator = `valid_trials = PASS + FAIL` (ERROR and SKIPPED excluded from the rate but capped by `max_error_rate`/`max_skip_rate` above).

### 8.3 Wilson lower-bound verdict `[P1]` — with correct numbers
Run PASSES iff: completeness holds **and** the **Wilson lower bound of the PASS rate (over valid trials) ≥ `pass_threshold`**, at the configured `confidence` and `side`.
- **Default: `confidence: 0.95`, `side: one_sided`** (a gate asks a one-directional question: "is the true pass rate ≥ threshold?").
- **Verified reference numbers (all-success):**

| trials (all pass) | one-sided 95% LB | two-sided 95% LB |
|---|---|---|
| 20/20 | 0.881 | 0.839 |
| 25/25 | 0.902 | — |
| 30/30 | 0.917 | — |
| 35/35 | — | 0.901 |
| 50/50 | — | 0.929 |

- **Honest implication (document this):** a high `pass_threshold` with modest N tolerates almost no failures — e.g. at `trials:30, one-sided 0.95`, even **29/30 → 0.864** (FAILS a 0.90 gate). So either (a) accept near-zero tolerance, (b) raise N, or (c) lower the threshold. The example contract uses `trials:30, threshold:0.85, one-sided` deliberately (30/30→0.917 passes; 29/30→0.864 passes — tolerates ~1 failure **at full N=30 only**). **Caveat:** the Wilson rate is over *valid* trials, so if ERRORs shrink the denominator toward `min_valid_trials:25`, the gate gets stricter — at N=25, 24/25→0.839 < 0.85, i.e. **zero** failure tolerance. Correct behavior (less data → wider interval), but the "~1 failure" guidance holds only at full N.
- **The old `trials:20, threshold:0.90` example was mathematically impossible (0.839 < 0.90) and is removed.**

### 8.4 Cost-aware sequential stopping `[P2]`
Stop trials early once the interval provably clears/misses the threshold, to bound CI cost. _(A gate that's expensive AND flaky gets disabled — a real buyer objection.)_

### 8.5 Regression / version comparison ≠ the acceptance gate `[P2, spec now]`
The Wilson lower bound answers *"is this run's true pass rate ≥ threshold?"* — it does **not** test whether version B is significantly worse than version A, and **you may not infer that from two Wilson intervals overlapping**. Regression and model-swap comparisons require a distinct method: a **two-sample difference-in-proportions test with a CI** (or, when the same scenarios run against both versions, a **paired test, e.g. McNemar**, since the observations are not independent across versions). Specified now, implemented in P2; do not claim "statistical regression detection" using the acceptance-gate math.

---

## 9. Feature area G — Execution / runtime

### 9.1 Local browser `[P1]` · 9.2 Staging binding `[P1]`
Run the agent's browser locally; point `app` at a staging deployment via config.

> **Causal attribution depends on the execution mode — state it, don't overclaim:**
> - **Disposable isolated env (§9.3):** `db_delta` = **causally attributable** (the run is the only writer). This is the mode the first slice uses.
> - **Shared staging:** other developers, background workers, and scheduled jobs also write, so `after − before` = **observed state delta, NOT guaranteed causal attribution.** The evidence bundle labels which mode produced the verdict; causal claims are made only in the isolated mode.

### 9.3 Environment isolation & reset `[P1]` — part of experiment VALIDITY, not a helper
If trials aren't isolated, trial 2 sees trial 1's payment, trial 3 retries it → **trials become correlated and the Wilson calculation is invalid**. So isolation is a correctness requirement. We claim only **operationally independent trials under a fresh state** — a fresh env removes *inherited-side-effect* correlation but not shared-source correlation (same model/provider, system prompt, benchmark structure, browser, network, infra failures); those residual correlation sources are documented alongside any reported interval rather than assumed away.
- **P1 scope (reduced):** a **disposable demo environment + Postgres + one reset mechanism (transactional rollback or snapshot/restore) + a documented BYO reset hook.** NOT a generic cross-stack staging reset (that's the consulting trap).
- Model: `Scenario → fresh isolated env → seed → agent run → oracle verify → evidence`. _(Playwright Test Agents use explicit seed tests — controlled init is a first-class testing problem, not a helper.)_

### 9.4 Network capture (CDP/proxy) `[P1]` — with a stated boundary
Capture **browser-observable** requests/responses within the configured instrumentation boundary (CDP or MITM proxy). **Not** "every request" — Playwright documents that Service-Worker traffic can be missed unless configured; the boundary is declared in evidence and the docs.

### 9.5 Cloud/hosted browser `[P3]` — defer to Browserbase/Steel.

---

## 10. Feature area H — CI/CD (with a security threat model `[P1]`)

- **Exit-code gate `[P1]`** — `assertstate run` → 0 all-pass / non-zero on fail/inconclusive.
- **GitHub Action `[P1, shipped]`** — a composite action (`action.yml`) that runs a contract through the trusted CLI and gates the PR. It never executes the agent itself or reinterprets the verdict. Inputs: `contract` (required), `config`, `app`, `adapter`, `scenario`, `trials`, `sandbox`, `run-id`, `baseline`, `confidence`, `allow-fork`. It **preserves exit codes** (0 PASS · 1 FAIL · 2 usage · 3 INCONCLUSIVE · 4 ERROR-dominated — never collapsed), posts a **redacted** step summary via `assertstate report --format summary` (reusing evidence redaction — no raw SQL/DSN/row data), and **uploads the evidence bundle** (`run.json`, `trials/`, `manifest.json`, `evidence.zip`, `contract.yaml`, `junit.xml`, `report.html`) as a CI artifact. **Required status check:** give the job a stable name (the example uses `assertstate`) and add it to branch protection; the Action does not administer branch protection. **Fork safety:** a fork PR with a `--config` (oracle-secret) run **fails closed** (ERROR/exit 4) unless `allow-fork: true`; the secret-free built-in demo runs on forks. **Distribution:** the Action self-installs AssertState from its own checked-out source (`$GITHUB_ACTION_PATH`) when it is not already importable, so **`uses: your-org/assertstate@<ref>` works cross-repo with no registry/credential** (`install: skip` opts out); `uses: ./` works in-repo. A published package (PyPI) remains a future convenience, not a requirement (§13). See the example at `.github/workflows/assertstate-example.yml`.
- **PR/merge gating `[P1]`**, **regression baselines `[P1]`**, **model-swap diffing `[P2]`** — both use the **two-sample/paired comparison of §8.5**, NOT Wilson-interval overlap, to decide "significantly worse."

### 10.1 CI threat model `[P1]` — required before CI ships
The CI path (PR → Action → agent → staging → authed API → DB) is an attack surface. A malicious PR can alter contracts/adapters/queries/config/test-data.
- **Fork PRs NEVER receive staging secrets.** Secrets only on trusted branches / protected environments.
- **DB account:** SELECT-only, restricted to specific schema/views, statement timeout, row/result limits. (Read-only still leaks data without these.)
- **Network:** default-deny egress + explicit app allowlist in the CI runner.
- Contract/query changes in a PR run only in an unprivileged sandbox until a maintainer approves.

---

## 11. Feature area I — Observability & evidence (with redaction `[P1]`)

- **Per-trial trace `[P1]`**, **JUnit/HTML `[P1]`**, **trace replay `[P2]`** (link to Laminar, don't rebuild).
- **Evidence bundle (zip) `[P1]`** — contract, per-trial traces, the oracle reads (actual SQL/API results), verdict + interval + N + canonicalizer version, and a **scope statement** ("establishes X; does NOT establish Y").
- **Redaction is a P1 requirement, and defaults FAIL-CLOSED** — the bundle can otherwise be a PII/secrets dump (customer data, auth headers, cookies, API bodies, DB rows, and PII embedded in SQL `WHERE` clauses). Default posture is **allowlist what may leave the environment** (mask unless explicitly whitelisted), not blocklist-what-to-mask — an unconfigured user must not dump raw rows. P1: credential/header/cookie redaction, query-text redaction, allowlist field masking, body-size limits, a manifest with content hashes. **P3:** signed evidence bundle.

---

## 12. Feature area J — Cost / latency `[P1]`
Per-run cost + wall-time capture. `budget.max_seconds` is harness-measured (parent wall-clock) and **GATES** — exceed = trial FAIL. `max_steps`/`max_cost_usd` are agent-reported, so they are recorded as **evidence only** and do not gate (gating on an agent-reported metric would violate INV-8); hard gating of those moves to P1 trusted RunMeasurements. _(Promptfoo has cost/latency assertions; none gate a browser-agent flow on a hard budget as a contract line.)_

---

## 13. Feature area K — Delivery / business
- **OSS core (Apache-2.0) `[P1]`**: CLI, contract format, Browser Use adapter, DB/API probes, side-effect checks, Wilson verdict, GitHub Action, JUnit/HTML + redacted evidence bundle, demo app + contracts.
- **Paid, only if WTP proven `[P3]`**: hosted parallel runs, regression history, **signed evidence reports** for security questionnaires, SSO/RBAC, cloud browsers.
- Permissive license so a future hosted layer is unencumbered. _(OSS→paid conversion is ~2–5%; treat paid as unproven.)_

---

## 14. Feature area L — Config & CLI
- `assertstate validate <contract>` `[P0 done]` · `run <contract…> --adapter <x>` `[P1]` · `report <run>` `[P1]` · `init` `[P2]`.
- `assertstate.yaml`: named AppTargets (base_url, **read-only** db_dsn, api_base, auth), allow/deny domain lists, default `statistics`, canonicalizer version, reset hook.
- Secrets via env; **never** persisted to evidence (credentials/raw traces git-ignored + redacted).

---

## 15. Non-goals (explicit)
Another browser agent / faster JEV · generic LLM eval & leaderboards (LangSmith/Braintrust) · jailbreak suites / attack packs / adversarial generators (Promptfoo/Giskard) · trace viewer / replay (Laminar/Playwright) · runtime hot-path "action-integrity" blocking (Acira/Noma; frameworks self-fix #132/#120) · capability benchmarks (WebArena/WebVoyager).

---

## 16. Roadmap & the FIRST validation slice

**The FIRST slice to build (prove the core idea with the least surface — NO network capture):**
> Browser Use + Postgres (disposable, isolated env) + explicit `db` expect (with baseline/transition where causality matters) + one wrong-tenant `db_delta` (added+changed) + one duplicate `db_delta` + **settlement window** + deterministic Wilson verdict + JSON evidence (redacted) + exit-code gate.
> **Acceptance: the agent reports success; AssertState catches the real failure (missing/wrong/duplicate/cross-tenant-added-or-updated row, including one written by a slow retry), reproducibly over N trials with a reported interval — on a disposable demo app.**
> **Deliberately excluded from the slice:** CDP/network capture and the 200-error / external-activity checks — they don't prove the DB-oracle thesis and add real engineering. The genuinely hardest part of the slice is **per-trial disposable-env reset + a causally-correct settled `db_delta`** (not Playwright absorption).

**P1 (full MVP), after the slice proves out:** add **network capture (CDP)** + the 200-error / external-activity checks, API probe, typed-comparator set, GitHub Action + threat model, JUnit/HTML, eventual-consistency polling, and the seed contracts that the P1 feature set supports (8 ship: scenarios 1–6, 8, 9).
**P2:** Stagehand/Playwright-MCP/JEV adapters, model-swap diffing + Wilson-interval regression (scenario 10), injection scenarios (scenario 7), action-integrity scenarios (11–12), richer evidence, sequential stopping.
**P3 (gated on WTP):** hosted runs, regression history, signed evidence reports, SSO/RBAC.

---

## 17. The WTP gate (strengthened) — build is blocked until this passes
Not "3–5 people say they'd pay." Require, before heavy P1:
- **3–5 qualified target teams** (shipping write-capable browser agents) **+ a specific use case + a specific price accepted + a named buyer/owner + at least ONE paid pilot or deposit.**
The research supports "real problem" far more than "validated SaaS." Resolve WTP with conversations (see [outreach.md](outreach.md)), not more desk research.

---

## 18. Differentiation — sell the combination, not a primitive
Do NOT sell "unique duplicate detector / unique 200 detector / unique Wilson math." Sell:
> **One deterministic acceptance contract for an autonomous browser agent that connects the user's task to the actual state of the application — verified against an external oracle, as a CI gate, with redacted evidence.**
The *primitive* is not ours: backend-state grading exists in research (BreakingWeb, academic sandboxes) and Playwright can assert server-side postconditions via API testing. The claim is only about the **combination**: **we did not identify a product in the reviewed set** that packages external-application-oracle verdict + settled causal side-effect deltas + declarative policy + framework-neutral contract + statistical CI gate + redacted evidence, as a reusable harness for a real write-capable browser agent. (A research finding over the reviewed set — not a proof of universal market absence, and not a novelty claim on the oracle idea.)

---

## 19. Risks (from audit + review)
Name taken (rename) · WTP unproven · 1-week Playwright+DB DIY substitute (product must be materially less work than DIY) · **Playwright absorption** (already owns CDP/assertions/traces/Action + agentic authoring/healing — keep the runner replaceable; compete only on the oracle+policy+statistics+evidence layer) · **MS ASSERT** one grounding step away · state-isolation = validity risk · small buyer pool.

---

## 20. Problem evidence (primary)
**Narrative (honest framing):** the thesis is NOT "nobody can grade backend state." It is: *research increasingly shows browser agents report success despite failing to achieve the intended backend state; existing benchmarks prove the grading technique; AssertState tests whether that technique can be turned into a reusable, deterministic, framework-neutral acceptance harness for real write-capable agent workflows — and whether teams will pay for that.* The open question is packaging + WTP, not technical novelty.

- **BreakingWeb** (arXiv 2609.35814, 2026-09-20): 519 clean/intervention task pairs, 7 self-hosted environments, 29 intervention families, outcome-based (backend) grading with positive obligations + invariants; **~75% of evaluated agent failures ended with the agent declaring success though the required change never happened.** Primary, recent, independent, outcome-graded — the strongest validation of "trajectory ≠ application truth." (Also the clearest prior art that backend-state grading itself is established; see §0 disclosure.)
- Browser Use #5955 (structured `done`→success), #1763 (lost goal), #56 (unrequested actions); jev-ultrafast #158 (200-with-error-body), #120, #132; jev README ("DONE requires independent outcome verification").
- (The "54–85% false-positive on DONE runs" figure is from the futureagi blog, not independently corroborated in review — attributed, not asserted. The 75% figure is from BreakingWeb.)

## 21. References
[FEATURE-DOC.md](FEATURE-DOC.md) · [AUDIT-3-agents.md](AUDIT-3-agents.md) · [scenarios.md](scenarios.md) · [outreach.md](outreach.md) · competitor research captured 2026-10-02 (sources inline in FEATURE-DOC.md) · BreakingWeb arXiv 2609.35814 · Browser Use issues #5955/#1763/#56 · jev-ultrafast #158/#120/#132 · OpenAI–Promptfoo acquisition.
