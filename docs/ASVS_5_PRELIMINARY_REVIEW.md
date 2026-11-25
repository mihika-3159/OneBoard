# OWASP ASVS 5.0.0 preliminary security review

Source: https://asvs.owasp.org/ and https://github.com/OWASP/ASVS/tree/v5.0.0. Review baseline: 8745ed50614e64ddc7487f40c1da84d37c067b4b plus the remediation in this commit. Target: ASVS Level 2 as an engineering goal for a future sensitive-business-data service, not a certification claim. For the hackathon use synthetic data only. This is a chapter-level triage based on inspected code, test inventory and observed GitHub Actions; individual ASVS requirements have not all been assessed. Do not report percentage compliance.

| Chapter | Existing evidence / gaps |
|---|---|
| V1 Encoding and sanitization | Typed inputs, ORM queries, static frontend sink scan; injection and traversal regressions in tests/adversarial/test_security_and_injection.py. Full sink and parser review needed. |
| V2 Validation and business logic | Financial boundary matrix, exact-money journal, workflow DAG and idempotency suites. Review abuse cases and all exposed mutations. |
| V3 Web frontend security | CSRF, CORS, frame denial, nosniff, referrer and permissions headers in apps/api/main.py; API no-store expanded in this commit. Production CSP absent in reviewed middleware; test an appropriate CSP and external font dependencies before real-data launch. |
| V4 API and web service | Route auth dependency inventory and runtime security matrix; bounded input and rate limits. Verify all response schemas and complete HTTPS browser/DAST gate. |
| V5 File handling | Bounded parsing and subprocess isolation; inspect upload/content-type and archive expansion coverage per applicable requirement. |
| V6 Authentication | Password, MFA, recovery and throttling tests (test_batch_f_account_security.py, test_auth_payload_limits.py); real email verification delivery unavailable. |
| V7 Session management | Session lifetime, revocation and browser expiry tests; full browser gate needed on final revision. |
| V8 Authorization | Restricted PostgreSQL, tenant isolation and member role tests. DAST returned 200 with empty foreign workflow revision list; explicit parent ownership 404 added, and regression checks same result for missing and foreign IDs. No evidence that foreign rows were exposed. |
| V9 Self-contained tokens | test_auth_token_claims.py and scoped expiring API keys; review all token algorithms, claim handling and lifecycle individually. |
| V10 OAuth and OIDC | Seven simulated native provider contracts and scope/state/PKCE checks; real registered apps, redirect and revocation evidence outstanding. |
| V11 Cryptography | Account security encryption, provider envelope rotation and backup tooling; key custody and independent audit outstanding. |
| V12 Secure communication | HTTPS production test and restricted-role deployment, remote TLS configuration and opt-in edge probe. Public certificate and network isolation not verified. |
| V13 Configuration | Production config/schema guards, locked packages and container smoke. Verify actual hosted settings, secrets and permissions. |
| V14 Data protection | Tenant exports, retention, deletion, backup tests and redaction; independent storage, hosting privacy and data-handling review deferred. |
| V15 Secure coding and architecture | Bandit, frontend AST scan, dependency audits and generated tests; these are not a full review of the entire dependency tree or architecture. |
| V16 Logging and error handling | Request IDs, route-template logs, OAuth callback log filter and protected operational metrics. Review actual edge/provider logs, redaction and alert delivery. |
| V17 WebRTC | Not apparent in inspected architecture (HTTP/NDJSON); confirm no applicable WebRTC functionality before marking individual requirements N/A. |

Observed predecessor CI: standard backend verification passed at 4ddc325; release engineering at 8745ed5 passed static-and-build but stopped on the foreign revision denial assertion. New remediation and synthetic review tests are pending CI. No ASVS level, independent audit or penetration-test pass is asserted.

Next assessment step: use the official ASVS 5.0.0 requirement-level checklist with evidence, applicability, PASS/FAIL/NOT TESTED, and remediation for each applicable L1/L2 control. Reuse existing tests rather than treating each chapter as a new feature batch. Prioritize authorization, data exposure, authentication, CSP and production endpoint security.
