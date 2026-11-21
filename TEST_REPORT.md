# OneBoard release verification report (2026-11-15)

**Scope:** draft [PR #8](https://github.com/mihika-3159/OneBoard/pull/8), isolated CI databases, GitHub-hosted Linux runners. **Not a production certification.** The report distinguishes previously completed CI from tests introduced on 15 November.

## Earlier verified head before release-review edits

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
- **Final release-review commit verified:** `8bab508ce187b47ce063d02981524a8e95f5c84b` (15 November). [Verification run 43718507615](https://github.com/mihika-3159/OneBoard/actions/runs/43718507615): Python tests, SQLite Alembic upgrade/downgrade/upgrade, frontend build and four live Ollama smoke tests passed. [Browser E2E run 43718507596](https://github.com/mihika-3159/OneBoard/actions/runs/43718507596): 4 Playwright tests passed in 10.1 seconds, including the new 11-tab navigation smoke test. I inspected the individual job logs on 17 November. Screenshots were not uploaded because artifact upload is configured for failure only.

## Unverified / blocked release criteria

| Area | Status and required evidence |
|---|---|
| End-to-end founder workflow: create, execute, approve/reject, retry, agent test, council decision, memory and finance | PARTIAL. Existing browser tests verify authentication and isolation; the new navigation smoke test checks tab mounting only. Full actions, failure cases and persisted results need dedicated browser tests |
| All sidebar tabs | PASS for 11-tab navigation smoke test at commit `8bab508`; does not exercise every control |
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

**NOT CERTIFIED FOR PRODUCTION.** The application has meaningful CI coverage and a working small-model inference smoke test, but full real-provider, Windows, production, concurrency, crash-recovery and founder-action verification remain outstanding. Final-head CI passed on 15 November, but keep PR #8 draft and unmerged until remaining release risks are explicitly accepted. Never use real customer data or live payments for these checks.

## Independent final-head log review (17 November 2026)

- Reviewed GitHub Actions job logs, not just green check summaries, for commit `8bab508`.
- API job passed pytest and disposable SQLite migration upgrade/downgrade/upgrade. Frontend build passed with a non-fatal Vite chunk-size warning (827.59 kB JS bundle, 235.02 kB gzip).
- Live Ollama job downloaded and exercised the small `qwen2.5:0.5b` model: **4 passed in 2.00s**. This is not a quality benchmark or proof of larger model performance.
- Browser job: **4 passed in 10.1s**. Ollama was unavailable to the browser job, so full browser-to-live-model behavior remains blocked.
- GitHub Actions reported Node.js 20 deprecation warnings for some actions. These did not fail the jobs but warrant maintenance.
- No failing final-head CI job was observed. No additional application code fix was justified by these logs alone. Outstanding functional and deployment gaps above remain open; this is not a production sign-off.

## 20 November 2026, 11:02 Dubai: CSRF CI failure and corrective commit

- **Observed failing head:** `89b5dcb8064c986af491806c1d620c2d0cb91e40`. [Verification run 44684655423](https://github.com/mihika-3159/OneBoard/actions/runs/44684655423) failed its `api-tests` job. Inspected job 136116017855 logs: **203 passed, 1 failed, 21 skipped**. The failing case was `tests/adversarial/test_cookie_origin_validation.py::test_rejects_cross_site_cookie_mutations[None-not-a-url]`: a malformed Referer without an Origin was incorrectly treated as absent in development mode. SQLite migration smoke was skipped after pytest failed. Frontend build and real Ollama inference jobs passed.
- [Browser E2E run 44684655382](https://github.com/mihika-3159/OneBoard/actions/runs/44684655382) passed on the failing API head; this does not override the failed security test.
- **Corrective commit:** `ae5356f1cd58a160b1f877213b831d75d60e4386` changes malformed Referer handling to an explicit HTTP 403 in all modes. Existing regression test remains unchanged and should now pass. **New-head CI pending; do not claim verified until it completes.**
- **Still blocked:** shared cross-worker login throttling, production PostgreSQL migration/concurrency checks, durable workflow execution across crashes, real external integration synchronization, full end-to-end founder action testing and independent production deployment review. No production certification.


## 20 November 2026, 12:04 Dubai: workflow approval definition integrity

- **Prior head verified:** `94f16c9bd521fca50b3b9c1ab1d19d5f1778823e`. [Verification 44692053463](https://github.com/mihika-3159/OneBoard/actions/runs/44692053463) and [browser E2E 44692053300](https://github.com/mihika-3159/OneBoard/actions/runs/44692053300) both completed successfully. Workflow summaries only; individual job logs not inspected this run.
- **New fix:** `b056e42758e78c4ea3c5959274ff8e6152377ae8` pins a SHA-256 digest of the complete executable workflow nodes and edges in run verification details, and rejects approval/resume if the definition changes while approval is pending. Previously only node IDs and order were checked, permitting a changed connector, operation, or action payload under the same node IDs.
- **Regression tests:** `6ee66cd4c5d5ecd083fca9ae5649acc357075207` adds adversarial tests for connector, operation, and label changes, asserting no commit on rejected resume, plus stable key-order hashing.
- **Verification:** CI for the new test commit was not yet available when checked. The tests are committed, **not yet claimed passed**. Existing pending approvals created before this change lack a digest and deliberately fail closed; operators must start a fresh run.
- **Remaining blocker:** This prevents changed workflow definitions from being approved, but does not establish durable exactly-once execution after a worker crash or across multiple workers. Production PostgreSQL concurrency, crash recovery and browser action coverage remain unverified.


## 20 November 2026, 12:56 Dubai: workflow definition pinning CI regression

- Inspected draft PR #8 head `5fc76020e4e5bb3c95c93476e2d0f54c8c1c4354` and GitHub Actions [verification run 44699740243](https://github.com/mihika-3159/OneBoard/actions/runs/44699740243). API tests **FAILED: 3 failed, 205 passed, 21 skipped**. The three failures are all in `tests/adversarial/test_workflow_definition_pinning.py::test_executable_changes_invalidate_approval`: the test fixture used a `SimpleNamespace` run without `workflow_id`, but production approval code correctly requires `run.workflow_id` to retrieve the pinned definition. The failure occurs before the digest assertion, so the intended tamper rejection was not exercised. The frontend and live Ollama jobs passed in the same run; [browser run 44699740248](https://github.com/mihika-3159/OneBoard/actions/runs/44699740248) passed.
- **Corrective commit:** `54b1ef7ae07406ac39fd50b497ae0430ff3bf4cc` adds the missing `workflow_id` to the test fixture. The test still asserts altered connector, operation or label prevents approval and no transaction is committed. **CI on this new commit must pass before calling this fixed.**
- **Release remains blocked:** production PostgreSQL concurrency/migrations, multiworker login throttle, crash-safe exactly-once workflows, live integration verification, comprehensive founder browser journey, HTTPS deployment/security and performance testing. PR stays draft; no production certification.


## 20 November 2026, 14:02 Dubai: approved high-risk actions no longer silently skipped

- **Baseline:** draft PR #8 head `5347a73ac1f1c0f7716fac25357a167765c95f8b` passed both GitHub Actions workflows: [verification 44706559057](https://github.com/mihika-3159/OneBoard/actions/runs/44706559057) and [browser E2E 44706559326](https://github.com/mihika-3159/OneBoard/actions/runs/44706559326).
- **Finding:** `WorkflowEngine.approve_and_resume_run` always resumed at `checkpoint_index + 1`. That is correct for a pure approval/control node, but silently omitted execution of an executable node flagged `risk=high`. The approval state could therefore be mistaken for a completed action.
- **Fix:** `d6e19612f9a165f292803a05aaaf8afccd800b3d` dispatches the approved executable checkpoint after the durable approval claim, records the actual result and fails the run without continuing downstream if the approved action fails. Pure approval nodes remain control-only. No real outbound email adapter is enabled.
- **Tests:** `39b6f32125a00c9beba65b543f618e8d4d60960d` adds three adversarial regression cases for executable approved checkpoints, pure approval checkpoints and failed approved actions. **New CI was not yet available at inspection; do not claim these tests passed until confirmed.**
- **Remaining risks:** A worker crash after the durable approval claim can leave a run `running` with incomplete step results. No automatic replay is attempted, which avoids an unverified duplicate external action but requires operator recovery. Shared rate limiting, PostgreSQL multiworker concurrency and full end-to-end founder journey remain unverified. Issue #2 is not closed.


## 20 November 2026, 15:00 Dubai: broader council challenge coverage

- **Baseline CI:** prior PR head `e2267f0f335ac4c0393e9829971e25dca6085430` passed [verification run 44715928200](https://github.com/mihika-3159/OneBoard/actions/runs/44715928200) and [browser run 44715928165](https://github.com/mihika-3159/OneBoard/actions/runs/44715928165).
- **Finding:** `CouncilEngine.conduct_deliberation` previously compared only the first two selected non-facilitator advisers, even if the founder selected more specialists. The synthesis prompt therefore received only one challenge and omitted later adviser disagreements.
- **Fix:** commits `af9b389`, `47ffbb5`, `cfbea1a` and `a55090c` compare adjacent selected specialists, record each attributable challenge and include every comparison in synthesis. Existing offline fallback remains explicitly labelled. This increases inference calls for larger councils and may affect latency.
- **Regression tests:** `a0c5d18` adds coverage for all nine known roles, founder-selected order and single-specialist no-debate behavior. **The new CI run was not yet reported when inspected; these tests are not claimed passed.** Full multi-adviser integration tests with real Ollama and response quality evaluation remain outstanding.
- **Open:** issue #4 remains open because substantive recommendation accuracy, changed financial inputs and full transcript attribution still require runtime validation. Seven issues remain open. Production PostgreSQL, multiworker throttling, crash-safe workflows and deployed end-to-end demo remain release blockers.

## 20 November 2026, 16:00 Dubai: browser-bundled demo credential exposure

- **Previous head:** `7fff443006aae0fb6b2081ad63adf991b85fd3f5` passed [verification 44723769645](https://github.com/mihika-3159/OneBoard/actions/runs/44723769645) and [browser E2E 44723769653](https://github.com/mihika-3159/OneBoard/actions/runs/44723769653). Workflow summaries were inspected; this is not a full log audit.
- **Security finding:** GitGuardian's PR #8 comment reports a generic password embedded in `apps/web/src/App.tsx` in historical commit `80eafd35`. Current source still prefilled `oneboard2026` on clicking 'Use Demo Login'. Public browser JavaScript cannot keep passwords secret.
- **Fix:** commit `ee8bd599` removes the password from the browser shortcut, clears any existing password field and changes the shortcut to 'Use Demo Email'. Commit `6fd9a860` adds source-level regression tests preventing the literal credential and password-prefill behavior. These commits do **not** erase Git history or rotate the previously exposed password.
- **Verification:** The new-head CI is pending. No claim of passing tests yet. **Operator action required:** determine whether this password was ever used outside disposable demo data; if so, revoke/rotate it and invalidate relevant sessions. GitGuardian incident must be triaged separately. The demo now requires manually entering the configured local demo password, which should be supplied through safe setup documentation rather than embedded in the shipped frontend.
- **Unresolved:** seven open issues; multiworker login throttling, crash-safe exactly-once workflow execution, PostgreSQL load/concurrency, real provider sync, and full end-to-end demo quality checks. This is not a production certification.

## 20 November 2026, 17:00 Dubai: fix remaining browser credential and red CI

- **Evidence:** PR head `f80b8b1` had verification run [44731694492](https://github.com/mihika-3159/OneBoard/actions/runs/44731694492) **failed** (api-tests: 1 failed, 215 passed, 21 skipped; web-build and live Ollama jobs passed). Browser run [44731694572](https://github.com/mihika-3159/OneBoard/actions/runs/44731694572) **passed**. GitHub job `136272808509` identifies `tests/adversarial/test_frontend_demo_secret.py::test_demo_shortcut_does_not_embed_or_prefill_password` failing: the initial React state in `apps/web/src/App.tsx` still contained the exposed demo password, even though the shortcut had been fixed.
- **Correction:** commit `9859dfa` initializes `authPassword` to an empty string. The existing adversarial test now guards both the initial state and shortcut. This is a code-level correction; **new-head CI is pending and not claimed passed**.
- **Security follow-up:** exposed password remains in Git history. Rotate/revoke if ever reused outside disposable local demo data; investigate GitGuardian finding. No live credentials were used. Multiworker throttling, durable crash-safe workflows, real provider integration and production concurrency tests remain open. No issue acceptance criteria have been fully demonstrated; all seven issues remain open.


## 20 November 2026, 18:00 Dubai: expanded document upload limit

- **Previous verified head:** `0c4812f4ba55151c5188adfb3f6bf5b1ab7abddd`. GitHub Actions runs [44740216893](https://github.com/mihika-3159/OneBoard/actions/runs/44740216893) and [44740217160](https://github.com/mihika-3159/OneBoard/actions/runs/44740217160) completed successfully. These runs predate this change.
- **Finding:** `apps/api/routers/memory_router.py` capped uploaded bytes at 10 MiB, but did not cap extracted text. A compressed spreadsheet or document could produce much larger text and trigger excessive chunking, embedding, database storage and resource consumption.
- **Fix:** commit `20aaa200` rejects extracted text above 2,000,000 characters or non-string parser output before calling document persistence. Commit `4d7d546` adds two isolated regression tests asserting HTTP 413 and zero persistence calls.
- **Verification:** New-head CI must run before these tests can be reported as passing. The bound limits post-extraction work, **not** parser CPU/memory consumed during decompression; compressed archive expansion limits and parser isolation remain necessary for hostile files.
- **Release:** issue #6 remains open because live provider sync, durable scheduled jobs, and parser resource isolation are not fully verified. All seven issues remain open; production certification remains blocked.

## 21 November 2026: offline AI financial-claim correction

- **Baseline:** head `6da08ea` passed [verification 44750056706](https://github.com/mihika-3159/OneBoard/actions/runs/44750056706) and [browser E2E 44750056629](https://github.com/mihika-3159/OneBoard/actions/runs/44750056629). These results predate this fix.
- **Finding:** `apps/api/services/ollama_gateway.py::_generate_simulated_response` produced a canned offline conversational response claiming Northstar Studio revenue, 38 customers, 7.2 months runway and a named commitment regardless of the authenticated business. This could mislead founders and leak demo-specific narrative across tenant contexts.
- **Fix:** commit `4d4b75a` replaces that fallback with an explicit no-inference/no-verified-facts notice. Commit `9f9497f` adds two regression tests for fabricated financial values and prompt independence. **New-head CI has not been confirmed.**
- **Scope limitation:** JSON structured fallbacks still include seeded demo-specific claims and require separate hardening; do not treat them as real analysis. Shared login throttling, PostgreSQL multiworker testing, workflow crash recovery, live integrations and complete founder browser flows remain unverified. No production certification.

## 21 November 2026: durable cross-worker login throttling (first batch)

- **Baseline:** previous PR head `0e886b4` passed [verification 44883625801](https://github.com/mihika-3159/OneBoard/actions/runs/44883625801) and [browser E2E 44883625822](https://github.com/mihika-3159/OneBoard/actions/runs/44883625822).
- **Finding:** `apps/api/core/auth.py` used process-local `_LOGIN_ATTEMPTS` counters. Separate API workers could bypass the failed-password counter, and process restarts erased it.
- **Changes in this batch:** persistent SHA-256-keyed `LoginThrottleState`, Alembic revision `002_shared_login_throttle`, production PostgreSQL transaction-scoped advisory locking spanning check and failure/clear commits, login endpoint wired to its DB session, and adversarial cross-session/expiry/fail-closed tests. SQLite regression is not a PostgreSQL concurrency proof; local no-DB helper remains test-only.
- **Verification:** tests and migration smoke are committed for GitHub CI, but **new-head CI not yet reported at authoring time**. The production PostgreSQL advisory-lock path, concurrent multiworker attacks and lock contention must be independently exercised before claiming issue #1 resolved.
- **Outstanding:** login key is IP+email; distributed attacks from different IPs against one account and stale counter cleanup need additional controls. Durable workflow recovery, tenant-wide end-to-end tests, production HTTPS deployment, backups and live integrations remain blocked. No production certification.
