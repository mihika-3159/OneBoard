# Five-area reliability batch: engineering evidence and unresolved gates

Scope: draft PR #8 only, synthetic data only. No provider enrollment, outbound actions, spending, customer data, or deployment.

## Backup and disaster recovery
Previously implemented age-encrypted PostgreSQL dump is opt-in and does not contain plaintext archive files. New scripts/operations/test_encrypted_restore.py can decrypt into only a newly created local database named oneboard_restore_drill, verify head revision 008 and basic restored table count, and drop only its scratch database. It requires a 0600 private identity and explicit approval. This is operator tooling, not a tested offsite production backup. No real backup or restoration was executed.

## Durable alert state
AlertSnapshot persists tenant-scoped alert payload, unique alert key, active/resolved state and first/last-seen timestamps. PostgreSQL tenant advisory locks serialize concurrent refresh. The authenticated GET /api/alerts/history exposes durable resolved history. Repeated refreshes update rather than duplicate rows. Scheduler wakeups and outbound jobs are still process-local and cannot be guaranteed on sleeping hosts.

## Genuine integration without vendor accounts
POST /api/integrations/local/customers/import accepts founder-authorized user-supplied customer CSV with dry-run preview followed by explicit commit. CSV is capped at 1 MiB and 250 rows, with strict status, decimal, email and header checks. A tenant-unique durable import key and PostgreSQL advisory lock protect against duplicate records. The frontend provides preview and confirmation. This is NOT live provider OAuth, CRM sync or independently verified financial data.

## Workflow recovery
A workflow run now commits its running checkpoint, definition digest and request idempotency before dispatching any tool. Crashed runs remain visible; retries return the same run without auto-replay and a founder may quarantine stale runs. This does NOT establish exactly-once effects for real third-party tools.

## Large-corpus memory
PostgreSQL migration 008 creates a GIN full-text index for all chunk content and tenant/date lookup indexes. Production PostgreSQL queries rank tenant-scoped full-text matches beyond the former 1,000 recent chunks, returning strategy and truncation metadata. SQLite and unmatched queries still use bounded recent-window fallback. True embedding ANN search, synonyms and deployed load metrics remain unverified.

## Acceptance and limitations
The exact new PR head must pass all GitHub Actions workflows, including browser E2E, the full API suite, real Ollama, and PostgreSQL migration/backup/restore. A green CI run does not prove legal free hosting eligibility, uptime, actual encrypted offsite retention, real external integrations, or production SLA. No issues may be marked done until acceptance evidence exists.
