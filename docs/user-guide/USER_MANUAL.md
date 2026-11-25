# OneBoard user and operator guide

## Getting started
Use the README's local startup instructions. Register a founder workspace with a unique email and password, or sign in to an existing workspace. Demo data is optional and synthetic; a fresh real workspace does not automatically contain Northstar records. Review the setup guide before connecting providers or recording business information.

## Workspace sections

| Section | Use |
|---|---|
| Overview | Inspect recorded metrics and alerts. Missing or unverified information is labeled. |
| Founder Command | Ask questions about tenant records, verify evidence, and distinguish genuine inference from fallback. |
| Boardroom | Select advisers, convene a meeting, inspect arguments and citations, and record a founder decision. |
| Workflow Studio | Create or revise definitions, review schedules, dry-run, inspect approvals and resume eligible checkpoints. Do not blindly retry uncertain external actions. |
| Agent Studio | Configure explicit tools and memory grants, then monitor read-only ordered runs and cancel when needed. |
| Accountability | Record outcomes, compare forecasts and review adviser calibration. |
| Business Memory | Upload supported documents, monitor indexing, search and validate citations, resolve conflicts. |
| Operations & CRM | Inspect recorded commitments, customers and leads; data is not independently CRM-verified. |
| Finance & Ledger | Record journal entries, invoices, settlement evidence and statement comparisons; review reconciliations and forecasts. |
| Integrations | Review sandbox status and configured provider authorization, scopes, diagnostics, sync and revocation. No external connection is implied by a sandbox adapter. |
| Settings | Review model availability, account security, retention, exports, archives and deletion. |

## Security, data and recovery
Set up MFA and save one-time recovery codes securely; configure expiring scoped API keys only as required. Review sessions and security audit. Owners can manage workspace members. Export archives and verify restore before deletion; deletion requires exact confirmation, password and a factor if enabled. Existing backups and remote copies have separate retention.

If the session expires, sign in again. If a network failure interrupts a write, inspect recorded history before attempting again. An interrupted request does not establish that an action failed or succeeded.

## Operator notes
Follow the README, Batch E/F/N and external production gate documents for PostgreSQL roles, secure configuration, backups and monitoring. Do not handle real customer data or deploy publicly based solely on disposable CI. Live external providers, real hosting and independently verified financial provenance require separate approval and evidence.
