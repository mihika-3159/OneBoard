# Batch E engineering / operator notes

## Database separation
Production startup rejects superuser, BYPASSRLS, database/role creation,
replication, public-schema CREATE, application-table ownership and role
memberships. Run Alembic with a separate migration-owner connection; an
owner-approved operator may provision a distinct login with:

```sh
# Use private environment variables, not committed files or shell history.
# DATABASE_URL is the migration owner's PostgreSQL psycopg URL.
# ONEBOARD_RUNTIME_ROLE and ONEBOARD_RUNTIME_PASSWORD must be separately set.
ONEBOARD_ROLE_PROVISION_APPROVED=YES python -m scripts.operations.provision_runtime_role
```

Use only the resulting restricted login in the API DATABASE_URL. On
PostgreSQL upgrades, grant newly added application-table DML and migration
version SELECT to the existing restricted login with an approved owner
operation; never grant ownership or BYPASSRLS. Do not place migration
credentials in the running API environment. The runtime auth directory,
business discovery and global coordination tables intentionally remain
readable before a tenant context. All RLS-protected content tables deny
unscoped non-owner access; the sync history policy checks parent ownership.
This is database defense in depth, not resistance to arbitrary SQL
execution by a fully compromised application login.

## Scheduled workflows
Only explicitly enabled daily/weekly local wall-clock schedules run.
Select a fixed time and IANA timezone in Workflow Studio, or
PUT /api/workflows/{workflow_id}/schedule using e.g. cron "15 9 * * fri".
DST gaps are skipped, repeated local times use the first occurrence.
Missed slots coalesce; each due slot uses a stable idempotency key. A
running, failed, paused or approval-required run pauses future slots until
the founder reviews it and explicitly re-enables the schedule. It does not
auto-replay uncertain actions. No external email/provider delivery exists.
Worker polling is bounded and best effort, not a punctuality SLA.

## Owner data
Settings exposes bounded consistent JSON snapshots, and separately opt-in
document/resolved-alert/expired-session retention. Large snapshots return
413 rather than silently truncating; older paginated exports are not
point-in-time consistent. Credential columns are excluded, but arbitrary
user text can still contain secrets. Financial and audit evidence are
never automatically pruned. Neither export nor deletion erases backups or
external provider data.

## Lock maintenance
The checked-in requirements.lock is generated with
`uv pip compile apps/api/requirements.txt --universal --python-version 3.11 --generate-hashes --output-file apps/api/requirements.lock`.
Review changes and test the wheel-only hash install on Linux and Windows.
The history scan covers reachable Git objects with high-confidence
patterns, not all possible secrets, unreachable blobs or remote logs.
No history rewrite is authorized by a detection.
