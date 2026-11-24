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
