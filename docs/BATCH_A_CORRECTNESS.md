# OneBoard Batch A: correctness and source-truth controls

Branch: draft PR #8. All changes use synthetic CI data only.

## Six repaired code-level defects

1. The operator-only encrypted restore drill now checks the current Alembic
   schema head 009, not obsolete 008. The PostgreSQL CI job additionally
   generates a temporary age key, encrypts a synthetic logical backup, then
   decrypts and restores into a new localhost scratch database with a schema
   assertion and cleanup. This is not proof of offsite production recovery.
2. Workflow approval UI consumes the already-resumed run returned by
   resolveApproval, never dispatches a second executeWorkflow call.
3. Operations UI uses real, tenant-owned commitments, customers and leads
   from GET /api/business/operations, not static demo delivery promises,
   client counts, fabricated stage labels or external GitHub actions.
4. The legacy /api/integrations/crm/contacts remains explicitly a demo-only
   object with a contacts array. The real Operations screen no longer
   assumes the object itself is an array, and has loading, failure and
   empty states.
5. Founder-submitted actual outcomes are now marked
   founder_reported_unverified; an exact existing prediction metric,
   finite number and bounded history are required. The service never
   auto-marks an outcome verified or increments empirical scorecards.
   Historical demo verification flags are suppressed from real API
   responses while no authenticated verification pipeline exists.
6. Unsupported adviser accuracy, evidence completeness, completion, and
   verified-outcome percentages now default to NULL and are withheld by
   the API even if old demo/legacy rows contain preset values. Confidence
   evidence defaults to user_statement with unknown confidence; new
   customer health has no fabricated default. UI no longer substitutes
   optimistic precision, counters or measured business outcomes.

## Tests and limits

- New synthetic adversarial regressions: tenant-scoped Operations sources,
  missing/invalid outcome prediction, NaN/infinity, no scorecard increment,
  no fabricated defaults, current revision restore guard, no duplicate
  workflow run from UI, and no fictitious UI records.
- New Playwright fresh-founder Operations journey, verifying empty
  commitments/customer/pipeline tabs without mock Northstar data.
- New disposable PostgreSQL age encrypt/decrypt/restore workflow. All
  tests run without approved providers, payments, live customer data or
  offsite storage.
- Source-backed customer and financial records are still USER-RECORDED,
  not independent bank or CRM verification. There is no real independent
  outcome reviewer, immutable cryptographic audit ledger, or production
  restore certification. No provider accounts, deployments, releases,
  merges, or external actions authorized.

Exact-head GitHub Actions remain the gate before Batch B or C: do not
proceed unless ALL applicable workflows finish completed/success.
