-- AssertState P0 demo application schema (DEVELOPMENT.md §19).
-- A deliberately tiny disposable payment app. It is a TEST FIXTURE, not a product.

CREATE TABLE tenants (
    id text PRIMARY KEY
);

-- Schema matches frozen DEVELOPMENT §19. `idempotency_key` is populated = invoice in the
-- demo (DEVELOPMENT §19: "idempotency_key = invoice (demo)"); `invoice` is the natural key
-- used by the P0 contracts (one payment per invoice).
CREATE TABLE payments (
    id              bigserial PRIMARY KEY,
    invoice         text NOT NULL,
    tenant_id       text NOT NULL REFERENCES tenants(id),
    amount          numeric(12, 2),
    status          text,
    idempotency_key text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Controllable async retry worker queue (so `drain` has a real, observable queue).
CREATE TABLE payment_jobs (
    id            bigserial PRIMARY KEY,
    invoice       text NOT NULL,
    run_id        text NOT NULL,
    state         text NOT NULL DEFAULT 'queued',   -- queued | active | done
    process_after timestamptz NOT NULL DEFAULT now(),
    attempts      int NOT NULL DEFAULT 0
);

-- Drain observability (condition d): the oracle can see the last processed job for a run.
CREATE TABLE run_markers (
    run_id             text PRIMARY KEY,
    producers_closed   boolean NOT NULL DEFAULT false,
    last_processed_job bigint
);

-- Sentinel for the read-only probe (DEVELOPMENT.md §13): the oracle role has NO write grant
-- on this table, so an INSERT attempt must be rejected with "permission denied".
CREATE TABLE assertstate_readonly_probe (
    id text PRIMARY KEY
);
