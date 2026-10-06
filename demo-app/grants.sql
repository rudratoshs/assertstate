-- AssertState P0 oracle grants (DEVELOPMENT.md §13, §19).
-- Run inside the template DB, as the migrator/owner. The oracle role :oracle_role
-- gets SELECT on the app tables and NOTHING that can write — in particular NO
-- INSERT/UPDATE/DELETE on assertstate_readonly_probe, which makes the read-only
-- role-privilege probe (INSERT must be rejected) meaningful.

GRANT CONNECT ON DATABASE :"db_name" TO :"oracle_role";
GRANT USAGE ON SCHEMA public TO :"oracle_role";

-- Read-only on the application tables the oracle legitimately observes.
GRANT SELECT ON tenants, payments, payment_jobs, run_markers, approvals TO :"oracle_role";

-- Deliberately: NO grant of any kind on assertstate_readonly_probe to the oracle role.
-- (A fresh role has no privileges by default; we simply never grant them here.)

-- Defence in depth: force every session of this role to be read-only at the transaction level.
-- (The PRIMARY proof remains the absence of write privileges above, not this flag.)
ALTER ROLE :"oracle_role" SET default_transaction_read_only = on;
