# Batch N — Reliability and infrastructure (103–117)

## Operating contract

No production account, server, backup destination or external notification service is provisioned. All destructive fault tests target validated disposable containers. The operator must choose real hosting, HTTPS/DNS, credentials, a backup key kept outside the server, recovery targets and alert recipients. CI evidence is synthetic; no SLA or offsite durability claim.

| ID | Implementation and evidence |
|---|---|
| 103 | Database service stop during an uncommitted real finance ledger transaction; fail closed, recover readiness and replay the same reference exactly once. |
| 104 | Linux systemd hourly timer checks integrity and creates an encrypted backup when due; explicit approval and dedicated database backup credentials required. |
| 105 | Bounded age/count retention, minimum two verified copies, no expiration on integrity or replication failure. |
| 106 | Storage protocol with independent directory simulation; real age ciphertext is copied, primary removed, retrieved and decrypted in disposable PostgreSQL CI. |
| 107 | Snapshot start timestamp and elapsed verified restore duration; recovery-point age is an upper bound relative to drill time, not observed lost writes or service RTO. |
| 108 | Full ciphertext checksum and size verification each scheduled run, private atomic status report and nonzero exit on failure. |
| 109 | /health is liveness only; /ready checks database, schema and local disk; private /ops/health reports scheduler and admitted inference dependencies separately. |
| 110 | Validated W3C trace ID, response span and propagation to the approved inference gateway; bounded route-template metrics, per-process pool/RSS/events. |
| 111 | Independent systemd monitor stores deduplicated alert transitions for unavailable service/dependencies, failed jobs, disk and pool pressure. Local alert status and exit code are not external paging. |
| 112 | Digest-qualified base lock generation, hashed Python and locked npm dependencies, nonroot/read-only container and loopback-only host networking. CI builds and starts the image. |
| 113 | Graceful ASGI lifecycle, bounded Uvicorn request shutdown, scheduler completion, pool disposal; rolling worker SIGHUP and full restart preserve durable state. |
| 114 | Immutable-image schema compatibility preflight; incompatible older binary is blocked, restore a verified clone before rollback. |
| 115 | Ten-minute multi-worker authenticated HTTPS load and separate ten-minute genuine small-model inference soak with RSS and latency measurements. |
| 116 | Actual database stop/start, critical transaction rollback, pool saturation, interrupted TLS response and real isolated tmpfs ENOSPC tests. |
| 117 | Automated report from sustained HTTP and inference measurements; configuration limits and memory headroom, not extrapolated throughput. |

## Backup and alert setup (operator-owned)

Create private directories (0700) and distinct unprivileged service accounts. Configure /etc/oneboard/backup.env (0600) with the approved PostgreSQL DSN (remote requires verified TLS), ONEBOARD_PRODUCTION_MODE=true, ONEBOARD_BACKUP_OPERATION_APPROVED=YES and ONEBOARD_AGE_RECIPIENT. Never place the age private identity on the backup host. Install the example systemd service/timer only after owner approval. Default daily backup, hourly integrity checks, 30-day retention, keep three. Review backup-status.json and systemd journal. The CLI supports interval, keep, minimum disk floor and an optional DirectoryReplica for simulated testing. That replica is not certified independent physical storage. Real backup adapter credentials and destination remain an operator decision; no automatic network upload. The ciphertext manifest is an integrity checksum, not independent authenticity evidence; retain separately protected manifests and periodically perform age decryption/restore.

The backup manager serializes runs with a process-crash-safe flock. A partial pair, corrupt archive or replica stops expiration and reports an alert. Repair/quarantine a damaged artifact explicitly; never erase the only recoverable copy. RTO/RPO results describe the scratch database drill only. For service restoration, also verify keys, runtime role, edge TLS, migrations, provider connectivity and authenticated tenant isolation before routing traffic. Keep previous release image and its schema manifest.

Configure OPERATOR_METRICS_KEY independently of session signing key, at least 32 characters, never expose to users. /ops endpoints return 404 when unconfigured or unauthorized. Use monitor.env with the same key and exact HTTPS origin; copy the backup status into a separately readable protected directory or grant the monitor read access to the specific status file, then add --backup-status to the service command. Monitor returns 1 while alerts remain active. Local health alerts do not send messages to third parties. Collect per-worker metrics separately (a load-balanced sample is not cluster aggregation). /ready does not fail merely because inference is unavailable; deterministic workflows remain usable. A DB restart invalidates old connections; no automatic write replay. For an uncertain finance or workflow mutation, reconcile by the existing request reference/idempotency key before issuing a new request. A failed backup or unavailable database may require operator intervention.

## Container release and rollback

On Linux, generate a base lock with sh deploy/lock-bases.sh release-bases.lock, retain it, then build with sh deploy/build-image.sh release-bases.lock oneboard:release. Use the same lock for subsequent builds. Capture the immutable local image ID or registry digest and actual Alembic head in a release manifest {"image":"sha256:...","schema_head":"024_batch_m_storage"}. Run python -m scripts.operations.release_guard --release-manifest release.json using a read-only database account before deploy/rollback. A mismatch blocks execution. Use a separately approved migration account and verified backup; test upgrade on a disposable clone, then migrate during a maintenance window. Do not downgrade a live database automatically. If rollback crosses a schema change, recover to a verified clone and validate prior release there before an explicit operator-controlled cutover. Never overwrite live DB from the scratch drill. Compose uses host networking to preserve loopback-only ASGI and existing local PostgreSQL/Ollama and TLS edge; do not expose port 8000 directly. Runtime uses a restricted nonowner DSN and separate secret file. Production storage is PostgreSQL, not tmpfs. The container's data directory is temporary and not a backup location. Two to four API workers may be configured only with verified connection/memory budget. Uvicorn stops admitting traffic on SIGTERM; allow 180s supervisor grace for scheduler completion. Rolling workers require POSIX multiprocess mode; container replacement itself requires an edge drain/second instance plan and is not guaranteed zero downtime.

## Capacity and recovery evidence

The mandatory GitHub workflows collect exact-commit reports for the synthetic database and model workloads, fault drill, container build identity, backend tests and browser regression suite. The capacity report applies a 30% memory margin and 1 GiB OS/DB reserve to measured peak RSS, with worker count and pool limits. It does not promise capacity for larger models or customer data. The operator must repeat soak and recovery drills on the chosen deployment topology and choose alert thresholds and recovery objectives. No actual production deployment is part of Batch N.
