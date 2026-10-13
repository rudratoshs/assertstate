# AssertState

**Verify what your browser agent *did* — not what it *said* it did.**

A browser agent reports `DONE`. Did the database row actually change to the right value?
Did it create a duplicate on retry, or touch a tenant it wasn't allowed to? AssertState
answers that from an **independent, read-only read of the application's own state** — the
ground truth the agent cannot see or fake — not from the agent's success claim.

> The frameworks already agree with the premise. jev-ultrafast's own README:
> *"A `DONE` choice still requires independent outcome verification."*

License: **Apache-2.0**.

## See it catch a bug your eval passes (≤60s)

Needs a local PostgreSQL (the harness builds a disposable DB + a read-only oracle role).

```bash
uv venv --python 3.11 && source .venv/bin/activate && uv pip install -e '.[dev]'

assertstate run contracts/pay-invoice.e2e.yaml --app demo --scenario correct      # PASS, exit 0
assertstate run contracts/pay-invoice.e2e.yaml --app demo --scenario slow_retry   # FAIL, exit 1
```

In `slow_retry` the agent reports success and **every final-state check is green** — yet the
run **FAILs**: a slow retry worker committed a *second* payment **after** the agent "finished,"
caught only by the **settled** before/after DB delta. Your current eval passes this run; your
database has two charges. Open the `report.html` in the printed evidence dir to see it.

## What it is

A deterministic **acceptance harness** for autonomous browser agents. The PASS/FAIL verdict comes
**only** from independent trusted reads of the app's own state (DB / API / DOM) plus
settlement-aware causal side-effect deltas — **never** the agent's self-report (invariant INV-8).
The agent runs **out-of-process behind a trust boundary** (no oracle credentials, JSON-only IPC,
optional locked-down container), so it can neither read nor forge the evidence that judges it.

### Shipped
- **Contracts** — framework-neutral YAML: typed comparators, `expect` (db/api/ui), `forbid`
  side-effect policies, named shorthands (`duplicate`/`touch_other_tenant`/`destructive_action`),
  required orderings (`trajectory`), and reusable/templated contracts (`include` packs + `${params}`).
- **Oracles** — read-only DB (privilege-verified read-only), authenticated GET/HEAD API, and a
  trusted parent-side DOM probe (SSR + headless-Chrome render).
- **Side-effects** — causal `db_delta` with settlement: `drain`, `bounded` (trusted network anchor),
  and `run_correlated` (run-id-tagged); `external_*` / `http` policies over a trusted network
  capture; `destructive_action` approval gating. Settlement that can't be proven → ERROR, never a
  silent pass.
- **Statistical verdict** — four trial states (PASS/FAIL/ERROR/SKIPPED), completeness gating, a
  Wilson lower-bound acceptance gate, and regression comparison (`compare`: two-proportion, or
  `--paired` McNemar for a model/version swap) plus local pass-rate **history**.
- **CI** — a composite **GitHub Action** that runs the trusted CLI, preserves exit codes
  (0 PASS · 1 FAIL · 2 usage · 3 inconclusive · 4 error-dominated), posts a redacted summary, and
  uploads the evidence bundle. Fork PRs with secrets fail closed.
- **Evidence** — a per-run bundle (verdict, per-trial traces, JUnit/HTML, `contract.yaml`,
  SHA-256 manifest, zip) with **fail-closed allowlist redaction** (no raw SQL/DSN/row values by
  default).
- **Adapters** — a real Browser Use adapter (drives Chromium + an LLM) and a self-hosted
  **remote-CDP** adapter (attach to your own cloud browser); the runner is framework-neutral and
  swappable.

### Deferred (demand-driven, not needed to adopt)
Additional adapter stacks (Stagehand / Playwright-MCP / JEV) and cost-aware sequential stopping are
`[P2]` reach items. Hosted parallel runs, SSO/RBAC, signed evidence reports, and a managed
browser fleet are `[P3]`, built on real demand — the OSS engine above runs fully in your own CI.

## CLI

```
assertstate validate <contract>                         # structural + typed + semantic checks
assertstate run <contract> --app demo|bounded-demo      # built-in demo app
assertstate run <contract> --config assertstate.yaml --app <name> --adapter <x>   # a real app
assertstate report <run> --format json|junit|html|summary
assertstate compare <baseline> <candidate> [--paired]   # regression gate (exit 1 if worse)
assertstate history [--gate]                            # pass-rate trend + latest-vs-prior regression
assertstate matrix <manifest>                           # fan contracts × targets
assertstate init                                        # scaffold assertstate.yaml + a contract
```

Use it in CI with the bundled Action (self-installs from source; no registry needed):

```yaml
- uses: rudratoshs/assertstate@v1
  with:
    contract: contracts/pay-invoice.e2e.yaml
    app: demo
```

## Contract example

Framework-neutral (no `agent:` field — the adapter is chosen at run time). Money literals are
strings. Side-effects are causal `db_delta` diffs with a settlement policy. See
[contracts/pay-invoice.e2e.yaml](contracts/pay-invoice.e2e.yaml):

```yaml
task: "Pay the invoice in bill-december.pdf from the inbox"
app: demo

expect:                       # authoritative final-state reads
  - db: { query: "SELECT status FROM payments WHERE invoice='bill-december'", equals: "paid" }
  - db: { query: "SELECT amount  FROM payments WHERE invoice='bill-december'", eq_canonical: "98.70" }

forbid:                       # causal before/after deltas (any hit -> FAIL)
  - touch_other_tenant:       # a row added outside / re-pointed to another tenant
      table: payments
      tenant_col: tenant_id
      tenant: acme
      where: "invoice='bill-december'"
      settle: { mode: drain, queue: payment_jobs, timeout: 10s }
  - duplicate:                # at most one NEW payment for this invoice (retry-safety)
      table: payments
      key: invoice
      value: bill-december
      settle: { mode: drain, queue: payment_jobs, timeout: 10s }

statistics: { trials: 5, pass_threshold: 0.8, min_valid_trials: 5, max_error_rate: 0.2 }
```

> A `db_delta` observes only the columns its query projects. The validator rejects a predicate that
> references a non-projected column (so evaluation is never blind) and rejects volatile projections.

## Honest scope / caveats

- **HTTPS/CDP network capture** is not built — the trusted capture proxy is HTTP-only; for an
  HTTPS app the `http`/`external`/`trajectory` policies are **non-gating** (fail-closed), never a
  false pass.
- **`drain`** uses a demo-coupled queue probe; a real `--config` app that wants drain supplies its
  own queue-state probe.
- **`run_correlated`** attributes run-id-tagged INSERTs; a pre-existing row's UPDATE/DELETE needs the
  app to re-stamp the run id.
- **`destructive_action`** fires on an in-scope *removal* (delete / move-out-of-scope), not an
  in-place update.
- **Remote-CDP** attaches to an already-running browser, so it can't inject the capture proxy;
  capture there is operator-configured at the remote browser, else non-gating.

## Development / reproduce the tests

Requires Python ≥ 3.11. Integration tests need a local PostgreSQL (they **auto-skip** if none is
reachable); the INV-7 container tests need Docker (also auto-skip).

```bash
uv venv --python 3.11 && source .venv/bin/activate && uv pip install -e '.[dev]'

ruff check assertstate tests demo-app scripts   # lint
mypy assertstate                                 # strict type-check
pytest -q                                        # full suite (unit + integration + e2e + adversarial)
```

Override Postgres connection defaults via env (no machine-specific values are baked in):

```bash
export ASSERTSTATE_PG_HOST=/tmp              # socket dir (default: /tmp)
export ASSERTSTATE_PG_ADMIN_USER=postgres    # migrator/superuser (default: your OS user)
```

## Source of truth

The design is specified across [docs/FEATURE-SPEC.md](docs/FEATURE-SPEC.md) (product behaviour &
contract semantics), [docs/SYSTEM-DESIGN.md](docs/SYSTEM-DESIGN.md) (architecture, trust model), and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) (implementation). Code is subordinate to them.

## What it is NOT

Not another browser agent · not a capability benchmark or model leaderboard · not a trace viewer
(use Laminar) · not a generic prompt-injection scanner (use Promptfoo/PyRIT). It is the layer the
platforms structurally can't own: **your app's backend truth and permission semantics.**

## Prior art (honest)

Backend-state grading of agent tasks is established (BreakingWeb; academic sandboxes; Playwright API
testing). AssertState's bet is the *productized combination* — external oracle + settled causal
deltas + framework-neutral contract + statistical CI gate + redacted evidence — for a real
write-capable browser agent.

## How it compares

Most "agent verification" tooling checks the **security boundary** (was the agent jailbroken?
did data leave?). AssertState checks a different, complementary layer: **did the business outcome
actually happen correctly in *your* backend** — right value, exactly once, right tenant — read
independently from the app's own state.

| Tool | Layer it verifies | Checks *your* backend truth? |
|---|---|:--:|
| Promptfoo / PyRIT | prompt-level red-team (model jailbreak / injection) | — |
| [Pipelock](https://github.com/luckyPipewrench/pipelock) | egress firewall (did data leave the boundary?) | — |
| [RAMPART](https://github.com/microsoft/RAMPART) | pytest side-effect assertions (via adapter) | — |
| [OWASP ASRH](https://github.com/OWASP/Agent-Security-Regression-Harness) | tool-call assertions over a recorded trace | — |
| [agentverify](https://github.com/rudratoshs/agentverify) | boundary side-effect check (reference impl) | — |
| **AssertState** | **app DB / API / DOM state + settled causal deltas + permissions** | **✅** |

The security tools answer *"did the agent do something it shouldn't?"*. AssertState answers
*"did the agent do the thing it was asked to, correctly, exactly once, and only where allowed?"* —
verified against the ground truth the agent can't see or fake. They stack; they don't overlap.
