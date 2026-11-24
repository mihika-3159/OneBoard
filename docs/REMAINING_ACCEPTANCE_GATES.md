# Remaining production acceptance gates

Engineering batch: 24 November 2026, draft PR #8 only. The project is
NOT an independently certified production SaaS. No customer data, paid
provider, bank connection, deployment or external action is authorized.

## 1. Financial source verification

The founder-only POST /api/business/financial/reconcile compares a
256-KiB, 500-row maximum uploaded CSV against tenant-owned invoices,
expenses and business cash. Required headers:

    record_type,record_id,amount,currency,as_of

Amount must be finite, nonnegative and precise to two decimal places.
Currency, dates, duplicate evidence, duplicated invoice numbers, IDs
and data-quality issues are checked. Missing and foreign-tenant IDs
produce the same generic result, without disclosing foreign amounts.
No invoice or balance is changed. Responses include source SHA-256,
mismatches and independently_verified=false.

A file hash does NOT authenticate bank statements, settlement, cash,
revenue recognition, FX or an auditor. Genuine independent source
verification remains open until trusted evidence is supplied.

## 2. Multi-tenant resource and security tests

Persistent tenant_resource_windows budgets enforce, across PostgreSQL
workers, expensive operations per tenant and resource class:
- AI command: 30 per 60 seconds
- Memory search: 120 per 60 seconds
- CSV import: 6 per 300 seconds
- Financial reconciliation: 20 per 60 seconds

Exhaustion returns HTTP 429 with Retry-After. Disposable PostgreSQL
concurrency tests launch 12 workers, verify correct shared enforcement
and another tenant's independent quota. Existing authentication, file
limits, and same-tenant joins still apply.

This is NOT a global memory/CPU/GPU governor, a DDoS firewall, a
sustained independent stress test, or proof of deployed resource fairness.

## 3. Clean Windows installation

New Windows Actions job does a fresh Python 3.11 / Node 20 install,
Python dependencies, npm ci and frontend build, SQLite Alembic migration,
financial and rate tests, then launches a local Uvicorn child process.
A black-box HTTP smoke creates two synthetic tenants and confirms
separate business IDs, live health/registration, dashboard uncertainty,
mock fixture denial and evidence discrepancy labeling. The child is
always terminated, and a JSON receipt is archived.

Only a successfully completed Windows workflow on the current head
constitutes evidence. CI cannot verify every arbitrary Windows PC.

## 4. Independent production acceptance

A separate acceptance-evidence Actions workflow tests and produces a
commit-tagged receipt, but explicitly labels production_level_3=NO_GO.
Self-authored source code and CI tests are NOT an independent audit.

A future independent assessor must review an approved live host with
synthetic data, real TLS and network isolation, eligible zero-dollar
hosting, separate offsite encrypted backup restore, provider privacy,
authenticated financial source documents, security/availability load,
end-to-end failures and recovery, and formally sign the evidence.

Do not close issues or mark production-ready without that real
independent evidence. A prototype hackathon demo is a separate,
lower-readiness decision.

## Strict gating

All applicable workflows must be green on the exact latest head before
another engineering batch: API/PostgreSQL/Ollama/build, browser E2E,
isolated browser inference experiment, Windows clean startup, and
automated acceptance evidence. Keep PR #8 draft and unmerged.
