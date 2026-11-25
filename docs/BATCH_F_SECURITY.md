# Batch F security controls

Draft PR 8. No production deployment or real provider delivery.

- PostgreSQL restricted role: transaction-bound HMAC scope, signed for tenant + backend PID + transaction ID; narrowly scoped directory functions. Password and API-key verifiers are denied direct SELECT, including scoped sessions. The trusted application process can still verify credentials; a compromised application process is outside this boundary.
- Migration 016 enforces additional typed tenant relationships. Owner-only count audit reports legacy invalid rows without destructive repair. Heterogeneous JSON references still need domain-level verification.
- Account controls: encrypted TOTP with replay detection, one-use recovery codes, password reset with previously issued code, session revocation, scoped expiring keys, owner membership controls. Email challenges are staged only; actual delivery requires approved integration. No claim of email ownership without completed challenge.
- Configure independent 32-byte base64 secrets TENANT_CONTEXT_KEY and ACCOUNT_SECURITY_KEY in protected runtime configuration. Provision the matching tenant context key with the owner-only provisioning script; never put actual secrets in Git. Signing-key rollover uses AUTH_PREVIOUS_SECRET_KEY for the bounded overlap; remove it after old sessions expire. Keep account encryption key stable until a planned re-encryption migration.
- Security event chain uses keyed hashes in production; detects changes to retained events, but no external anchor means suffix deletion or complete replacement is not independently detectable.
- AI output is data, never authority. Workflow dispatch uses explicit server-owned capability allowlist; approval pins action and definition; custom agent tests are text-only. Prompt boundaries reduce risk, not guarantee model obedience. Live sending and provider execution remain disabled.
- Existing role grants must be reviewed on upgrade; owner script provisions a fresh restricted role; no live role changes performed.
