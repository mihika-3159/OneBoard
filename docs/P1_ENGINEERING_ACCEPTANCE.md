# P1 engineering controls and acceptance matrix

These controls were developed on **draft PR #8**, after the earlier PR head
`3fb8592a6f025b782be6187bcee3c3acc93f5c31` passed all three
GitHub Actions workflows. They do **not** authorize a provider account,
live deployment, model download to an end-user device, customer-data access,
or expenditure. An individual implementation change is not acceptance of
all criteria in a GitHub issue.

## P1 #5: Server-side Ollama reliability, backpressure and UI truthfulness

Implemented:
- Real inference is reported as ready **only** when the exact chat model
  selected by the current business is installed on the reachable Ollama
  server. An unrelated downloaded model cannot make the selected profile
  appear ready. The API returns `requested_model`,
  `requested_model_installed`, `available_models` and
  `inference_available` separately.
- Local server-side inference is limited to two in-flight requests **per
  API process**, with a three-second bounded wait before returning a
  distinctly labeled `capacity_exceeded` fallback. This protects CPU
  resources without inventing a successful model answer. It is **not**
  cluster-global rate limiting or a production-scale queuing system.
- Ollama responses require actual completion (`done=true`), a nonempty
  message, matching model when named, and a JSON object for structured
  output. Missing, mismatched, partial, malformed, timed-out, busy and
  non-200 responses are labeled simulated, with the reason visible to the
  caller. Inference errors do not log prompts or provider error bodies.
- The Settings UI distinguishes offline server, installed-but-wrong model,
  actual benchmark success and simulated fallback. The shared frontend
  API client already throws typed non-2xx errors; Settings and Integrations
  display retryable error banners.
- Regressions:
  `tests/unit/test_gateway_reliability.py`,
  `tests/adversarial/test_ollama_backpressure_and_model_truth.py`,
  `apps/web/e2e/p1-reliability.spec.ts`, dedicated real-Ollama CI and
  TypeScript production build.

Not yet accepted: verified multi-process/global load shedding, audited
provider tenancy isolation and quotas, long-duration soak/load tests,
real zero-dollar **server-side** GPU/LLM hosting, guaranteed inference
availability, privacy/security terms of an approved provider and actual
resource measurements on target hardware. No fallback is described as real
AI. The legacy browser feasibility experiment is **not** the default AI
architecture or approval for user-side model downloads.

## P1 #6: Safe integration access, bounded ingest and restart-aware alerts

Implemented:
- The fixed Northstar CRM, ledger and GitHub fixtures are accessible only
  from the explicitly enabled, nonproduction Northstar demo workspace.
  Registered business tenants and **all production requests** receive
  404 rather than fictional customers, finances or source-control state.
- Non-mock integrations are not connected by simply changing database
  status; unimplemented live synchronization returns 501. Sandbox
  refresh is explicitly labeled simulated and makes no external calls.
  Provider configuration/credentials are not included in integration
  list responses. The UI labels sandbox-only entries and disables live
  provider sync buttons. Chat import starts empty, extracts only heuristic
  candidate statements and does not silently index them.
- Existing ingestion guards read at most 10 MiB plus one byte and
  bound extraction, ZIP expansion, PDF pages, XLSX rows/columns and
  database persistence. Unauthorized and cross-tenant access are covered
  by the existing adversarial security matrix.
- Scheduler reads **tenant-scoped persisted source records** and
  recomputes alerts on every GET. A new scheduler instance reconstructs
  the same alerts after a process restart; stale process cache is not the
  authoritative record. Invalid/nonfinite/negative invoice amounts produce
  a data-quality alert without a fabricated receivables total. Scheduler
  startup errors now prevent a production service from starting, rather
  than silently claiming monitoring is running. No credentials are
  printed in startup logs.
- Regressions:
  `tests/adversarial/test_demo_integration_tenant_scope.py`,
  `test_scheduler_restart_and_invalid_invoices.py`, existing document
  abuse/tenant-route tests, and browser-based sandbox/unavailable-provider
  and retry scenarios.

**Operational limitation:** APScheduler's timed jobs and the sandbox
email outbox are **in-process, not a durable distributed job queue**.
GET requests regenerate alert facts from persisted invoices and
commitments, but queued interval ticks are not guaranteed across outage,
deployment restarts, multiple replicas or sleeping free-tier hosting.
Do not advertise exactly-once monitoring, 24/7 active checks, real email
delivery, OAuth, or a live connected provider. Live auth, scopes, revoked
token handling and actual provider sync results are unimplemented and
require explicit user approval and eligible hosting before integration.

## P1 #7: Independent security, workflow, UI, performance and portability

Existing GitHub Actions cover Linux Python unit/adversarial/API integration,
FastAPI route/auth tests, migrated PostgreSQL 16 with concurrency and
backup/restore, frontend TypeScript/Vite production build, Chromium
Playwright E2E, dedicated small real-Ollama CPU inference and isolated
browser inference experiments. The new browser regression covers
cross-tenant mock fixture restrictions, selected-model status, retry-safe
workflow execution and a simulated HTTP 503 with visible recovery.

Use the following reproducible commands **only against disposable local
data**, not live customer databases:

```sh
python -m compileall -q apps/api tests alembic
python -m pytest -v
cd apps/web && npm ci && npm run build
cd apps/web && npx playwright test
```

The PostgreSQL 16 CI test environment has a strict locally validated
`oneboard_ci` URL; its restore drill creates only
`oneboard_restore_ci`. Follow `TEST_REPORT.md` for the exact CI
commands, results, head SHA, and verification-run URLs.

**Incomplete acceptance criteria:** a clean native Windows startup and
service run, real deployment browser certificate and proxy tests,
hardware-specific sustained CPU/GPU measurements, privacy review against
an approved provider, operational alert durability across external
outages, live integration token verification, real external delivery
and full proof of every marketing/README claim. Mark these **blocked or
not verified**, not passed. Do not close P1 issues #5–#7 or mark the PR
ready merely because the subset of tests above passes.

All decisions remain under the OneBoard owner: no spending, account signup,
hosted deployment, live email, live model provider, customer data or merge
without explicit approval.
