# Four critical readiness controls: implementation and acceptance

**Status:** engineering changes in draft PR #8. These controls are not a
verified Level 3 public SaaS certification. A green CI run verifies only
the commit actually tested, and does not verify any live provider or
customer deployment.

## 1. Workflows and human approvals

- Execution uses topological graph order, validates DAGs, never infers a
  live tool from an untrusted node label, and treats unsupported tools as
  failures.
- Production workflow execution requires a client `Idempotency-Key`
  (8–128 letters, digits, hyphens or underscores). Runs have a unique
  `(business_id, idempotency_key)` database constraint, with a PostgreSQL
  advisory transaction lock around the first-use lookup and run creation.
  Retrying with the same key returns the same run; reusing it for a
  different workflow or dry-run mode is refused.
- The browser holds a pending key in memory across uncertain network/5xx
  outcomes, so a retry reuses the durable run record. Browser reloads do
  not retain those keys. Callers integrating directly must persist the
  key independently until they establish the result.
- Approval resume uses a one-time conditional DB claim and pins executable
  workflow definitions. The approval is committed before execution.
  **External side-effecting actions are not implemented.** The current
  registry performs reads, calculations, and local reminder drafting.
- Stale `running` records (5 minutes to 1 day old) can be quarantined
  by a founder-only `POST /api/workflows/runs/reconcile-interrupted`
  call. The operation never auto-replays unknown effects and always
  returns `automatic_replay: false`. A paused run requires manual review.
- Evidence: adversarial idempotency/recovery tests, approval replay tests,
  PostgreSQL cross-worker idempotent-execution and concurrent-approval
  races. **Limitation:** no proof of exactly-once effects across actual
  third-party side-effecting provider calls; those remain prohibited.

## 2. Financial correctness and source provenance

- MRR comes only from active customer records, recurring expense estimates
  from recognized billing periods, overdue balances from overdue invoice
  status, and cash from the business profile. One-off expenses are excluded
  from recurring burn.
- Unknown periods, missing/nonfinite/negative amounts and invalid overdue
  receivables are flagged in `financial_data_issues`. A partial snapshot
  has `financial_data_status=needs_review` and cannot produce runway
  health conclusions or an optimistic dashboard health score.
- Responses contain tenant-scoped contributing record IDs, source types,
  currency, update/generation timestamps and explicit
  `financial_data_verified=false` with `independent_ledger_reconciliation=false`.
  They do **not** claim audited cash balances, actual bank transactions,
  recognition of revenue under GAAP/IFRS, or verified ledger reconciliation.
- Council prompts identify invalid/unverified data and avoid numeric
  recommendations from incomplete inputs. Boundary and tenant isolation
  tests cover source IDs, annualization, expenses, negative/NaN values,
  invoice status and missing billing periods.
- **Limitation:** the underlying source records are self-maintained
  application data. Bank statements, invoice settlements, FX conversion,
  accounting period close and independent reconciliation are not integrated.
  Use explicit "unverified / user-recorded" labels in any investor pitch.

## 3. PostgreSQL backup and disaster recovery

- The disposable CI script `scripts/verify_postgres_restore.py` takes a
  `pg_dump --format=custom` snapshot, records its SHA-256 digest,
  verifies the manifest, restores to a newly created separate
  `oneboard_restore_ci` database, compares every application's table row
  digest and count, checks Alembic heads and schema constraints, then
  destroys **only** the database it created.
- Hard safety gates require localhost, `oneboard_ci`, matching
  `DATABASE_URL` and `ONEBOARD_TEST_POSTGRES_URL`, and an explicit
  `ONEBOARD_CI_DISPOSABLE_RESTORE=1` flag. Existing restore DBs are
  not overwritten. Tests reject remote/customer database URLs and
  corrupted archives.
- The disposable PostgreSQL CI job performs the drill after database
  migration, concurrency, and auth tests. No cloud account, customer data
  or live production backup is accessed or created.
- **Limitation:** a synthetic restore test is not an operational recovery
  service. The actual host's durable offsite retention, encryption at
  rest, access control, scheduled backups, key escrow, RPO/RTO, restore
  drills after disk loss and provider data-loss policy remain to be
  verified only after owner-approved hosting.

## 4. Production deployment security

- Application Host header and HTTPS scope checks fail closed. The
  `scripts/serve_secure_api.py` launcher binds only to loopback, disables
  reload, and trusts only explicitly allowlisted proxy IPs.
- Production settings forbid wildcard/CIDR proxy trust, unauthenticated
  demo mode, weak signing keys, insecure cookies, wildcard CORS and
  non-HTTPS public API origins. Remote PostgreSQL connections require
  `sslmode=verify-full` for certificate identity validation.
- Shared PostgreSQL throttles separately bound registration, account
  guessing and rotating-email password-hash abuse across workers.
- **Limitation:** there is no actual authorized hosted deployment to
  validate edge TLS certificates, routing isolation, proxy header
  overwriting, database network segmentation, logging, alerting,
  zero-cost provider lifecycle, or live availability. These are
  mandatory no-go checks for Level 3, not optional polish.

## CI evidence required before advancing

Run `python -m pytest -v`, disposable PostgreSQL integration and restore
verification, browser E2E, frontend TypeScript build and the real Ollama
smoke tests. Record the exact PR head and every GitHub Actions conclusion
in `TEST_REPORT.md`. The isolated browser inference experiment is not
a product architecture approval. Keep PR #8 draft and all seven issues
open until their full acceptance criteria are demonstrated. Do not merge,
spend money, enroll providers, use real customer data or deploy live
without explicit owner approval.
