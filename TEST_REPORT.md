# OneBoard independent test evidence (2026-11-03)

Scope: Issue #7, draft PR #8, previously verified head `4fb422c`. This report is **not a production release certification**.

| Check | Result | Evidence |
|---|---|---|
| Python syntax | PASS | [Verification](https://github.com/mihika-3159/OneBoard/actions/runs/41415737965) |
| Pytest | 108 PASS, 17 SKIPPED, 2 warnings | Same verification run |
| Alembic upgrade/downgrade/upgrade on disposable SQLite | PASS | Same verification run |
| Frontend TypeScript/production build | PASS | Same verification run |
| Chromium Playwright | 3 PASS | [Browser E2E](https://github.com/mihika-3159/OneBoard/actions/runs/41415737867) |
| Live Ollama inference | NOT VERIFIED | CI reports Ollama unreachable at 127.0.0.1:11434; live tests skipped |
| Live API and provider integrations | NOT VERIFIED | No live provider test evidence |
| Windows startup, production deployment, all navigation tabs, performance | NOT VERIFIED | No corresponding test evidence |

Reproduce configured checks: `python -m compileall -q apps/api tests alembic`, `python -m pytest -v`, `python -m alembic upgrade head`, `python -m alembic downgrade base`, `python -m alembic upgrade head`, `cd apps/web && npm run build`, and `cd apps/web && npx playwright test --config playwright.config.ts` (with dependencies and browser installed).

Remaining release blockers: test real Ollama with installed models and timeout/failure behavior; full founder browser journey and all tabs; production-like HTTPS/cookie/CORS/secret checks; fresh database and seeded demo; multi-tenant and scheduler restart tests; Windows startup; performance; README claim-by-claim validation. Capture screenshots and traces for reproduced failures. No real user data or live payments should be used.

Earlier failed CI attempts are not retroactively successful. The green runs above verify only the checks explicitly listed.
