# AssertState

**Verify what your browser agent *did* — not what it *said* it did.**

A browser agent reports `DONE`. Did the database row actually change to the right value?
Did it create a duplicate on retry, or touch a tenant it wasn't allowed to? AssertState
answers that from an **independent, read-only read of the application's own state** — the
ground truth the agent cannot see or fake — not from the agent's success claim.

> The frameworks already agree with the premise. jev-ultrafast's own README:
> *"A `DONE` choice still requires independent outcome verification."*

License: **Apache-2.0**.

> **Status (honest): P0 in progress — NOT done.** Implemented and tested against a real
> PostgreSQL: the contract loader/validator, the read-only oracle probe, snapshot
> fail-closed guards, and the `db_delta` diff + safe predicate engine. **Not yet built:**
> the demo worker, settlement/drain, the orchestrator, the verifier/statistics/evidence
> pipeline, and the out-of-process agent adapter. The canonical `assertstate run` command
> is therefore **not wired yet** (it exits non-zero and says so). See
> [docs/P0-IMPLEMENTATION-BACKLOG.md](docs/P0-IMPLEMENTATION-BACKLOG.md) for exactly what
> is and isn't done, and the per-task status.

---

## Source of truth

The design is frozen across three documents; code is subordinate to them:

1. [docs/FEATURE-SPEC.md](docs/FEATURE-SPEC.md) (v2.3) — product behavior & contract semantics
2. [docs/SYSTEM-DESIGN.md](docs/SYSTEM-DESIGN.md) (v2.2) — architecture, trust model, lifecycle
3. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) (v1.1) — the P0 implementation blueprint
4. [docs/P0-IMPLEMENTATION-BACKLOG.md](docs/P0-IMPLEMENTATION-BACKLOG.md) — the executable task list

## Contract format (P0, FEATURE-SPEC v2.3)

The contract is **framework-neutral** (no `agent:` field — the adapter is chosen at run
time). Money literals are strings. Side-effects are causal `db_delta` diffs with a
settlement policy (`drain` in P0). See [contracts/pay-invoice.p0.yaml](contracts/pay-invoice.p0.yaml):

```yaml
task: "Pay the invoice in bill-december.pdf from the inbox"
app: demo

expect:                       # authoritative final-state reads
  - db: { query: "SELECT status FROM payments WHERE invoice='bill-december'", equals: "paid" }
  - db: { query: "SELECT amount  FROM payments WHERE invoice='bill-december'", eq_canonical: "98.70" }

forbid:                       # causal before/after deltas (any hit -> FAIL)
  - db_delta:                 # wrong-tenant, caught as ADDED or re-pointed via UPDATE
      query: "SELECT id, tenant_id, invoice FROM payments WHERE invoice='bill-december'"
      added_where:   "tenant_id != 'acme'"
      changed_where: { before: "tenant_id = 'acme'", after: "tenant_id != 'acme'" }
      max_added: 0
      settle: { mode: drain, queue: payments, timeout: 10s }
  - db_delta:                 # duplicate-on-retry: at most one NEW payment
      query: "SELECT id FROM payments WHERE invoice='bill-december'"
      max_added: 1
      settle: { mode: drain, queue: payments, timeout: 10s }

budget: { max_steps: 30, max_cost_usd: "0.10", max_seconds: 60 }

statistics: { trials: 30, pass_threshold: 0.85, confidence: 0.95, side: one_sided,
              min_valid_trials: 25, max_error_rate: 0.10, max_skip_rate: 0.00 }
```

> A `db_delta` observes only the columns its query projects. The validator rejects a
> predicate that references a non-projected column (so predicate evaluation is never
> blind) and rejects volatile projections — but a count-only policy still sees only the
> projected columns, so project every column whose mutation matters (DEVELOPMENT §6.6/§17).

## Development / reproduce the tests

Requires Python ≥ 3.11. Integration tests need a local PostgreSQL (they **auto-skip**
if none is reachable); the unit tests need only the installed package.

```bash
# from this directory (agent-contracts/)
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e '.[dev]'          # installs psycopg, pytest, ruff, mypy

ruff check assertstate tests        # lint
mypy                                 # strict type-check
pytest -q                            # 45 unit + 10 integration (integration skip w/o Postgres)

assertstate validate contracts/pay-invoice.p0.yaml   # -> exit 0
```

**PostgreSQL for integration tests.** A local cluster reachable on the socket is enough;
the harness builds a disposable template DB and a read-only oracle role, then creates and
drops a fresh database per test. Override connection defaults via env (no machine-specific
values are baked in):

```bash
export ASSERTSTATE_PG_HOST=/tmp              # socket dir (default: /tmp)
export ASSERTSTATE_PG_ADMIN_USER=postgres    # migrator/superuser (default: your OS user)
```

## What it is NOT

Not another browser agent · not a capability benchmark or model leaderboard · not a
trace viewer (use Laminar) · not a generic prompt-injection scanner (use Promptfoo/PyRIT).
It is the layer the platforms structurally can't own: **your app's backend truth and
permission semantics.**

## Prior art (honest)

Backend-state grading of agent tasks is established (BreakingWeb; academic sandboxes;
Playwright API testing). AssertState's bet is the *productized combination* — external
oracle + settled causal deltas + framework-neutral contract + statistical CI gate +
redacted evidence — for a real write-capable browser agent. Whether teams pay for that is
being validated by conversations (see [docs/outreach.md](docs/outreach.md)), not by this README.
