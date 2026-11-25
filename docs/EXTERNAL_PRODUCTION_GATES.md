# External production gates: engineering complete does not mean deployed

No provider has been enrolled or approved. This repository must not claim
live hosted SaaS readiness, free 24/7 inference, public TLS or offsite
disaster recovery until independently verified on an authorized service.
The normal AI architecture is server-side: no founder model downloads.

1. Hosting and persistent database: BLOCKED. The owner requires zero cost,
   no payment card, no guardian consent and explicit eligibility for a
   minor in the UAE. Verify provider terms, data loss/sleep/quotas, storage,
   private PostgreSQL networking and privacy, and obtain owner approval.
   A static frontend is not an adequate backend deployment.

2. Hosted AI inference: BLOCKED. The default OLLAMA_BASE_URL points to the
   API server's loopback. Remote inference configuration is rejected in
   production unless the operator separately enables
   OLLAMA_REMOTE_APPROVED=true and pins the exact HTTPS hostname with
   OLLAMA_REMOTE_HOST. A boolean flag is NOT provider eligibility or
   privacy approval. Synthetic OVHcloud experiments are NOT approval.
   Benchmark actual latency, capacity and fallback with synthetic data.

3. HTTPS deployment: BLOCKED. The source includes a minimal unactivated
   Caddy reverse proxy example in deploy/Caddyfile.example. An approved
   operator must provision a real HTTPS domain and ensure there is no
   direct public route to Uvicorn or PostgreSQL. After explicit approval,
   run the external smoke tool with a canonical PUBLIC_API_ORIGIN:

     ONEBOARD_EXTERNAL_PROBE_APPROVED=YES python -m scripts.operations.verify_https_edge --origin https://api.example.test --probe

   The tool verifies the TLS certificate through a real HTTP client,
   HSTS, unexpected Host rejection and rejection of spoofed forwarding
   headers. A default run without --probe checks only the URL string.
   This is not a firewall scan or penetration test.

4. Encrypted backup/recovery: BLOCKED. Disposable PostgreSQL CI already
   exercises dump, simulated deletion, checksum and restore with fake data.
   For a separately authorized production host, an operator may install
   pg_dump and age and prepare a locked-down 0700 backup directory.
   The following opt-in command streams a custom-format PostgreSQL dump
   into age encryption without creating a plaintext dump file:

     ONEBOARD_BACKUP_OPERATION_APPROVED=YES ONEBOARD_PRODUCTION_MODE=true python -m scripts.operations.backup_encrypted --backup --directory /private/backups --recipient age1...

   The recipient is a PUBLIC age encryption key. Never commit or send the
   private decryption identity. Remote PostgreSQL requires verify-full TLS.
   This command does NOT upload ciphertext, schedule retention, rotate
   keys, restore databases or perform external network access on its own
   without an approved source DATABASE_URL. To verify ciphertext hash
   without connecting to a database:

     python -m scripts.operations.backup_encrypted --verify /private/backups/name.dump.age

   An offsite encrypted copy, tested decryption into a separate disposable
   target, secure private-key custody, RPO/RTO and a documented recovery
   operator remain mandatory before production acceptance.

These tools create no infrastructure, accounts, payment activity or real
provider actions during CI. Do not close any of the four live blockers
based on a successful build. The release decision remains NO-GO until the
four independent acceptance records exist.
