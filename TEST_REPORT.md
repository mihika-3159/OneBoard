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

## 21 November 2026: structured offline inference truthfulness

- **Baseline:** PR head `1309903a5d168c39fb85663549121315ae55a4ca` had completed successful [verification run 44889884109](https://github.com/mihika-3159/OneBoard/actions/runs/44889884109), [browser E2E run 44889884163](https://github.com/mihika-3159/OneBoard/actions/runs/44889884163) and isolated browser feasibility run 44889884102. These are **prior-head** results, not verification of this batch; individual job logs were not inspected in this batch.
- **Production fix:** `b8c7ec0207d142695f7b7ebdd3da07cfa80ab479` removes fabricated pricing, runway and customer claims from the offline structured council and generic-analysis responses. The returned JSON explicitly marks inference unavailable and simulated; workflow and agent template fallbacks remain illustrative and require separate labeling review.
- **Regression tests:** `96fbe61b5d71715677069e117b85c804adc697d6` adds parameterized checks for no invented tenant financial evidence, no actionable council recommendation and explicit text-fallback disclosure.
- **Verification status:** New-head GitHub Actions runs were not returned immediately after `96fbe61`; **PENDING, NOT PASSED**. Reproduce with `python -m pytest -q tests/adversarial/test_offline_structured_truthfulness.py`, then full `python -m pytest -v`, disposable Alembic migration smoke, web build, and browser E2E in CI. Inspect actual new-head job logs before changing status.
- **Release blockers:** No production PostgreSQL concurrent-migration or multiworker throttle evidence; durable workflow crash recovery and replay remain unverified; full founder browser actions, data-dependent council quality, external integration state, HTTPS deployment, backup/restore and resource-limited hosting remain incomplete. No provider has been approved or integrated. All seven issues remain open. PR #8 remains draft; no Level 3 certification.

## 21 November 2026: structured offline inference truthfulness

- **Observed baseline:** draft PR #8 head `1309903a5d168c39fb85663549121315ae55a4ca`; earlier head `1309903` had successful [verification 44889884109](https://github.com/mihika-3159/OneBoard/actions/runs/44889884109) and [browser E2E 44889884163](https://github.com/mihika-3159/OneBoard/actions/runs/44889884163). Those runs do **not** verify later commits.
- **Production correction:** `b8c7ec0207d142695f7b7ebdd3da07cfa80ab479` removes fabricated financial facts and invented advice from the structured offline council and generic JSON fallbacks in `apps/api/services/ollama_gateway.py`. A workflow-template and agent-template fallback still returns illustrative structures; those must remain explicitly simulated and must not be executed as verified provider actions.
- **Regression:** `tests/adversarial/test_offline_structured_truthfulness.py` on the branch asserts that structured fallback is unavailable/simulated and does not invent tenant financial claims. Test-file commit SHA should be confirmed from Git history before attributing it.
- **Latest inspected PR head:** `96fbe61b5d71715677069e117b85c804adc697d6`. No associated CI runs returned during this inspection. **New-head tests PENDING / NOT VERIFIED.** Reproduction: `python -m pytest -q tests/adversarial/test_offline_structured_truthfulness.py`; full verification: `python -m pytest -v`, `python -m alembic upgrade head`, `python -m alembic downgrade base`, `python -m alembic upgrade head`, and `cd apps/web && npm ci && npm run build`. Browser E2E requires Playwright Chromium and a disposable backend DB.
- **Release blockers:** PostgreSQL multiworker rate-limit and migration concurrency, crash-safe workflow recovery and idempotency, full founder-action browser journey, tenant-isolated persistent alerts, actual deployed HTTPS and backup/restore, and independently verified no-card/minor-eligible zero-cost hosting/inference. No external provider approved or enabled. No Level 3 certification, no issue closure.


## 22 November 2026: signed-token claim validation (verification pending)

- Draft PR #8, branch `fix/p0-auth-tenant-isolation` only. No merge or deployment.
- Prior head `7c831e8838a56c7807465f70d8f2f9fec3109337`: GitHub Actions verification, browser E2E, and browser inference feasibility all reported success for **that earlier SHA only**.
- Code commit `85d723c06f115e496616c1510fd818e67f6275cd`: reject malformed signed JWT-like payload identities, missing session IDs, invalid time claim types, tokens expiring exactly now, and future-issued tokens.
- Regression test commit `4512e1a5cc3a65ad9b8d984c69d3665a8f86443d`: adversarial valid-HMAC malformed-claim cases plus legitimate round-trip.
- On querying workflow runs for `4512e1a5cc3a65ad9b8d984c69d3665a8f86443d`, the API returned **no associated PR workflow runs yet**. This is **UNVERIFIED/PENDING**, not green. CI on an older head does not validate these commits.
- Reproduction: run `pytest -q tests/test_auth_token_claims.py` in the configured API test environment, then verify every applicable PR GitHub Actions workflow against the latest commit SHA.
- Outstanding: full authentication/tenant/migration batch and concurrency tests; do not proceed to workflow/financial batch until latest-head checks are all green and batch acceptance criteria are met.


## 22 November 2026, security batch: account-scoped throttling and logout ownership

- Prior head `21e87ace6ed4bb04d15610b87404a69b93557d9a`: all three applicable PR workflows completed successfully: [verification 45000673684](https://github.com/mihika-3159/OneBoard/actions/runs/45000673684), [browser E2E 45000673658](https://github.com/mihika-3159/OneBoard/actions/runs/45000673658), [browser inference feasibility 45000673702](https://github.com/mihika-3159/OneBoard/actions/runs/45000673702). This is **prior-head evidence only**.
- Production fix `053dcdb4159369c63ac0f17572ea6f1a708d39a0`: failed-login throttle identifier is now account-wide rather than source-IP-plus-account, preventing simple IP rotation from evading the persistent per-account lockout. Logout now checks both stored session user and tenant against the signed token before revocation.
- Adversarial tests `1ab513be3b52d07ced63b4390ce880aaebab3ddc`: verify three IP addresses share the same account throttle key, and mismatched session user/tenant cannot be revoked by another signed identity.
- **Current-head CI: pending/unverified at authoring.** The GitHub PR workflow query returned no runs yet for `1ab513be3b52d07ced63b4390ce880aaebab3ddc`. Run `pytest -q tests/adversarial/test_account_throttle_logout_scope.py` and all applicable PR workflows on the latest commit; do not move to the next batch until all checks pass.
- Security limitations: account lockout can be used for targeted denial of service; per-source/IP and account-level rate limits need a carefully ordered dual-key transaction, real PostgreSQL concurrent-worker verification, and operational review. Production migration concurrency and tenant access review remain outstanding. PR #8 remains draft; no release or Level 3 certification.


## November 22: logout revocation persistence hardening

- Baseline head `c1f262db5b73d4490cd38ad344cf3ed24c9404e8`: verification workflow `45005231822` **PASS**; browser E2E `45005231839` **PASS**. Browser inference feasibility workflow `45005231757` was **CANCELLED** during the qwen3-1.7b CPU smoke job, despite its other jobs passing. A retry of that cancelled job was requested; the workflow was still in progress at last inspection. This experimental workflow is not evidence of approved production browser inference.
- Commit `4ff7980eef6957ed7254bbbeb2e4cda4eac74bb3`: logout no longer swallows database query or commit failures. On a failed revocation commit, it rolls back and propagates the error rather than returning a false success.
- Commit `f0c2cb837f752c8f3efec4cc144323369a445d9b`: added adversarial tests for revocation commit failure and malformed bearer credentials.
- **Verification of these changes: PENDING.** No PR-triggered workflow runs were returned for head `f0c2cb837f752c8f3efec4cc144323369a445d9b` at inspection time. All applicable workflows must be verified on the eventual exact final head before advancing beyond the security batch.
- Reproduce targeted tests: `python -m pytest -q tests/adversarial/test_account_throttle_logout_scope.py`.
- Remaining security evidence: PostgreSQL multi-worker throttle concurrency and migration locking, deliberate account-lockout abuse resistance, production cookie/HTTPS deployment and cross-tenant integration tests. No external security audit has been performed.


## 22 November 2026, 14:55 Dubai: signed session lifetime boundary

- **Prior verified PR head:** `162ca6139cb89b502137b236e981277caaafddbd`. GitHub Actions completed successfully on this exact head: [browser E2E 45010539726](https://github.com/mihika-3159/OneBoard/actions/runs/45010539726), [verification 45010539771](https://github.com/mihika-3159/OneBoard/actions/runs/45010539771), and [browser inference feasibility 45010539727](https://github.com/mihika-3159/OneBoard/actions/runs/45010539727). These green results **do not verify the new commits**.
- **Code commit:** `0681f3b0f9a66b66a364f1afc13c8d12f5ba6997` rejects signed sessions whose `exp - iat` exceeds the configured session lifetime, uses an inclusive database expiry cutoff, and suppresses demo-user fallback when production mode is enabled.
- **Adversarial test commit:** `3612df3e63befa24f00f0b041067e9c240ca1e19` adds tests for overlong signed sessions, exact-limit valid sessions, and old issue times paired with excessive future expirations.
- **New-head verification:** pending at the time of this report. No claim of passing tests on `3612df3` or this report's later head. Recheck the exact PR head and every applicable workflow before starting Batch 2.
- **Remaining Batch 1 gaps:** multi-worker PostgreSQL throttle and migration concurrency evidence, account-lockout abuse resistance, tenant authorization across all endpoints, and production HTTPS security validation. This is not a production certification.


## 22 November 2026, 15:57 Dubai: CI blocker diagnosis and repair

- Exact failing PR head `c64284efe9c7cf9355c3c76094b236dcb7a3b18c`: verification workflow [45014821920](https://github.com/mihika-3159/OneBoard/actions/runs/45014821920) **FAILED** at `api-tests / Python syntax`; browser E2E [45014821878](https://github.com/mihika-3159/OneBoard/actions/runs/45014821878) **FAILED** because the API could not start; browser inference feasibility [45014821803](https://github.com/mihika-3159/OneBoard/actions/runs/45014821803) **PASSED**. These are results for the old head only.
- Root cause from both failing job logs: `SyntaxError: unexpected character after line continuation character`, `apps/api/core/auth.py:180`. The lifetime validation expression contained literal `\\n` characters instead of Python newlines, introduced by the prior session-lifetime change.
- Repair commit `2b29f6563b666da136a46aa51776a3ed5f776ca5` replaces the escaped sequences with actual Python line breaks without weakening token checks. New-head CI remains **UNVERIFIED** at the time of writing; wait for all applicable checks on this exact SHA, inspect any failures and keep Batch 1 open.
- Reproduction: `python -m compileall -q apps/api` followed by `python -m pytest -q tests/adversarial/test_account_throttle_logout_scope.py` and the complete PR verification and browser E2E workflows. No claim of local execution or production readiness.

## 22 November 2026, 17:00 Dubai: production CORS origin hardening

- Prior head `592839c6b7f37ab746299aea0b6419aee1656f0f` **PASS** on all three PR-triggered workflows: verification [45019905740](https://github.com/mihika-3159/OneBoard/actions/runs/45019905740), browser E2E [45019905717](https://github.com/mihika-3159/OneBoard/actions/runs/45019905717), browser inference feasibility [45019905741](https://github.com/mihika-3159/OneBoard/actions/runs/45019905741). These are previous-head checks only.
- Code commit `6eaa6d3e59809e38c5f50b96acdb6a03b3f793f4` tightens production CORS configuration validation to reject missing host, userinfo, URL path/query/fragment, malformed port and noncanonical origins. Prefix-only HTTPS checks were insufficient.
- Test commit `0933623b1af7683b28b8090dc8f7b78fd4053d98` adds parameterized adversarial cases and valid HTTPS origins.
- Reproduce: `python -m pytest -q tests/adversarial/test_production_cors_origins.py` and `python -m compileall -q apps/api`. **New-head CI is not yet verified** at report-writing time; this report commit itself will create a newer SHA and must be checked separately.
- Batch 1 remains open pending exact-head CI and PostgreSQL multi-worker concurrency, migration locking, account-lockout abuse, tenant authorization and production HTTPS integration evidence. No production deployment or independent audit.


## 22 November 2026, 18:04 Dubai: PostgreSQL concurrent migration serialization

- **Verified baseline:** `1d688a4bc95bb785084e8a079846b7e3b41b9848` had three successful pull-request workflow runs: [verification 45025460708](https://github.com/mihika-3159/OneBoard/actions/runs/45025460708), [browser E2E 45025460638](https://github.com/mihika-3159/OneBoard/actions/runs/45025460638), and [browser inference feasibility 45025460643](https://github.com/mihika-3159/OneBoard/actions/runs/45025460643). These green results **do not verify** the new commits.
- **Finding:** `alembic/env.py` previously ran migrations without serializing concurrent PostgreSQL deploys. Two workers could inspect the same old `alembic_version` and both attempt DDL.
- **Code:** `84e52d7146e6e31412a3fb4d04ef13cb187acc96` adds a transaction-scoped PostgreSQL advisory-lock helper. `b2192854affaebebb3d8581d2798c2991d1e6b2f` acquires that lock **before** Alembic's version inspection and keeps the same connection/transaction through migration DDL.
- **Regression tests:** `a4507e3ddebaccef3c10f0d28d63dd39e5afaa3f` adds tests for lock acquisition, transaction requirement, dialect isolation, and database failure propagation. **Not yet verified by CI** at the time of this entry.
- **Reproduce:** `python -m pytest -q tests/adversarial/test_migration_lock.py` and `python -m alembic upgrade head` against a disposable database. A real PostgreSQL parallel-process migration test remains **NOT TESTED**; mocked unit tests cannot prove inter-process serialization or operational permissions.
- **Release gate:** Remain on security/auth/tenant-isolation/migrations batch until all applicable workflows on the exact latest PR head are green and remaining batch acceptance criteria are proven. Do not merge, deploy, or certify.

## 22 November 2026, 19:00 Dubai: production/demo secret fail-closed correction

- **Previous verified PR head:** `982f310527a6504f1c51f67c7315733e86bc4e02`. GitHub Actions returned successful completion for OneBoard verification (run 45030924320), browser E2E (45030924390), and browser inference feasibility (45030924312), all on that exact SHA. Workflow summaries were checked; this does not establish real PostgreSQL multi-worker migration correctness.
- **Code commit:** `b94284604e5005a3d4b38178798bf69141bc4d1e`. Authentication previously accepted a fixed, publicly predictable signing key whenever demo mode was enabled, even if production mode was also enabled. Startup now rejects the no-secret combination when production mode is true.
- **Regression commit:** `576d9ced0d165c91cc0d73cd15acec02b81fd18e`. Four fresh-interpreter tests cover conflicting flags, missing secret in production, local demo sentinel, and explicitly configured secret. Run: `python -m pytest -q tests/adversarial/test_production_demo_secret.py`.
- **New-head CI:** Pending verification after this report update. Do not reuse previous-head green results as evidence for these changes. Batch 1 stays open; real concurrent PostgreSQL migration tests, shared throttle contention and tenant authorization remain unverified.


## 22 November 2026, 20:00 Dubai: production anonymous-demo authorization regression

- **Prior verified head:** `88d5411b366ee3a86a60a13b46e12f8f11931e8d`. All three pull-request workflows completed successfully: [verification 45035821910](https://github.com/mihika-3159/OneBoard/actions/runs/45035821910), [browser E2E 45035821674](https://github.com/mihika-3159/OneBoard/actions/runs/45035821674), [browser inference feasibility 45035821816](https://github.com/mihika-3159/OneBoard/actions/runs/45035821816). These are **prior-head results**, not proof of subsequent commits.
- **Regression commit:** `6fd7ba29b005b7a84abe70b53e9ac472cef57d29` adds `tests/adversarial/test_production_demo_fallback_authorization.py`. It checks production with demo enabled/disabled, development without demo, explicit development demo, and invalid API-key denial. The implementation already guards demo fallback with `not settings.ONEBOARD_PRODUCTION_MODE`; this is regression coverage, **not a new production-code fix**.
- **Reproduce:** `python -m pytest -q tests/adversarial/test_production_demo_fallback_authorization.py` with test dependencies and a dummy `AUTH_SECRET_KEY`. No local test execution is claimed. Latest-head GitHub Actions must be checked before marking this change verified.
- **Unfinished Batch 1:** Real PostgreSQL simultaneous migration execution and cross-worker throttle contention have not been exercised; tenant isolation requires an endpoint-wide authenticated/unauthenticated matrix; account lockout remains susceptible to deliberate denial of service. No production certification or issue closure.


## 22 November 2026, 21:00 Dubai: disabled-account login information disclosure

- **Verified prior head:** `352a3e0fc40125e20ae6cf6064199a12179fec4b`. All three PR workflows returned successful completion: OneBoard verification run 45041549041, browser E2E run 45041549082, and browser inference feasibility run 45041549159. These results apply to the prior head only.
- **Security finding:** login previously returned a distinct 403 response for disabled accounts when a valid password was provided, revealing account status and not counting the attempt against the shared throttle. This was a different failure path from incorrect credentials.
- **Code commit:** `8798ceb76c402a8c113f398632ab57dcf28520ae` makes disabled accounts return the same generic 401 and record a failed attempt using the existing account-wide shared throttle; no session is issued.
- **Regression commit:** `132e4bed3789ae4d3d0dc268c130ae52df6653bd` adds parameterized tests for disabled accounts with correct/incorrect passwords, active accounts with incorrect passwords, and denial of session creation for disabled users.
- **Verification:** No workflow runs were returned for the regression commit when queried. This report commit will create a newer head. **Do not claim the new changes passed until every applicable workflow is green on that exact final head.** Reproduce with `python -m pytest -q tests/adversarial/test_account_throttle_logout_scope.py`, followed by complete verification and browser workflows.
- **Remaining Batch 1 blockers:** real PostgreSQL parallel migration and cross-worker throttle contention tests, account-lockout abuse resistance, full endpoint-wide tenant authorization matrix, and production HTTPS integration. No production certification or issue closure. PR remains draft.


## 23 November 2026: consolidated security/auth/schema engineering batch

**PR:** draft #8, branch `fix/p0-auth-tenant-isolation` only. This report is not a certification of a production multi-tenant deployment. No provider signups, external API calls, real data, spending, merging or deployment were performed.

### Exact prior-head evidence

Commit `8f31fd389fc7ac10a0a8b060e72e28d5635ddb87` completed all three PR workflows successfully:
- Verification: https://github.com/mihika-3159/OneBoard/actions/runs/45047416260
- Browser E2E: https://github.com/mihika-3159/OneBoard/actions/runs/45047416302
- Isolated browser inference feasibility: https://github.com/mihika-3159/OneBoard/actions/runs/45047416613

Those results **do not verify the current batch**.

### Engineering and regression commits

- `713f5fb6b543b8e2f1b4de92511c4c54cad2bda8`: Alembic revision `003_app_schema` provisions missing model tables on a fresh database, using a migration-scoped creation registry to avoid deleting previously existing tables on downgrade. The earlier revisions provisioned auth/throttle only. The initial bootstrap derives tables from current SQLAlchemy metadata, so future schema changes need explicit immutable revisions.
- `2d816c4bcf8e98c5563daeb204b89bfd737e1729`: production startup checks **every expected table and column** after confirming Alembic head, and rejects stamped-but-incomplete databases without creating tables.
- `0fb18910f537e635e98e6304eb05245e4e3f060e`: adds PostgreSQL Python driver dependency.
- `8b56abb0748102121f4be5db0affa896dfd28ee1`: disposable PostgreSQL tests for simultaneous Alembic upgrades, actual model table/column presence, ten-worker shared throttle race, and production schema check. These are **SKIPPED** unless `ONEBOARD_TEST_POSTGRES_URL` is explicitly configured against disposable Postgres.
- `6c98e31674acabd7c7050c1fae4c8e62500e330c`: account+source shared throttling prevents a remote account-wide failed-login flood from permanently denying a founder who presents the correct password from a clean source. A correct password clears the global counter. Failed password attempts still count account-wide across rotating sources.
- `77ab1309e9fc0682d4430948a258facc84e3ae64`: adversarial unit tests for blocked/disabled credentials, source-identity spoofing, lockout and valid-password recovery.
- `cbfd5fc3397ec8d71376a36c63b2553e05bd9ca7`: rejects demo reset if production mode is active, even when a conflicting demo flag is set.
- `0ae7634fda0445dc8a7962bd45018fed6f69925f`: runtime anonymous GET route security matrix and foreign-tenant workflow, agent, approval and integration mutation denial.
- `9459c62f98ec2aca8446d8d13c65380d1e1e676a`, `5f04295aa794514b3b4c646a6eacc5cc20b4e6b3`: SQLite-backed integration regression of five distributed wrong-password guesses, account throttle and a succeeding verified founder login from another source.
- `b8514d4fd0098289da49089ec19ac9311cf5f9aa`: rejects incomplete production schema even when manually stamped at Alembic head.
- `bf9b9b8e3632556a60868abd8caf311c9babcdc9`, `86f1f643e0dfdee32729491d10163899ab36bfdf`: production config now rejects zero/unbounded login windows, attempt counts and session expiration, with boundary tests.

### Observed CI regression and correction

Earlier batch head `0ae7634fda0445dc8a7962bd45018fed6f69925f`: verification workflow https://github.com/mihika-3159/OneBoard/actions/runs/45099407721 **FAILED** in api-tests (**1 failed, 306 passed, 24 skipped**); web-build and real Ollama jobs passed. Browser E2E and browser feasibility both passed on that earlier head. The failure was `tests/unit/test_production_configuration.py::test_production_startup_accepts_stamped_schema_without_create_all`, which assumed a database containing **only an Alembic version stamp and no application tables** was safe to start. This obsolete expectation directly contradicted the new fail-closed schema contract. Commit `e35d4759fccd0a55ffd7ee8716f3eae7f2edeb35` corrected the test to demand rejection, rather than weakening production validation. Its exact-head CI must be verified.

### Follow-up verification and database safety

- Corrected test head `e35d4759fccd0a55ffd7ee8716f3eae7f2edeb35`: all applicable workflows completed successfully: [verification 45099642145](https://github.com/mihika-3159/OneBoard/actions/runs/45099642145), [browser E2E 45099642184](https://github.com/mihika-3159/OneBoard/actions/runs/45099642184), and [browser feasibility 45099642341](https://github.com/mihika-3159/OneBoard/actions/runs/45099642341). This is **prior-head CI**, not final-batch verification.
- Commit `de92ee9e6f8fdc9a2d5cd1daee9a9b1b6c3e7149` adds a required explicit disposable localhost `oneboard_ci` database guard before the PostgreSQL migration subprocess starts, and imports the full model inventory into the Postgres assertions.
- This report commit creates another head. Recheck exact final SHA and all applicable workflows. No independent PostgreSQL process test was run by this assistant.

### Critical unfinished evidence and restrictions

1. Real PostgreSQL concurrency tests are committed but not yet wired into an applicable CI job. An attempted GitHub Actions workflow-file modification was blocked by tool safety checks; **do not claim PostgreSQL testing passed**. An authorized workflow edit must configure a disposable PostgreSQL 16 service and run `python -m pytest -v tests/integration/test_postgres_security.py` with `DATABASE_URL` and `ONEBOARD_TEST_POSTGRES_URL` both pointing to that dedicated database. No shared or production database may be used.
2. All applicable workflows on the **exact final report head** still require review. Older green runs cannot satisfy the strict gate; new-head CI pending or unavailable means remain in Batch 1.
3. Source+account throttling reduces remote lockout abuse, but shared NAT/source lockouts and distributed Argon2 CPU exhaustion remain. Trusted reverse proxy source configuration and rate-limit load tests remain unverified.
4. The Alembic 003 bootstrap uses SQLAlchemy metadata to provision previously missing tables. Real PostgreSQL initial upgrade, parallel upgrade, rollback behavior, constraints and index parity require verification before declaring migrations production-safe.
5. Endpoint-wide tenant isolation, role changes, HTTPS/cookie behavior behind a real reverse proxy, signup abuse, production backup/restore and external audit are not fully demonstrated. Keep seven tracked issues open. **Do not advance to Batch 2 or merge PR #8.**

Reproduction in isolated local/test environments: `python -m compileall -q apps/api tests alembic`, `python -m pytest -q tests/adversarial/test_login_throttle_recovery.py tests/adversarial/test_account_throttle_logout_scope.py tests/adversarial/test_security_route_matrix.py tests/adversarial/test_production_schema_guard.py tests/unit/test_production_configuration.py`, full `python -m pytest -v`, disposable Alembic upgrade/downgrade/upgrade, web build, browser E2E, and the explicitly opt-in disposable PostgreSQL suite.


## 23 November 2026: disposable PostgreSQL CI and schema integrity gate

- **Verified prior head:** `e54050ac0a29116dfceddb9660fecc8b6c28fd0b`. All three applicable PR workflows completed successfully: verification [45231373351](https://github.com/mihika-3159/OneBoard/actions/runs/45231373351), browser E2E [45231372875](https://github.com/mihika-3159/OneBoard/actions/runs/45231372875), and isolated browser feasibility [45231372922](https://github.com/mihika-3159/OneBoard/actions/runs/45231372922). The verification run's disposable PostgreSQL 16 job [137891497555](https://github.com/mihika-3159/OneBoard/actions/runs/45231373351) **passed all three integration tests**: concurrent Alembic upgrades, ten-worker shared login throttle, and production schema guard. This replaces the earlier report's statement that PostgreSQL CI was not wired up.
- **New regression commit:** `5d4459bd62c9fcf8774e003bb33d1b7aaf84b0cf` adds PostgreSQL schema index and unique-constraint parity assertions for all registered SQLAlchemy models. This targets the gap where table and column checks alone cannot detect absent uniqueness enforcement or indexes.
- **Current-head gate:** The regression commit's workflows were not yet returned at inspection time. This report update creates another head. Do not claim these new assertions pass until all applicable workflows are green on the exact latest SHA.
- **Unfinished security batch:** Endpoint-wide role/tenant mutation matrix, abuse-resistant signup/login under shared NAT and Argon2 CPU pressure, PostgreSQL downgrade/upgrade recovery, reverse-proxy HTTPS/cookie behavior, and operational backup/restore remain unproven. Keep PR #8 draft and all issues open. No live providers, real data, paid resources, deployment or merge.


## 23 November 2026: exact-head CI failure triage and index parity correction

- Head `ecec0fbc9513af515f6a99765e7aad54b56f35c0` **failed** two applicable workflows. Verification [45233378640](https://github.com/mihika-3159/OneBoard/actions/runs/45233378640) passed API, web build, and Ollama jobs, but the PostgreSQL job failed: 3 passed, 1 failed. New schema parity test expected `ix_business_memberships_business_id` while the migrated PostgreSQL schema has `ix_memberships_business_id`. This is a legacy index-name mismatch, not proof of missing index coverage. Browser E2E [45233378606](https://github.com/mihika-3159/OneBoard/actions/runs/45233378606) passed. Isolated browser feasibility [45233378611](https://github.com/mihika-3159/OneBoard/actions/runs/45233378611) failed in its qwen3-0.6b job during `npm install` of onnxruntime-node with external network `ETIMEDOUT`, before model tests ran. No inference correctness conclusion follows from that failure.
- Fix commit `9195f350b252a56b0161839951e2a89160f00bf7` compares PostgreSQL indexes by ordered columns and uniqueness instead of legacy SQL index identifiers, while still enforcing required model index semantics and unique constraints. This preserves the integrity gate rather than deleting it.
- **Current-head gate:** new workflows were not yet returned when inspected. This report commit creates a further head and must itself receive complete green CI. Do not advance to Batch 2, merge, or claim readiness. Browser-side inference remains experimental and is not approved as default; no new browser-model tests were added.


### 23 November 2026: PostgreSQL index parity failure and migration repair

- Verified **previous exact head** `c565becf8866a941fc098730451eda429c1fc8b9`: OneBoard verification run [45244352886](https://github.com/mihika-3159/OneBoard/actions/runs/45244352886) **failed** (PostgreSQL job `137937093202`, 3 passed/1 failed); browser E2E [45244352684](https://github.com/mihika-3159/OneBoard/actions/runs/45244352684) **passed**; browser inference feasibility [45244352677](https://github.com/mihika-3159/OneBoard/actions/runs/45244352677) **failed** (browser WASM and real-model CPU jobs). These checks do not verify subsequent commits.
- PostgreSQL failure reproduced in CI: `test_04_postgres_schema_constraints_and_indexes_match_models` found missing nonunique index on `user_sessions.token_hash`. Migration 001 built the session table without that model index; migration 003's `create_all(checkfirst=True)` correctly preserved existing tables but did not reconcile their indexes. Merely changing the test expectation would hide a real schema defect.
- Commit `eb4bc26f0f1d312220c125bb13d75e3eb8805e5d`: added Alembic revision 004 to create missing model indexes/unique guarantees without rewriting existing tables, recording exactly the newly created indexes for safe downgrade.
- Commit `faa3d8764519ffdd1ad39b40ef2261ae1968d26e`: updated PostgreSQL integration tests to expect revision 004 and check that a repeated upgrade preserves the repaired session indexes.
- **New-head verification pending** at report authoring time. All applicable workflows must be green on the same latest head SHA before any batch transition. Do not infer green from previous-head results.
- Browser inference experiment remains non-default and unapproved for the founder experience. Its failing CI remains a gate blocker; do not suppress its checks merely to advance.
- Remaining Batch 1 risks: comprehensive cross-tenant/role endpoint authorization, real shared-NAT abuse, legacy schema upgrades with data, HTTPS deployment behavior, and adversarial migration recovery. PR stays draft; no customer data or deployment.


### 24 November 2026: production schema guard regression after migration 004

- Previous head `313d1565d8ae584946a39a7dd8d1c8cd75c06ec2`: browser E2E run `45254840891` **success**, browser inference feasibility run `45254841119` **success**, verification run `45254840718` **failure**.
- Verification `api-tests` job `137973817476` reported **2 failed, 316 passed, 26 skipped**. Both failures in `tests/adversarial/test_production_schema_guard.py` were test-fixture staleness: the incomplete database was stamped `003_app_schema` after migration 004 became current, so the startup guard correctly rejected a revision mismatch before it could exercise the missing-table guard.
- Commit `f215c07ab8aad23f900926c9be9e073d2cc86465` changes the adversarial fixture to obtain the current Alembic script head dynamically and stamp that revision while deliberately leaving required tables absent. This retains the fail-closed assertion and checks that production does not call `create_all`.
- **New-head CI pending/unverified** at time of change. All applicable workflows must pass on the exact latest PR head before Batch 2. PostgreSQL concurrent migrations and index checks passed on previous head; no production deployment or live database was used.


### 24 November 2026: production schema index guard and PostgreSQL regression
- Exact prior head `08340172d241cef546795a8aee039f2b98e50859` verified green: verification run 45264559036, browser E2E run 45264558871, browser inference feasibility run 45264558976.
- Security fix `f49cfe588452e3f532d2f7677ecc819e5b11dd74`: production startup now compares model-defined index column signatures and uniqueness constraints against the migrated database, rejecting incomplete schemas even when Alembic reports head. No automatic production repair.
- Regression `a3b5dbc483836c2814fb080f83ccf2cacdc90a5e`: disposable PostgreSQL test simulates an absent session token index via an inspector shim, requires production startup to fail closed, then confirms healthy schema is accepted.
- Exact latest head at this report update: `a3b5dbc483836c2814fb080f83ccf2cacdc90a5e`. Workflow lookup immediately after commit returned no runs; CI is **pending/unverified**, not green. The following report-only commit also requires its own exact-head CI verification.
- Batch 1 remains open. Pending: full tenant/role endpoint authorization matrix, shared NAT abuse protection, migration failure recovery, HTTPS deployment verification. No live customer actions or external provider activation.


### 24 November 2026: founder-role enforcement, production signup abuse control, PostgreSQL recovery test

- **Exact pre-batch head:** `e6e2ab1c80cae6d628ba1ff51c28af8ba047f4ef`. Independently retrieved three completed successful workflows on that SHA: verification [45276068732](https://github.com/mihika-3159/OneBoard/actions/runs/45276068732), browser E2E [45276068700](https://github.com/mihika-3159/OneBoard/actions/runs/45276068700), browser inference feasibility [45276068792](https://github.com/mihika-3159/OneBoard/actions/runs/45276068792). These are **prior-head results only**.
- **Authorization changes:** commits `fc7df8716396c80a5ec1c9cfe82a06dbba3cdbd3`, `df9879a5eff2328799db53d9a4cd8aaeec6e6950`, `9a6144b0fa7352e1348cb84d11acb9006fc588c2`, `ca8226749cfc868c6fdf9ff782db84ca3adf9678`, `6c3b2b8f0dae253a6fe2fc2752194e703c6ab805`, `b9fbc74e6629ed3fab6b9106e451e29c82cb1b53`, `e01657a010b7ac4214c9bf23024f45c29bc9f3b5`: founder/owner/admin authorization for 11 workspace-changing operations across agents, workflows, council decisions, AI profile, memory, integrations and recorded outcomes. Existing ordinary authenticated reads remain available to members.
- **Adversarial role coverage:** commit `52d59ee9ffad8f42747753464117df97e9a0621f` adds real signed-session API tests using a `member` persisted in the database and a token claiming `founder`; mutations must receive 403 while authorized reads remain accessible. Tests are newly committed, not yet verified on the latest head.
- **Anonymous signup abuse:** commit `8fbc18cb140a90450e665aecac7e25583dbbb040` uses production-only shared database throttling per transport-source across email addresses, before costly Argon2id and resource creation; it persists the attempt before registration work and fails closed without a verified request client. Commit `356ee52941acee0185495446dcd542f8bed38bd7` covers per-source rotation, spoofed forwarded address, persistence failure and early refusal. Residual risk: shared-NAT lockouts, rotating source IPs, reverse-proxy trust settings, and abuse at the edge remain untested. Production default uses the existing login throttle budget and window; this is not a full anti-abuse system.
- **PostgreSQL recovery:** commit `88380ee9cc0e5ea8aa5a9a4fbfa846d443c095f3` adds a disposable `oneboard_ci` migration-004 downgrade/re-upgrade test checking that existing synthetic business, user, and session records survive and the session token index returns. No production/customer data is used.
- **CI gate:** On code head `88380ee9cc0e5ea8aa5a9a4fbfa846d443c095f3`, verification run [45331831378](https://github.com/mihika-3159/OneBoard/actions/runs/45331831378) and browser feasibility [45331831432](https://github.com/mihika-3159/OneBoard/actions/runs/45331831432) were queued, and browser E2E [45331831503](https://github.com/mihika-3159/OneBoard/actions/runs/45331831503) was in progress when checked. **Do not claim the new RBAC, registration or downgrade tests passed**. This report commit creates another latest head requiring fresh exact-head verification. No advance to Batch 2 until all applicable workflows finish green on the same final SHA.
- **Remaining Batch 1 blockers:** CI verification of this batch; broader authorization matrix and role-policy review, login abuse behind shared NAT and trusted HTTPS proxy, multi-tenant concurrency/load checks, migrations with legacy dirty data, and explicit HTTPS and backup/restore evidence. Keep issue #1 and other tracked issues open. Never merge PR #8, deploy, enroll third-party providers or spend money without approval.

Reproduction (isolated, disposable environment): `python -m pytest -v tests/adversarial/test_member_role_authorization.py tests/adversarial/test_registration_abuse_control.py`; full `python -m pytest -v`; `python -m alembic upgrade head`; dedicated PostgreSQL CI job `python -m pytest -v tests/integration/test_postgres_security.py` with matching locally bounded `DATABASE_URL` and `ONEBOARD_TEST_POSTGRES_URL`; web build and E2E workflows.


### 24 November 2026: CI triage and restored PostgreSQL auth referential integrity

- **Browser failure reproduced:** code head `356ee52941acee0185495446dcd542f8bed38bd7`, browser E2E run [45331688217](https://github.com/mihika-3159/OneBoard/actions/runs/45331688217), **8 failed**. Actual server traceback: `NameError: name 'settings' is not defined` in `apps/api/routers/auth_router.py` at the new signup throttle check, returning 500 to registration. Commit `3199070348a2571dccb61b57d04aecee2dbb33f9` adds the missing settings import. Its own browser E2E [45331972647](https://github.com/mihika-3159/OneBoard/actions/runs/45331972647) then completed **success**. This is prior-head evidence only; do not infer the later schema commits pass.
- **Confirmed migration defect:** Alembic revision 001 constructed `users`, `business_memberships` and `user_sessions` without their SQLAlchemy-model foreign keys. Even revision-004 schemas could admit orphan auth rows. This is a separate integrity gap from the repaired indexes.
- **Migration repair:** commit `85b48edf35003c60cf6e562e862425a1b128344b` adds revision `005_auth_foreign_keys` for four PostgreSQL `ON DELETE CASCADE` auth ownership constraints, preserving existing compatible constraints and tracking exactly what was added for safe rollback. It intentionally fails if existing legacy data are orphaned or a conflicting FK action exists; it never deletes customer rows. SQLite remains development-only and migration 005 does not retrofit SQLite table constraints.
- **Fail-closed runtime guard:** commit `427b8b84169495e7b49060e85cb56e8aaf9acd6b` adds production startup verification of model-defined foreign-key columns, target table, target columns, and delete action. A matching Alembic stamp without these constraints must be rejected.
- **PostgreSQL adversarial tests:** commit `89f2491395050c463daae91ff41e8c7575330b90` updates expected Alembic head to 005, checks actual PostgreSQL foreign keys, simulates missing reflected FK for startup rejection, verifies orphan-session writes fail, and checks synthetic business/user/session retention during 005+004 rollback and re-upgrade. Commit `18cd31da6fbf5b92c515c3afad24a9d1ea04948e` adds a disposable dirty-legacy migration test: an orphan must block 005 atomically, preserve the orphan and prior revision, and allow recovery once synthetic corruption is removed.
- **Exact-head CI gate:** These newly committed migration and abuse tests are **not yet independently verified**. GitHub did not return workflow runs immediately after code head `18cd31da6fbf5b92c515c3afad24a9d1ea04948e` was created. This report commit creates another PR head requiring full verification. Any failed/pending/cancelled applicable workflow keeps Batch 1 open.
- **Residual blockers:** member/owner role policy needs broader review; per-source signup limits risk shared-NAT denial of service; real HTTPS reverse-proxy behavior and trusted-client-IP configuration are unverified; production legacy-data migration may require manual non-destructive remediation; system backup/restore and external audit are unproven. Keep all seven issues open and PR #8 draft; no live providers, real customer records, external actions, or paid deployment.

Reproduction: `python -m pytest -v tests/adversarial/test_member_role_authorization.py tests/adversarial/test_registration_abuse_control.py`, `python -m pytest -v`, `python -m alembic upgrade head`, `python -m alembic downgrade base` and `upgrade head` on disposable SQLite, and full `tests/integration/test_postgres_security.py` on dedicated disposable local PostgreSQL 16 as configured in `.github/workflows/verification.yml`.


## 24 November 2026: active tenant, live membership revocation and founder-role gates

**Verified starting head:** `f86c3420d025667f214da12c11b1da415931b86d`, with successful applicable workflows: [verification 45332302483](https://github.com/mihika-3159/OneBoard/actions/runs/45332302483), [browser E2E 45332302579](https://github.com/mihika-3159/OneBoard/actions/runs/45332302579), and [isolated browser feasibility 45332302511](https://github.com/mihika-3159/OneBoard/actions/runs/45332302511). Those runs do **not** verify later commits.

**Authorization findings and changes:**

1. **Secondary-membership scope widening**: `enforce_tenant_boundary` previously accepted a resource in any workspace where the caller had an additional `BusinessMembership` if a DB session was passed. The API has no explicit active-tenant switch, and downstream operations use `current_user.business_id`. Commit `eea9719617afa007b54489054ed31436e6ecddc0` removes this unsafe fallback. A resource must now belong to the one authenticated active tenant. This is defense against future incorrect use of the helper, not evidence that every existing route was exploitable.
2. **Membership deletion did not revoke existing credentials**: valid signed sessions and API keys previously authenticated a still-active `User` even after their business membership was deleted. The same commit introduces live production tenant-membership validation for both credentials, with the recorded business owner retained as an explicit alternative. Commit `e6bda4e649ca0376443e5ef46528e12316242d21` also blocks *new password login sessions* for an account without active workspace authority, returning the same generic invalid-credentials response and recording throttling failures.
3. **Live role downgrade did not revoke founder privileges**: `require_founder_role` previously relied only on persisted `User.role`. Commit `6c371cbe0200f853ca51261d7f9f4ee503447ea1` now checks actual production membership role for founder-only mutations, unless the user is the recorded business owner. This prevents a downgraded membership from retaining privileges via old cookies, signed role claims or API keys. Legitimate member reads remain allowed.

**Regression coverage:** `3c4f16f999e052c8dd010825bb110df25b863b5b`, `07818636e0c2a7b93fa1848a7b275dd7bad2636b`, and `564e26fe70f95deeb86c74d898fe23552f07312c` add synthetic two-workspace auth tests for active tenant scope, bearer/API-key access after membership deletion, owner access, inactive users, live founder-role demotion and invalid login after membership revocation without creating a session. `169e9612ba1afa919698b1d1fb1cf09f15c3d5d4`, `171eb4cbd36f7b1c049c5dcc46b96eaa81db2dec`, and `aa6e1c9edb89298dba7030393b0de54fe1f67665` add and correct a dependency-graph audit requiring centralized authentication for every nonpublic API route and founder-level dependency for high-impact mutations. The audit checks the router definitions directly after CI showed that the shared app route inventory was empty during the pytest suite. The audit was not deleted or weakened to an unchecked status.

**CI evidence / gate:** On code head `169e9612ba1afa919698b1d1fb1cf09f15c3d5d4`, verification [45341017779](https://github.com/mihika-3159/OneBoard/actions/runs/45341017779) failed `api-tests` with **2 failed, 341 passed, 31 skipped**, both failures in the new route-inventory test because it inspected no routes; browser E2E and isolated browser feasibility passed. The first inventory change on `171eb4cb` still failed for the same problem. `aa6e1c9e` instead audits source router definitions. On `aa6e1c9e`, verification run [45341424291](https://github.com/mihika-3159/OneBoard/actions/runs/45341424291), browser E2E [45341424213](https://github.com/mihika-3159/OneBoard/actions/runs/45341424213), and experimental browser feasibility [45341424320](https://github.com/mihika-3159/OneBoard/actions/runs/45341424320) were still **in progress** at inspection. This report commit changes the head again: do **not** treat older-head green status as success.

**Scope and remaining blockers:** These changes mitigate two separable authentication risks (cross-tenant authorization scope and revoked/downgraded membership reuse) but are **not** a full independent security audit or production certification. Pending exact-head green CI; broader multiworker adversarial session/role tests on real PostgreSQL; trusted reverse-proxy and HTTPS origin behavior; shared-NAT throttling/CPU-abuse resistance; legacy account membership reconciliation; realistic migration/backup recovery and deployment validation. No production provider, customer data, live outbound actions, spending, or deployment. PR #8 stays draft; tracked issues remain open.

Reproduce in disposable CI: `python -m pytest -v tests/adversarial/test_tenant_membership_revocation.py tests/adversarial/test_route_auth_dependency_inventory.py`; `python -m pytest -v`; PostgreSQL `python -m pytest -v tests/integration/test_postgres_security.py` with dedicated `oneboard_ci` service; browser E2E and all applicable workflows on exact latest PR SHA.


### 24 November 2026: real PostgreSQL membership revocation regression

- **Prior code head `aa6e1c9edb89298dba7030393b0de54fe1f67665`:** verification [45341424291](https://github.com/mihika-3159/OneBoard/actions/runs/45341424291) and browser E2E [45341424213](https://github.com/mihika-3159/OneBoard/actions/runs/45341424213) completed successfully. The API job reported **344 passed, 31 skipped, zero failed**, including the new active-tenant, removed-membership, role-demotion, login revocation and route-dependency tests. The disposable PostgreSQL migration/concurrency job, frontend build and real Ollama job also passed on that SHA. Browser inference feasibility was still in progress at the time of this observation; no complete green gate is claimed for that head.
- **Prior report head `785eeec2fc8dae51284b97982775c287f3df1a53`:** verification [45341556780](https://github.com/mihika-3159/OneBoard/actions/runs/45341556780) and browser E2E [45341556805](https://github.com/mihika-3159/OneBoard/actions/runs/45341556805) completed successfully; experimental browser feasibility [45341556754](https://github.com/mihika-3159/OneBoard/actions/runs/45341556754) was still in progress when inspected.
- **New PostgreSQL test commit `2aec1b148270b4c827839832ac452ceb9cc22935`:** adds `test_11_postgres_rejects_revoked_membership_for_bearer_and_api_key` to the existing protected disposable PostgreSQL 16 suite. It creates synthetic primary/secondary tenants, validates live founder and bearer/API-key access, denies foreign-tenant access despite secondary membership, verifies immediate founder privilege loss after membership role demotion, and rejects both session and API-key access after deletion. Cleanup targets only synthetic rows. This extends the earlier SQLite auth tests to real PostgreSQL transaction and query behavior.
- **Latest-head gate remains unverified:** On `2aec1b14`, verification [45341690086](https://github.com/mihika-3159/OneBoard/actions/runs/45341690086) and isolated browser feasibility [45341690112](https://github.com/mihika-3159/OneBoard/actions/runs/45341690112) were queued, browser E2E [45341690106](https://github.com/mihika-3159/OneBoard/actions/runs/45341690106) running when inspected. The current report update creates an additional head and must receive fresh exact-head CI. Keep PR draft and Batch 1 open if any check is pending, failing or cancelled.


### 24 November 2026: distinct shared-NAT registration quota and fail-closed HTTPS API origin

**Verified previous gate:** PR #8 head `409ec3a6e5b6b043333786fde9865b596d06a44f` had all three completed successful workflows: [verification 45341751391](https://github.com/mihika-3159/OneBoard/actions/runs/45341751391), [browser E2E 45341751388](https://github.com/mihika-3159/OneBoard/actions/runs/45341751388), [isolated browser feasibility 45341751221](https://github.com/mihika-3159/OneBoard/actions/runs/45341751221). These are starting-head results, not proof of changes below.

**Blocker A, shared-network signup denial:** A public registration attempt previously counted against the `LOGIN_MAX_ATTEMPTS=5` source-wide limit, which meant five unrelated signups from a school, office or carrier-grade NAT could deny the sixth user for the login lockout interval. Commits `f061a9456ba8b280116cf248c6516b200812e86c` and `0ec07341d10ea6a15657753c588f959f24263f55` separate the registration source-wide budget (`REGISTRATION_SOURCE_MAX_ATTEMPTS=30`, allowed 10–100) from the tighter five-guess source+account login budget, retaining the shared PostgreSQL advisory-lock checks. This mitigates premature shared-NAT lockouts while bounding expensive anonymous account creation. It **does not** stop a malicious party from deliberately exhausting the 30-source limit or rotating source IPs. Tests in `tests/unit/test_production_configuration.py` verify the two limits independently, and a disposable PostgreSQL 16 test `test_12_postgres_shared_nat_registration_quota_across_workers` admits exactly 10 of 14 concurrent attempts under a lowered isolated test budget and rejects the other four. `50c4861b3fb3c78182cfbf902a977027ee63d116`, `b07e84289e6d9070567fc0638bf0a824ed4dd9cb` and `1e0cc29d036cf2a2a2897ac0a6db97cc352e2234` add the tests.

**Blocker B, plaintext/Host-header misrouting:** Previously production emitted HSTS and restricted CORS, but neither ensured incoming requests had trusted HTTPS ASGI scheme nor verified the API Host against an operator-selected public origin. Commits `f061a9456ba8b280116cf248c6516b200812e86c` and `e25e00e9ca04c6f0f504ef914f2687c478829b54` require a canonical `PUBLIC_API_ORIGIN=https://...` in production, reject unexpected or duplicate `Host` values with HTTP 421, and reject plaintext `scope["scheme"]` requests with HTTP 403 rather than trusting raw `X-Forwarded-Proto` or `X-Forwarded-Host`. Standard security response headers remain on rejection. `4b6ba5ceab6455adbc771fc4565f9f99afac5b1c` adds adversarial TestClient cases for spoofed/multiple hosts, insecure requests, and valid HTTPS. The code-level proxy trust contract and deployment acceptance checks are in `docs/PRODUCTION_HTTPS_AND_AUTH.md` (`e5d4c8f703de96c9183ba222a44df0cfd9395c35`). **External TLS termination, actual Uvicorn trusted-proxy IP allowlisting, edge isolation and external HTTPS validation are NOT proven**; this is only the application-side security guard.

**CI triage:** On code head `e5d4c8f703de96c9183ba222a44df0cfd9395c35`, [browser E2E 45342801359](https://github.com/mihika-3159/OneBoard/actions/runs/45342801359), the disposable PostgreSQL job and real Ollama job in [verification 45342801402](https://github.com/mihika-3159/OneBoard/actions/runs/45342801402) succeeded. The API job on the same head reported **363 passed, 33 skipped, 2 failed**: an older CORS configuration-test fixture omitted the new required `PUBLIC_API_ORIGIN`, and a newly authored test incorrectly expected a syntactically valid but unfamiliar custom HTTPS hostname to be categorically rejected. `6f878f0b83da14b2663915b5d9ea337884471785` updates the existing fixture. `ed0677ea159f20c0448ac59f5571e3ccd58258fb` fixes the expectation: an explicit valid custom HTTPS host is acceptable as configuration; only incoming Host mismatch is forbidden, as exercised by the actual request middleware tests. The runtime security checks were **not** disabled to make CI green.

**Execution / remaining gate:** Reproduce locally with `python -m pytest -v tests/unit/test_production_configuration.py tests/adversarial/test_production_cors_origins.py tests/adversarial/test_https_public_origin_guard.py tests/adversarial/test_registration_abuse_control.py`; full `python -m pytest -v`; dedicated disposable PostgreSQL `python -m pytest -v tests/integration/test_postgres_security.py`, and browser E2E. Exact-head verification after the fixture fixes and after this report commit is **not yet established**. Keep Batch 1 open until all applicable workflows finish successfully on the same latest SHA. No production account, customer data, live outbound integration, deployment, spending, merge or PR-ready transition. Residual shared-IP denial and real TLS/reverse-proxy exposure tests remain open; do not claim blanket Level 3 readiness.


### 24 November 2026: cross-account login abuse and plaintext API-key migration

**Strict gate at entry:** all three workflows were verified completed/successful on exactly
`71e63226458fd3e2674348cb1cd4aa8d4a32999a`:
[verification 45343087752](https://github.com/mihika-3159/OneBoard/actions/runs/45343087752),
[browser E2E 45343087818](https://github.com/mihika-3159/OneBoard/actions/runs/45343087818),
[browser inference feasibility 45343087750](https://github.com/mihika-3159/OneBoard/actions/runs/45343087750).
The isolated browser inference workflow is not an approved production browser-model experience.

**Security blocker 1, cross-account credential stuffing:** prior login throttling keyed by
source+account and account still allowed a client to rotate email addresses at a single
source and request unbounded expensive Argon2 checks. Commits
`b3395a675d4d88dc8111b1cc186f24594cc84314`,
`51acca9b59183750331e415ff79d27b4d0776092` and
`91bb5b623afc250b12ece941ffb481f182d98c5d` introduce a separate
production `LOGIN_SOURCE_MAX_ATTEMPTS` (default 60, configurable 20–200,
greater than the per-account limit). Every admitted attempt is counted and
committed via the existing shared PostgreSQL advisory-lock throttle *before*
account lookup or password verification; successful logins do not reset it.
Production denies login before hashing if no verified transport client IP is
available, and does not consume untrusted forwarded-for headers. Existing
per-account and account-global controls are retained. Tests:
`tests/adversarial/test_cross_account_login_abuse.py`,
`tests/unit/test_production_configuration.py`, and PostgreSQL
`test_13_postgres_shared_login_source_quota_blocks_email_rotation`.
**Residual:** a busy shared NAT may reach its 60-attempt budget, distributed
source IPs can evade it, and trusted edge capacity controls still require
live deployment validation. This is bounded abuse resistance, not a DDoS
guarantee.

**Security blocker 2, database-held plaintext API keys:** previously
`users.api_key` contained reusable, raw `obk_` credentials; any database-only
credential read could directly authenticate as that user.
`7844b719769885734f8c1aa723f80cf39d3a42b6` adds SHA-256 one-way
verifiers and bounded canonical key input checks in production lookup;
`0c586fd71e9b1068c446fbd5160e3ad729c7d559` stores verifiers on
registration and rotation and returns only the new raw rotated key.
`99c4b1e1ba33fd358d81a93ec9a69561180cfaa8` adds Alembic revision
`006_api_key_hashing`: canonical legacy keys are upgraded atomically without
changing what the client holds, while noncanonical/weak legacy keys block
deployment without data loss. The irreversible conversion refuses PostgreSQL
downgrade while hashed keys exist. Development-only legacy demo credentials
remain local; production does not match them. Commit
`8da1116b6ed869487d9a7291e038187ca5acc958` rejects production startup
when a manually stamped revision still contains plaintext/noncanonical API
keys. Tests include
`tests/adversarial/test_api_key_hashing.py`, PostgreSQL
`test_14_postgres_legacy_api_keys_are_hashed_without_losing_users`,
`test_15_postgres_rejects_weak_legacy_api_key_without_data_loss`,
and `test_16_postgres_production_guard_rejects_stamped_plaintext_api_key`.
Operational migration/rollback caveats are documented in
`docs/PRODUCTION_HTTPS_AND_AUTH.md`. **Residual:** cannot restore pre-006
plaintext keys by downgrade; a tested backup/restore and client key rotation
procedure remains unverified. No secret raw keys were committed.

**CI triage on code commit `b5007b89ae93510b41d5bdd0702786bf86fef558`:**
The API job in [verification 45344268938](https://github.com/mihika-3159/OneBoard/actions/runs/45344268938)
reported **384 passed, 36 skipped, 1 failed** because a new synthetic
successful-login test fixture was missing the `name` attribute. The disposable
PostgreSQL job reported **14 passed, 1 failed** because the migration-005
recovery test still asserted that `head` was revision 005 after introduction
of revision 006. These were test fixture / expected-head defects.
`d9e08496d50c48ce676dd66ea57779e930d6e35e` added the missing
fixture attribute and `2721080a00f7ed63d248143c10c43034fa928d64`
updated recovery's expected head to `006_api_key_hashing`.
No underlying security check was weakened to pass CI.

**Gate:** Verification, PostgreSQL, and browser checks on the final report
commit remain **unverified** at report creation; passing workflows on
`71e63226` do not satisfy checks on later commits. Keep Batch 1 open and
PR #8 draft until every applicable workflow on the *exact final SHA* is
completed successfully. All issue acceptance criteria remain open until
separately evidenced. This work used only synthetic CI/dev data. There was
no deployment, customer data, paid provider, merged PR, or outbound live
integration.

**Reproduction:** `python -m pytest -v tests/adversarial/test_cross_account_login_abuse.py tests/adversarial/test_api_key_hashing.py tests/adversarial/test_tenant_membership_revocation.py tests/unit/test_production_configuration.py`;
`python -m pytest -v`; disposable PostgreSQL 16
`python -m pytest -v tests/integration/test_postgres_security.py` with
validated local `oneboard_ci` URL; `python -m alembic upgrade head` and
SQLite downgrade/upgrade CI smoke; all browser workflows.


### 24 November 2026: follow-up CI failure triage for API key migration and startup guard

The initial new-batch code run [verification 45344268938](https://github.com/mihika-3159/OneBoard/actions/runs/45344268938) at `b5007b89ae93510b41d5bdd0702786bf86fef558` found two test-fixture problems: missing `name` on a synthetic login user (API: 384 passed, 36 skipped, one failed), and a stale migration 005 assertion after upgrade to head 006 (PostgreSQL: 14 passed, one failed). Fixed respectively in `d9e08496d50c48ce676dd66ea57779e930d6e35e` and `2721080a00f7ed63d248143c10c43034fa928d64`.

A subsequent [CI run 45344644850](https://github.com/mihika-3159/OneBoard/actions/runs/45344644850) on `87106d75b709a300f4b886d34b7b421c31cd65b3` exposed a **Python SyntaxError** in the newly added production startup API-key invariant SQL block. That is an application-code defect; no success was claimed. Commit `20ccf0364c2d281ad795d5dba7f13c700147986f` replaces it with syntactically valid SQL that checks for the `sha256:` prefix, exact verifier length, and lowercase hex characters using PostgreSQL `translate`. The committed file was re-read and the full return/create-all structure inspected. No authentication check was removed.

The security blocker status remains **implemented but not yet exact-head CI verified** after these corrections. The latest report commit also creates a fresh head requiring its own verification. All applicable PR workflows must complete successfully on precisely the same latest SHA before Batch 2 can begin. No deployment or real user data were used.


## 24 November 2026: four critical control clusters on PR #8

**Strict gate at start:** draft PR head `908c09444a39583e47fbc27a8e1b758dce9b2ff0` had all three applicable GitHub Actions workflows completed successfully. The batch remains on `fix/p0-auth-tenant-isolation`, PR #8 only; no merge, real customer data, paid services, provider enrollment, external actions or deployment.

### Critical 1: durable workflows, approvals and recovery

- New `WorkflowRun.idempotency_key` with tenant-scoped uniqueness and Alembic `007_workflow_idempotency`. Migration initially failed on legacy/bootstrap tables that already had the new column; revision `756141cbef652f02d0541ebd9f93cbf635115b63` reconciles existing columns/constraints, tracks only changes created by this revision for safe downgrade. `1f1adf719d99fd46c3c41e14240ac4ead6ab0909` tolerates reflected column order. Full disposable PostgreSQL migration/concurrency suite now passes.
- The workflow engine accepts a bounded client idempotency key, holds a PostgreSQL advisory transaction lock for concurrent first use, refuses reuse for a different workflow or dry-run mode, and returns the existing run to a retry rather than running it twice. Production non-dry-run execute requires `Idempotency-Key`. The browser reuses an in-memory key after uncertain network/5xx results. Founder-only `/api/workflows/runs/reconcile-interrupted` quarantines stale `running` states without replaying uncertain actions.
- New unit/adversarial tests and disposable PostgreSQL `test_17` and `test_18` confirm concurrent single-run and concurrent approval claim behavior; **18 PostgreSQL tests passed**. Existing DAG, approval checkpoint and dry-run tests remain enforced.
- **Limitations:** no genuine external effect dispatch is available, so exactly-once behavior cannot be claimed for unapproved third-party tools; browser reload discards the in-memory request key; paused runs need operator review.

### Critical 2: financial record accuracy and provenance, including UI

- Deterministic financial snapshot rejects invalid/missing/nonfinite/negative recorded amounts, flags unknown expense periods and invalid receivables, includes contributing tenant-scoped customer/invoice/expense IDs, currency, source and update timestamps. All figures are explicitly **user recorded, not independently ledger-reconciled**. Invalid inputs suppress health/runway claims; the council receives data-quality warnings.
- Found significant **frontend fabricated values** still shown despite backend improvements: Overview/Finance previously displayed fallback `18450` MRR, `132840` cash, `7.2` runway, invented customer growth, trend histories, pretend paid invoices, expenses, bank names, and an unverified accountability score. Replaced both tabs with authenticated tenant metrics, empty/error states, verification labels and no invented historical trend. Added strongly typed nullable financial data-quality fields.
- `tests/adversarial/test_financial_record_provenance.py` and `test_financial_frontend_truthfulness.py` verify the invalid-record response and lack of fabricated UI. An ORM default forced a synthetic None billing period to monthly; corrected fixture with an explicit persisted NULL. All current API tests pass.
- **Limitations:** bank transactions, FX normalization, ledger reconciliations, historical close and external audit are not integrated. Self-maintained data and derived computations must not be pitched as verified accounting balances.

### Critical 3: synthetic backup/restore and crash recovery

- New `scripts/verify_postgres_restore.py` has hard guards for disposable local PostgreSQL `oneboard_ci`, matching database URLs, explicit `ONEBOARD_CI_DISPOSABLE_RESTORE=1` and a separate scratch `oneboard_restore_ci` that must not already exist. Uses full custom-format PostgreSQL dump, SHA-256 manifest, scratch restore, all-table row hashes and counts, Alembic head 007 and schema uniqueness checks. Synthetic tenant, customer, expense, workflow definition and run are inserted, backed up, then deleted from the source to simulate damage. The scratch restore must contain the original rows. Cleanup targets synthetic IDs and the scratch DB it created.
- `tests/adversarial/test_disposable_backup_guards.py` tests refusal of remote/customer databases and corrupted manifests. CI runs the live disposable PostgreSQL 16 restore drill **after** its 18 passing migration and concurrency tests.
- Early runs failed: newer runner `pg_restore` emitted PostgreSQL 17+ `transaction_timeout` unsupported by PG16; runner `apt` lacked `postgresql-client-16`; first Docker wrapper had an unterminated quoted string. These were fixed by using an explicitly quoted heredoc wrapper invoking `pg_dump` / `pg_restore` from the already available official `postgres:16` CI service image. No restore assertions were disabled.
- **Successful proof on code commit `1be29a94700414dc165e146c5e9d1072c195f96e`**, GitHub Actions [verification run 45348904926](https://github.com/mihika-3159/OneBoard/actions/runs/45348904926): **pg_dump and pg_restore 16.16**, **18 PostgreSQL tests passed**, backup/restore output: **35 application tables, 38 records, SHA-256 validated, schema head 007**. The same verification run included 436 passing API tests and a passing frontend build.
- **Limitations:** this proves a CI-only synthetic restore, not an encrypted, durably retained offsite production backup system, retention schedule, RPO/RTO or recovery from provider loss.

### Critical 4: production deployment security guardrails

- New `TRUSTED_PROXY_IPS` production setting allows only explicit addresses, no wildcard/CIDR, duplicates or multicast; remote PostgreSQL URLs require `sslmode=verify-full`. `scripts/serve_secure_api.py` binds Uvicorn to loopback only, disables reload and trusts exactly configured proxy IPs. Existing production app Host, HTTPS scope, CORS, CSRF, secure-cookie, tenant membership, API-key hash and shared DB throttle controls remain in force.
- `tests/adversarial/test_secure_entrypoint.py` exercises remote DB TLS and proxy allowlist refusals, and `docs/PRODUCTION_HTTPS_AND_AUTH.md` records the deployment trust contract. No actual account or external TLS endpoint was created.
- **Limitations, hard deployment no-go:** a real certificate/HTTPS reverse proxy, external Host testing, private database network, provider age/no-card/zero-budget eligibility, persistent disk/offsite backups, operational monitoring and throughput have **not been verified**. This implementation must not be represented as a deployed or independently audited production SaaS.

### Exact-head CI and remaining gate

**Latest inspected executable code head:** `1be29a94700414dc165e146c5e9d1072c195f96e`. On that SHA:
- [OneBoard verification 45348904926](https://github.com/mihika-3159/OneBoard/actions/runs/45348904926) **completed success**: 436 passed / 39 skipped API tests, frontend build passed, real Ollama CPU inference job passed, 18/18 disposable PostgreSQL tests passed, and backup/restore completed with 35 tables and 38 records.
- [Browser E2E 45348905073](https://github.com/mihika-3159/OneBoard/actions/runs/45348905073) **completed success**.
- [Browser inference feasibility 45348905153](https://github.com/mihika-3159/OneBoard/actions/runs/45348905153) was **still in progress** at the final inspected code head. This is an isolated experiment only, not approval for default browser-side model downloads.
- This report update creates another latest head and requires its own applicable workflows. No advance to the high-priority batch without all green on that exact latest SHA.

**Remaining production blockers:** the four clusters have stronger, automated code-level controls, but real hosted TLS/proxy validation, approved eligible zero-dollar server inference/hosting, backup retention/recovery RPO/RTO, independent financial source reconciliation, authorized live integration/side-effect tests, and operational performance/security assessment are still **unverified**. Keep all seven issue acceptance criteria open. Level 3 is a no-go absent those real-world checks; the hackathon prototype/demo is a separate, lower-readiness target.

Reproduce: `python -m pytest -v`; `npm run build`; `python -m pytest -v tests/integration/test_postgres_security.py` on a disposable PostgreSQL 16 `oneboard_ci`; `ONEBOARD_CI_DISPOSABLE_RESTORE=1 python scripts/verify_postgres_restore.py` only with both matching explicitly validated localhost CI database URLs and PostgreSQL 16 client binaries; browser Playwright E2E and isolated inference CI.


## 24 November 2026: P1 engineering batch after critical CI gate

**Gate at batch start:** draft PR #8, `fix/p0-auth-tenant-isolation`,
commit `3fb8592a6f025b782be6187bcee3c3acc93f5c31`: all three GitHub
Actions workflows completed **success** (OneBoard verification,
browser E2E and browser inference feasibility). High-priority work only
began after this exact-head gate passed. No production secrets, real
customers, paid resources, new accounts, deployments, main commits,
merges or ready-for-review transition were performed.

### P1 #5: Ollama reliability and honest frontend errors

- `apps/api/routers/model_gateway_router.py` now makes model readiness
  tenant-specific: the requested chat model must be installed. A
  connected daemon with unrelated models does not count as real
  inference. Founder Command financial data now show source/verification
  status, and invalid or unconfigured figures are withheld from model
  prompts and from business-state output instead of fabricated.
- `apps/api/services/ollama_gateway.py` uses a two-slot bounded
  **per-process** concurrency gate with a three-second queue timeout.
  Overload is explicitly reported as `capacity_exceeded` with simulated
  output, not as a successful model response. Actual responses must have
  nonempty completed generation, the correct returned model when
  present, and a JSON object for structured requests. Missing model,
  malformed JSON, incomplete generation, 404 and timeouts remain
  explicitly labeled fallback. Prompts and provider exception messages
  are not logged.
- `apps/web/src/components/SettingsTab.tsx` distinguishes the selected
  model's availability and real benchmark status, with retryable errors.
  `tests/adversarial/test_ollama_backpressure_and_model_truth.py`,
  `test_founder_command_financial_quality.py` and existing gateway
  and offline tests cover these cases. Browser test
  `apps/web/e2e/p1-reliability.spec.ts` checks tenant-selected model
  readiness on a disposable founder account.
- **Unverified:** provider/region eligibility, offsite server-side
  inference, cluster-global rate limiting, target-hardware resource
  soak, long-term uptime, cloud fallback and live provider privacy
  terms. No browser-hosted model default was implemented.

### P1 #6: integration boundaries, bounded memory and restart monitoring

- `apps/api/routers/integrations_router.py` refuses fixed Northstar
  demo CRM/finance/GitHub data for any non-demo tenant or production
  request. Non-mock provider sync remains **501 not implemented** and
  sandbox refresh is clearly simulated. `IntegrationsTab.tsx`
  disables unsupported live sync, shows a visible retryable API error,
  removes fabricated prefilled chat examples, marks heuristic parsing
  as unverified and labels the in-memory email outbox undelivered.
- `apps/api/services/scheduler_service.py` now rejects nonfinite,
  missing and negative overdue invoice totals with an explicit
  data-quality alert. A scheduler that cannot start causes production
  startup failure rather than being silently marked active; no
  connection-sensitive exception text is logged. Alert facts still
  derive from tenant-scoped stored records on each GET, so the same
  alert can be regenerated after a process restart. **The job interval
  scheduler and email outbox remain process-local, not a durable
  distributed queue.** Documented in
  `docs/P1_ENGINEERING_ACCEPTANCE.md`.
- `apps/api/routers/memory_router.py` restricts public search to
  nonblank 1–2048-character queries and top-k 1–20. Internally, the
  engine accepts top-k 1–50 for existing security checks. The
  `MemoryChunk`/`MemoryDocument` same-tenant join eliminates the
  N+1 document query and excludes chunks pointing to a foreign tenant
  document. The query scans at most 1,000 recent chunks and explicitly
  flags `candidate_limit_applied`; this is **not** exhaustive
  old-document recall. New tests check 1,005 chunks, a single SELECT,
  orphan exclusion, parsing limits and no Ollama work on an empty
  tenant.
- `apps/api/services/workflow_engine.py` now validates every overdue
  invoice amount through the same deterministic money-validation
  policy used by financial snapshots. An invalid amount fails the
  financial workflow instead of producing an actionable total.
- Regression evidence: new `test_demo_integration_tenant_scope.py`,
  `test_scheduler_restart_and_invalid_invoices.py`,
  `test_bounded_memory_search.py` and
  `test_workflow_finance_quality.py`, plus browser E2E.

### P1 #7: verification breadth and public technical claims

- `apps/web/e2e/p1-reliability.spec.ts` adds Chromium browser tests
  for fixture access denial, exact selected-model readiness, replay
  of a workflow with a fixed idempotency key, honest sandbox UI, and a
  synthetic HTTP 503 integration failure with visible retry/recovery.
- `README.md` was reconciled against actual source and execution.
  Removed claims of deployed ChromaDB, cloud-provider inference
  fallback, SSE, immutable cryptographic ledgers, fully verified
  revenue/clients, fabricated Northstar accounting metrics and
  guaranteed seamless offline AI. Clarifies nine actual adviser
  roles, user-recorded finance, process-local monitoring, no live
  OAuth/provider sync, no public deployment certification, and
  zero browser-model-download default. New
  `tests/adversarial/test_readme_truthfulness.py` protects these
  distinctions.
- **Blocked or not independently verified:** clean Windows startup,
  external browser certificate and reverse-proxy network checks,
  sustained real CPU/GPU performance, provider authorization/scopes,
  actual live email or payment actions, operational alert/outbox
  persistence across sleeping hosts and replicas, external backup
  retention and a systematic audit of every README claim against
  a real deployed instance. GitHub issues #5–#7 remain open.

### Regression failures uncovered and corrected during the batch

1. New memory service top-k 20 bound conflicted with an existing direct
   internal tenant-isolation test using 50; the public endpoint remains
   bounded to 20 and internal direct calls allow at most 50.
2. Old tenant-isolation test expected a malformed cross-tenant chunk to
   appear with its title redacted; secure joined retrieval now **omits
   such rows entirely**. The test was strengthened to assert no chunk
   content or document title leaks, not weakened to return the orphan.
3. An adversarial test attempted to persist SQL NULL into
   `Invoice.amount`, which is NOT NULL. Replaced that impossible
   fixture with an isolated mock to exercise the defensive validation
   path without weakening database constraints. No product guard was
   disabled to make tests pass.

### Exact CI evidence (prior to this reporting commit)

**Last tested code head for this batch:**
`1e4517befb7d495aa6c28ecace672e81eee090c5`

- [OneBoard verification run 45352376857](https://github.com/mihika-3159/OneBoard/actions/runs/45352376857):
  - Python API/unit/adversarial/integration: **495 passed, 39 skipped,
    4 deprecation warnings** on exact code head.
  - Frontend TypeScript/Vite production build: **passed**.
  - Disposable PostgreSQL 16 concurrency/migration suite:
    **18 passed**.
  - Disposable PostgreSQL custom dump/restore:
    **35 application tables, 38 synthetic records, SHA-256 validated,
    schema head 007**.
  - The dedicated small real-Ollama CPU job was still completing at
    the time of this report's creation; check the workflow's conclusion
    rather than assuming its final status.
- Browser E2E: [run 45352376668](https://github.com/mihika-3159/OneBoard/actions/runs/45352376668)
  was in progress at report drafting.
- Browser inference feasibility: [run 45352377462](https://github.com/mihika-3159/OneBoard/actions/runs/45352377462)
  was in progress. This legacy experiment remains isolated and is
  neither a default user-hosted inference plan nor hosting approval.

**Final strict gate:** this TEST_REPORT.md edit creates another PR head.
It must separately pass all applicable workflows on **that exact new
head** before any new engineering priority batch begins. A pending,
failed, skipped or unavailable check is not green. Do not close any of
the seven GitHub issue acceptance criteria without full proof.

## 24 November 2026: single-commit external deployment safety gate

Starting PR #8 head: a450074ac175aaa2665aaf404b010b8738a76780.
All three PR workflows had completed successfully before changes began.

This single, atomic engineering commit adds:
- Production Ollama URL origin validation. The default server-side loopback
  model remains permitted; arbitrary public URLs, credentialed URLs and
  metadata/internal hosts are blocked. Remote HTTPS requires a separately
  pinned hostname and an explicit owner-controlled approval flag.
- An opt-in external HTTPS probe: safe GET requests to the exact authorized
  public API origin with real TLS verification, HSTS, Host and forwarded
  header checks. It cannot run without TWO operator actions.
- An opt-in production PostgreSQL streaming backup piped to age encryption
  without writing plaintext dumps. Requires explicit owner approval,
  local private directory, verified remote DB TLS, checksum manifest and
  no overwrite. Ciphertext verification is offline and DOES NOT prove
  decryptability or successful restoration.
- An example, not activated, local Caddy HTTPS reverse proxy configuration.
- Regression tests and an explicit external release no-go checklist.
- Local .env example updated to remove fictional unused cloud failover keys.

External requirements remain UNVERIFIED and must not be marked complete:
1. Legal, minor-eligible zero-cost/no-card hosting with persistent PostgreSQL
   has not been chosen, approved or provisioned.
2. No owner-approved, free and reliable remote server-side inference provider
   is deployed; no browser model download is introduced.
3. No actual public HTTPS certificate, reverse-proxy isolation or ingress
   scan has been performed.
4. No production encrypted offsite backup, retention policy or independent
   real-host restore test has been executed.

No new provider accounts, external services, live customer data, real
backups, payments or deployments were created. No main branch changes,
merges or ready-for-review transition. PR #8 stays draft. The experimental
OVHcloud tests are not provider approval.

Current commit CI status at report creation: PENDING until all applicable
GitHub Actions are green on the exact final head. Previous-head green checks
do not verify this new code.

## 24 November 2026: five-area durability and indexed-search engineering batch

Prior PR #8 head f80592767143d935eb518452e64271b02ce1ff2b: verification, browser E2E and isolated browser feasibility workflows all completed success. Work started only after that strict gate was green.

Prepared related production code and adversarial tests for: (1) operator-approved encrypted restore into a scratch localhost database, (2) persisted tenant alert snapshots and resolved history with PostgreSQL advisory transaction locks, (3) a real, founder-confirmed and idempotent user-supplied CSV customer import with strict validation but no live provider calls, (4) a durable pre-dispatch workflow execution checkpoint and no-replay recovery, and (5) PostgreSQL GIN full-text search across older document chunks plus tenant/date indexing.

Files include migration 008_operational_durability, production models, services and routes, UI import, synthetic tests and docs/RELIABILITY_BATCH_5.md. Existing PostgreSQL tests now expect schema head 008 and include tests of indexed retrieval beyond 1,000 chunks and concurrent import. The synthetic PostgreSQL dump/restore script now expects the new migration head.

All new operations are non-deploying source changes. No real encrypted backup, external provider enrollment, offsite store, model access, customer import, money, outbound send or production restore occurred. The new restore drill is not executed against any real database.

CI STATUS AT CODE AUTHORING: pending on the exact new head until GitHub Actions finishes. Do not advance beyond this batch until every workflow is green; repair failures with focused follow-on commits without bypassing tests.

UNRESOLVED EXTERNAL BLOCKERS: actual eligible no-card zero-dollar hosting and storage, real encrypted offsite backup retention and independent restore on approved infrastructure, scheduling during free-tier sleep, live provider OAuth/scopes and real sync, genuine third-party exactly-once effects, and measured deployed large-corpus semantic retrieval.


## 24 November 2026: financial evidence, tenant quotas, Windows and acceptance

**Strict start gate:** latest PR #8 SHA
65a491cbfc0780dc28ba5ec29c28c3252bcb23f3 had all three applicable
GitHub Actions workflows completed/successful before this work.

**Financial evidence**: introduced founder-only, read-only CSV comparison
for tenant invoices, expenses and cash, with strict date, duplicate,
currency, finite amount and size checks. Outputs identify mismatches,
include SHA-256 source identity, never touch invoice state and explicitly
say independently_verified=false. A user-uploaded statement is NOT an
authenticated banking or audit source. Source verification against a
trusted external provider remains unproven.

**Multi-tenant resource limits**: persistent per-tenant/per-resource
sliding window budgets (fixed windows) with PostgreSQL transaction
advisory locking on selected expensive production endpoints. Budget
limits: 30 AI commands/min, 120 memory searches/min, 6 imports/5min,
20 reconciliation checks/min. HTTP 429 includes Retry-After. New
disposable PostgreSQL concurrent regression checks 12 competing
sessions, 4 accepted/8 rejected when set to a synthetic 4/min cap,
and another tenant accepted. This is not a cluster-global CPU/GPU cap,
DDoS mitigation or measured live hosting performance.

**Clean Windows**: new windows-latest GitHub Actions workflow performs
fresh Python/Node install, frontend build, Alembic migration, finance
and quota tests, and a real subprocess localhost Uvicorn startup with
two synthetic account registrations, business isolation and explicit
financial unverified output. It produces an acceptance receipt, destroys
the child process and never reaches a paid provider.

**Independent acceptance**: new acceptance-evidence workflow creates a
machine-readable commit-tagged matrix and explicitly refuses to certify
Level 3 on self-authored CI. An independent assessor has NOT reviewed
this code or an owner-approved deployed instance. Formal external
review, financial authentication, real load testing, TLS, offsite
restore, eligible hosting and provider validation remain NO-GO items.

**Migration**: added Alembic 009_resource_budgets with a safe journal
to avoid destroying model-bootstrap-created objects, updated head
checks, downgrade roundtrips and disposable PostgreSQL restore
expected revision. All existing verification tests remain enabled.

**CI at authoring time**: new exact-head checks PENDING; never infer
success from the old green head. Keep PR #8 draft, unmerged and all
partially evidenced issue acceptance criteria open. No real customer
data, payment, service signup, external provider action or deployment.


### 24 November 2026: actual CI results and fixes for the four acceptance controls

**Verified code head before report update:** cb666da3edd58089731f617a526f9c9c7bf1417d.
All FIVE applicable workflows completed successfully on this exact head:
- OneBoard verification run 45376440122: API 554 passed, 42 skipped, 4 warnings;
  frontend TypeScript build passed; real small-model Ollama CPU inference
  passed; disposable PostgreSQL 21 integration/concurrency/migration tests
  passed. PostgreSQL full dump/restore recovered 40 application tables,
  42 synthetic records, verified SHA-256, schema revision 009.
- Windows clean installation run 45376440153: fresh Windows Python 3.11
  and Node 20 dependencies installed, frontend built, Alembic upgraded a
  disposable SQLite database, 20 focused financial/budget tests passed,
  and real local Uvicorn startup/HTTP registration, two-tenant isolation,
  unverified finance reconciliation and JSON receipt passed.
- Browser E2E run 45376440177: completed success.
- Isolated browser inference feasibility run 45376440145: completed
  success. This experiment is NOT an approved default model architecture.
- Acceptance-evidence run 45376439962: completed success; its artifact
  intentionally records production_level_3=NO_GO, not an independent audit.

**Fixes made while testing:** initial code commit
3c20bc12070faf3c7a991880167f502f29fb427c had a test using NaN in
a NOT NULL SQLite invoice column. SQLite converted the NaN to NULL
before the validation logic ran. Commit
16bd3c5036a069d70e9b734f3c706a58204ac234 changed the synthetic
fixture to infinity, preserving the nonfinite adversarial assertion.
The first Windows smoke then found a real Win32 file-handle lifecycle
error: the parent process attempted to delete its still-open Uvicorn
log. Commit cb666da3edd58089731f617a526f9c9c7bf1417d explicitly
closes the parent handle before unlink. No tests or checks were removed.

**What CI supports:** source-file comparison with discrepancy flags,
tenant-scoped cross-worker request budgets, genuine clean Windows
start/build and synthetic end-to-end smoke, and reproducible transparent
automated acceptance evidence. None of these prove independently
authenticated bank records, full deployed host resource fairness,
a third-party security audit, real financial settlement or independent
production acceptance. Those external requirements remain open.
No live provider, customer data, payment, deployment or third-party
action was used.

**Exact-head caution:** this report-only commit changes the PR SHA and
must pass all five applicable workflows again before any further batch
can begin. Keep PR #8 draft, unmerged and Level 3 release NO-GO.


## 25 November 2026: Batch A correctness, truthful UI, outcome provenance and encrypted restore

**Strict batch-start gate:** prior PR #8 SHA
3bc4d70237e0e744e9278ecacad8a5d4b2cb5763 had all FIVE
applicable workflows completed/success. Work remained on the draft
fix/p0-auth-tenant-isolation branch.

- Fixed encrypted operator restore drill's stale revision requirement
  from Alembic 008 to current 009. Added CI-only ephemeral age key,
  encrypted PostgreSQL custom dump, real decrypt/pg_restore into a
  new local scratch database, schema-head verification and cleanup.
  Synthetic CI is NOT offsite disaster recovery.
- Fixed duplicate execution from Workflow Studio approval handler:
  it now displays the already resumed run returned by the approval API
  and never triggers a fresh executeWorkflow call.
- Replaced static Operations commitments, customer/pipeline counts,
  fake deadline claims and hard-coded customer details with
  authenticated tenant-owned /api/business/operations results.
  The legacy mock CRM response remains an object with a contacts
  list and is never reused for real workspace operations.
- Removed false outcome-verification claims and scorecard increments
  from founder-supplied observations, requiring an exact prediction
  metric, finite value, bounded history and explicit
  founder_reported_unverified provenance. Historical unverified
  outcomes cannot advertise independent verification to real users.
- Removed fabricated adviser performance, confidence and customer
  health defaults, and removed UI placeholders such as 9.2% error,
  72% prediction error, 50 qualified leads and at least one tracked
  prediction. Unknown performance is explicitly unknown.
- Added adversarial data-boundary and no-fabrication tests, UI
  execution invariants, and a Playwright new-founder real Operations
  empty-state test. See docs/BATCH_A_CORRECTNESS.md.

**CI for the exact Batch A commit:** PENDING. Re-run all five workflows
and repair failures rather than treating the previous green commit as
proof. No production deploy, real customer data, offsite storage, provider
enrollment or payment used. PR remains draft and unmerged. External
financial authenticity and independent production acceptance are open.


### Batch A exact-head execution results: 25 November 2026

**Verified green code head:** 3bd9a2f9ee19e4e70e6c738bde421aaa35dfb166.
ALL FIVE GitHub Actions workflows completed/success on the same SHA:

- OneBoard verification, run 45532793042: 568 Python tests passed, 42 skipped,
  4 warnings; frontend build and real small-model Ollama inference passed;
  21 PostgreSQL integration/migration/security tests passed. Normal PG16
  logical restore checked 40 tables, 42 synthetic records, SHA-256 and
  Alembic head 009. NEW real age-encrypted PG16 custom backup, age
  decryption and restore into freshly created localhost scratch database
  passed, recovering 41 schema tables at revision 009. This is NOT offsite DR.
- Windows clean installation/startup, run 45532793076: completed/success.
- Real-browser E2E, run 45532793043: completed/success, including
  new real-founder Operations empty-state and demo-data denial.
- Isolated browser inference feasibility, run 45532793141: completed/success;
  not approved/default inference architecture.
- Acceptance-evidence, run 45532793045: completed/success, intentionally
  reports production Level 3 NO-GO and no independent reviewer sign-off.

**Test failures found and corrected rather than bypassed:**
1. The workflow-approval UI invariant test falsely matched a comment
   containing a removed executeWorkflow reference; the comment was rephrased
   and the strict no-second-dispatch assertion remains.
2. The encrypted PG restore initially failed because the Docker-based PG16
   client did not keep stdin attached. Added Docker -i so age-decrypted
   archive bytes reached pg_restore. The genuine roundtrip then passed.
3. New Operations Playwright test looked for "Operations" instead of the
   actual "Operations & CRM" sidebar item. Fixed the selector, retained
   the real browser test and confirmed green.

**Unresolved external Level 3 gates:** independently authenticated
financial sources, eligible real hosting and HTTPS, offsite encrypted
backup retention/recovery, live provider OAuth/sync and independent
production review. No real customer data, payments, provider signups,
deployments, merges or main-branch changes occurred.

**Exact-head caution:** This report-only commit generates a fresh SHA.
All five applicable checks must pass on the new SHA before Batch B
may begin. PR #8 remains draft.



## 25 November 2026: Batch B increment 1 (capacity and request admission)

Start head d9440b5dc0091b720ea5836531a6d6beeb7c4332: all five observed workflows completed success.
Adds PostgreSQL session advisory-lock admission across API workers for both
chat and embedding HTTP calls, plus tenant request budgets for workflow
generation/teaching/execution, agent generation/testing and document upload.
Includes disposable PostgreSQL lock saturation/release regression and policy
bounds tests. SQLite retains process-local inference limits. Provider-side
computation after connection loss/cancellation, external load, scheduler leases,
transactional outbox, storage quotas and DB-level tenant isolation remain open.
New code CI: NOT YET RUN at authoring. This is partial Batch B, not certification.


## Batch B increment 2: durable execution, local outbox, quotas and relational isolation

Adds persisted recurring monitor claims and next-due times, owner fencing,
crash lease expiry, PostgreSQL execution locks, and local-only transactional
invoice-reminder draft outbox with SKIP LOCKED processing. No external
delivery or exactly-once provider guarantee is implemented. Adds per-tenant
200 documents/50 MiB combined raw+chunk UTF-8 text/20,000 chunks, 200
workflows and 100 agents; advisory locking spans storage commit. Document
ingestion now commits parent and chunks together so the quota lock is not
released mid-ingestion. Adds council admission and PostgreSQL composite tenant
foreign keys for document chunks, workflow runs, approvals and draft intents.
Legacy violations are not deleted or certified; constraints apply to new
writes. Full RLS/read isolation and external provider delivery remain open.
Migration 010 and restore checks updated. All new CI evidence pending.


### Batch B increment 3: scoped RLS, adversarial and browser coverage

All five workflows passed on increment 1 (96825d19f27bf2a9f90ad308a77681d2f02178bb).
Adds transaction-local tenant context after authentication, restored after
commit/rollback, and PostgreSQL row policies for tenant-owned application
tables. These are defense in depth for scoped requests: authentication and
unscoped maintenance sessions are not subject to tenant filtering, and
superusers/BYPASSRLS roles bypass PostgreSQL RLS. Deployment must verify a
non-superuser/non-BYPASSRLS runtime role and separate maintenance privileges.
New tests cover stale lease fencing, concurrent claims, rollback of draft
intent, quota bytes and tenant separation, cross-tenant FK denial, restricted
role RLS, and browser tenant outbox isolation. All new tests are unexecuted
at authoring. No independent certification, real provider effects, or deployment.


### Batch B CI repair

Increment 2 PostgreSQL CI exposed migration-test drift: relative downgrade
counts targeted the wrong historical revisions after adding 010, leading to
a cascade of subsequent fixture errors. Replaced relative counts with the
same explicit historical revisions the tests already asserted. No security
assertions or tests removed. Full exact-head CI required again.


## 25 November 2026: Batch C start and indexed memory

Batch B exact head 6c451f5635b4c921cc6966c8852c7b874ade9d53: all five workflows completed success.
577 API tests, 25 PostgreSQL tests, 15 browser E2E tests passed; frontend,
Windows, disposable plaintext and encrypted PostgreSQL restore, real
small-model Ollama and browser feasibility completed. Batch C adds actual
model embeddings with indexed four-band angular LSH and cosine reranking,
bounded explicit indexing and atomic chunk storage. Legacy unindexed data
remains searchable lexically, not presented as genuine semantic recall.
CI pending for new head; no live services or independent certification.


Batch C increment 2: append-only user-reported settlement evidence with
source digest/reference, cumulative invoice bound, explicit FX provenance,
settlement-date period consistency and per-currency period totals. Does not
mutate invoice payment status or assert bank authentication. Offline provider
scaffolding uses a dedicated AES-256-GCM key, tenant/provider/scope/expiry AAD,
read-scope allowlists and persistent idempotent intents; no dispatch, OAuth
verification or provider contact. New CI and adversarial tests pending.


Batch C increment 3: owner-gated paginated export (excludes credential
fields and derived vectors; not a point-in-time snapshot), opt-in automatic
document retention, per-document deletion including vector rows, and
password/explicit-confirmation workspace application-row deletion. PostgreSQL
request transactions and monitor acquire tenant lifecycle locks to coordinate
deletion with in-flight writes. Backup copies, external systems, arbitrary
secret text embedded in user content, and physical storage erasure are not
certified. Sensitive validation responses are redacted. New CI pending.


Batch C increment 4: automatic bounded genuine embedding backfill, validated
evidence-content SHA-256, local provider credential revocation/cancelled
intents, additional quotas and no-store sensitive endpoints. CI pending.


Batch C increment 5: adversarial SQLite tests, PostgreSQL old-synonym/index
and tenant deletion tests, and browser owner export/deletion regression.
No external provider was registered or called by this engineering run.
Model semantic quality/recall, real provider authorization, external backup
erasure and independent certification remain unverified. CI pending.


Batch C CI repair: export-secret assertion now checks actual credential
column names and fixture values rather than matching the harmless
secrets_excluded metadata label. Added ingestion rollback fault injection
and scheduled-index separate event-loop gateway coverage. PostgreSQL
migration/concurrency job had passed its tests on the preceding head;
full final-head verification still required.


Batch C test evidence before final exact-head rerun: commit
11eae3e3ddaaa2de45bc5f8861c81516b0abc039 passed all 27 PostgreSQL tests,
16 browser tests, Windows startup, frontend build and disposable plaintext
and age-encrypted backup/restore (49 application tables, 49 records,
revision 011). Its API suite reported 580 passed and one faulty
credential assertion, now repaired. Dedicated local CPU embedding smoke
added to check actual model vector generation, relative similarity,
indexed persistence, retrieval and tenant separation using synthetic
data only. This is not large-corpus recall or independent production
certification. Final-head CI pending.


## 25 November 2026: Batch D mandatory integration acceptance

Batch C exact head c6551069cc3eeb2aad48e2a8d821930e3fcb6135: all five PR workflows completed successfully.
Modernizes the complete existing Ollama integration suite, including nine
live API tests and two additional authentication/isolation regressions.
Live API starts a new migrated disposable SQLite application with real
cookie sessions, CSRF, synthetic founders, and actual local models. Full
live inference rejects hash fallback and latency benchmark rejects simulated
results. Dedicated job requires 20 original gateway tests, 5 smoke/embedding
tests, 11 authenticated live HTTP tests and 27 PostgreSQL tests with zero
missing/skipped/failed cases. Ordinary offline suite intentionally skips
live infrastructure tests. Exact new head CI pending; not production certification.


Batch D increment 2: structured request IDs, route-template/status/latency
logs (no body, query, credential or raw tenant identifier), founder-only
tenant diagnostics and production benchmark quotas. Monitor schedule uses
UTC and configured interval with durable next-due time. Dedicated PostgreSQL
job adds six synthetic tenants, two actual HTTPS application workers,
20-second sustained request workload, idempotent execution, quota exhaustion,
cross-tenant denial and stop/restart persistence; reports median/p95 and
request counts. Local CI TLS is not certification of public edge TLS.
CI pending. No deployment or external actions.


Batch D increment 3: mandatory browser inventory and zero flaky/skip gate,
actual user-facing command, import, memory, workflow, agent and settings
controls with a separate all-eleven-tab navigation test; truthful memory
upload label (stored chunks are not necessarily embedded), accessible
agent/command inputs, expanded auth route inventory, cancellation/UTC and
test-gate fault tests. Required Python dependency audit, locked Node audit
(high/critical fail), high-confidence tracked credential detection and
Dependabot update configuration. Secret scan is checkout-only, not a
complete history audit. Existing disposable restore safety and fault
checks preserved. CI pending.


Batch D repair: the full Ollama gateway and smoke suites passed 20/20 and
5/5 (zero skips) on d147de9. Its live API mutation failures exposed missing
CI cookie Origin allowlist; corrected in 8068c38. On 8068c38, PostgreSQL
27/27 and both restores passed, plus measured 2,324 HTTPS requests over
20.17 seconds (six tenants, two workers, 401 expected quota denials, zero
unexpected errors, median 13.7 ms and p95 22.5 ms), with restart verified.
Expanded browser tests exposed real upload CSRF defect: now uses the
central authenticated multipart client. Browser fixture Origin explicitly
allowlisted only in CI. Removed hardcoded demo resolution text; founder
must supply actual resolution. Audit reported vulnerable cryptography
48.0.1, pip 24.0 and setuptools 79.0.1; minimum fixed versions from its
advisory output are cryptography 50, pip 26.2 and setuptools 84.1.
No advisory ignored. Mandatory exact-head rerun required.


### Batch D verified intermediate evidence and final repairs

On 8068c38 the mandatory live gateway suite passed 20/20, separate
smoke/embedding suite 5/5, and authenticated live API suite 11/11,
including the nine modernized tests and two negative auth/tenant tests.
All three suites had zero skips (verification run 45548545205).

On d9f582b28c2124e3280fbe5733b85a2a29d11d86, browser run
45549050635 passed all 18 tests with zero skips/flakes. Verification
45549050568 recorded 593 offline Python tests passed, 51 skipped
(infrastructure suites separately gated), 27/27 PostgreSQL tests,
49-table/49-record SHA-256 checked plaintext and encrypted restore at
Alembic 011, and 2,072 actual local HTTPS requests over 20.15 s with
six tenants, two workers, p95 33 ms, median 19.9 ms, 338 expected
quota denials, zero unexpected errors, and restart persistence.
Tracked-file scan: 214 files, zero high-confidence credential hits.
Python audit: no known vulnerabilities after dependency repairs.
Node audit was NOT green: high-severity Vite and associated advisories
remained. Fixed on 9dec40c by regenerating the npm lock with Vite 8.3.8,
compatible React plugin, patched selector parser and Node 22; removed
unused react-router dependency. No advisory suppression. Windows and
browser/build workflows use the new supported Node version.
37c5c6a additionally prevents a backup manifest collision from deleting
a pre-existing manifest and rejects symlink verification, with regression
tests. Final exact-head CI must pass before accepting Batch D.
No production deployment, real customer data, provider signup,
paid resource, external delivery or independent certification.


## Batch E: 25 November 2026

Start exact SHA e2b78a0d792ef4d5eceeb8400aeeed7ebb62c0d2: five workflows green. Increment 1 introduces
migration 012 with fail-closed unscoped content-table RLS for non-owner
roles, explicit owner maintenance, indirect sync-history RLS, production
runtime role admission, owner-approved provisioning, scoped background
jobs with tenant failure isolation, durable fair indexing cursor and opt-in
daily/weekly workflow schedules (IANA timezone, DST gap skip/fold once,
stable idempotent due slot, coalescing, pause on uncertain/approval run).
Auth directory and global coordination remain unscoped by design.
CI pending, no production credentials or role provisioning outside disposable CI.


Batch E increment 2: bounded repeatable-read snapshot export, opt-in
resolved alert/expired session retention (never financial/audit evidence),
migration 013, indexed Hamming-radius-one multiprobe retrieval and
credential revalidation at scoped PostgreSQL transaction boundaries.
Explicit workspace deletion obtains exclusive lifecycle lock from the
first scoped transaction; schedule configuration never waits while
holding a lifecycle lock. CI pending.
