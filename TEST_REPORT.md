# OneBoard release verification report (2026-11-15)

**Scope:** draft [PR #8](https://github.com/mihika-3159/OneBoard/pull/8), isolated CI databases, GitHub-hosted Linux runners. **Not a production certification.** The report distinguishes previously completed CI from tests introduced on 15 November.

## Last fully verified head before release-review edits

Commit `4b2a707ed2a3960f6d7e15f2a0bf8aaa7f104b5b`, 14 November 2026:

| Check | Result | Evidence |
|---|---|---|
| Python compile, pytest unit/integration/adversarial suite, SQLite Alembic upgrade/downgrade/upgrade | PASS | [Verification run 43564543771](https://github.com/mihika-3159/OneBoard/actions/runs/43564543771), api-tests job |
| Frontend TypeScript and production build | PASS | Same verification run, web-build job |
| Real Ollama qwen2.5:0.5b health, text inference, JSON inference, unavailable-model and offline fallback | 4 PASS | Same verification run, ollama-live job |
| Chromium browser login/logout, two-founder isolation, unauthorized workflow access | 3 PASS | [Browser E2E run 43564543644](https://github.com/mihika-3159/OneBoard/actions/runs/43564543644) |
| Browser app server connected to Ollama | NOT TESTED | Browser job intentionally runs without Ollama; separate live-model job exercises gateway |

**Important:** A green workflow only proves the specific checks in that workflow. These results belong to the **November 14 commit**, not to subsequent release-review commits.

## November 15 release-review changes

- Added `apps/web/e2e/navigation.spec.ts`: fresh founder registration, all **11** sidebar views, main view visibility, browser JavaScript error check, screenshots, logout. This is a browser smoke test, **not** proof that every action inside every tab works.
- Updated `README.md` to label the product a prototype, correct setup commands, disclose non-implemented live integrations/cloud fallback and clarify the limitations of offline simulation, audit logging and background scheduling.
- **New final-commit CI must be inspected before marking these changes passing.** Browser screenshots are generated inside the test runner; unless uploaded as CI artifacts they are not independently reviewable outside that runner.

## Unverified / blocked release criteria

| Area | Status and required evidence |
|---|---|
| End-to-end founder workflow: create, execute, approve/reject, retry, agent test, council decision, memory and finance | PARTIAL. Existing browser tests verify authentication and isolation; the new navigation smoke test checks tab mounting only. Full actions, failure cases and persisted results need dedicated browser tests |
| All sidebar tabs | NEW TEST PENDING. Test visits all 11 tabs but does not exercise every control |
| Fresh database and demo seed | PARTIAL. Browser CI starts with disposable SQLite; explicit seeded-demo reset and seeded-data correctness not tested |
| Real Ollama | PARTIAL. Four small CPU-model gateway tests pass; qwen2.5:7b / llama3.1:8b / 14b profiles, latency, concurrent users, memory consumption and business-quality outputs not verified |
| External provider sync, cloud LLM fallback | NOT IMPLEMENTED / NOT VERIFIED. Demo adapters must never be presented as actual third-party sync |
| Security | PARTIAL. Cookie CSRF, sessions, tenant isolation and adversarial tests exist; external security review, production HTTPS/cookie deployment, secret rotation and multi-worker abuse/rate limiting unverified |
| Workflow safety | PARTIAL. Tool dispatch and approval tests exist; durable exactly-once execution, restart replay and crash recovery not verified |
| Scheduler and alerts | PARTIAL. Alerts reconstruct from persisted business records and tests cover freshness; durable scheduled jobs, multi-worker coordination and persisted alert history absent |
| Windows startup | NOT VERIFIED. GitHub CI uses Ubuntu; PowerShell startup script and local Windows environment not executed |
| Production deployment, load and performance | NOT VERIFIED. No deployed HTTPS environment, performance benchmarks or concurrent-user soak evidence |
| Financial/accountability provenance | PARTIAL. Deterministic calculation tests exist; source evidence and immutable audit claims not independently established |
| README marketing claims | CORRECTED WITH RELEASE DISCLAIMER. Existing architectural prose may describe aspirational behavior; treat it as non-certified unless tests support it |

## Reproduction

```bash
# From repository root, with Python dependencies installed and AUTH_SECRET_KEY set:
python -m compileall -q apps/api tests alembic
python -m pytest -v
python -m alembic upgrade head
python -m alembic downgrade base
python -m alembic upgrade head
cd apps/web && npm ci && npm run build
# Browser test (with Chromium and backend dependencies installed):
npx playwright test --config playwright.config.ts
```

For the real Ollama test, start Ollama and pull `qwen2.5:0.5b`; set `ONEBOARD_LIVE_OLLAMA_TESTS=1`, `ONEBOARD_CI_OLLAMA_MODEL=qwen2.5:0.5b`, then run `python -m pytest -q tests/test_ollama_live_ci.py` from repository root.

## Release decision

**NOT CERTIFIED FOR PRODUCTION.** The application has meaningful CI coverage and a working small-model inference smoke test, but full real-provider, Windows, production, concurrency, crash-recovery and founder-action verification remain outstanding. Keep PR #8 draft and unmerged until its **final head** passes and remaining release risks are explicitly accepted. Never use real customer data or live payments for these checks.
