# Production HTTPS and shared-network authentication checks

This document is a **code-level security contract**, not a deployment
recommendation or evidence of a live HTTPS service. OneBoard has not verified
external TLS termination, provider eligibility, uptime, backup recovery or
deployment readiness. Do not enable public multi-tenant access until those
separate checks have been completed with owner approval.

## Production settings

A production process must set all required security options, including:

```env
ONEBOARD_PRODUCTION_MODE=true
ONEBOARD_DEMO_MODE=false
COOKIE_SECURE=true
AUTH_SECRET_KEY=<independently generated high-entropy signing secret>
DATABASE_URL=postgresql+psycopg://<dedicated private connection>
PUBLIC_API_ORIGIN=https://api.example.test
CORS_ORIGINS=https://app.example.test
TRUSTED_PROXY_IPS=127.0.0.1
LOGIN_MAX_ATTEMPTS=5
LOGIN_SOURCE_MAX_ATTEMPTS=60
REGISTRATION_SOURCE_MAX_ATTEMPTS=30
LOGIN_LOCKOUT_SECONDS=300
```

These are **placeholders**, not usable provider credentials or a deployed URL.
The HTTPS API origin may be the same as the frontend origin in a same-origin
installation. Both origins must be explicit and canonical.

The application rejects an unexpected or duplicate `Host` with HTTP 421,
and rejects plaintext HTTP (ASGI scope scheme `http`) with HTTP 403 in
production. It does **not** trust the raw `X-Forwarded-Host` or
`X-Forwarded-Proto` headers to override those decisions. Responses returned
from these checks still include baseline security headers. HSTS is sent only
for requests that the ASGI server identifies as HTTPS. These checks do not
themselves prove TLS was configured or that proxies were trustworthy.

## Reverse proxy trust boundary

- Terminate TLS at an owner-approved HTTPS reverse proxy and prohibit direct
  public traffic to the Python ASGI service. Expose the ASGI service only on
  localhost or a private network that is not directly Internet-accessible.
- Preserve the *external* `Host` value at the proxy; it must exactly equal the
  host and optional port specified by `PUBLIC_API_ORIGIN`.
- The proxy must supply the correct `X-Forwarded-Proto: https` header **only
  after accepting a real HTTPS connection**. Configure Uvicorn
  `--proxy-headers --forwarded-allow-ips=<actual trusted proxy IP addresses>`.
  Do not use `--forwarded-allow-ips=*` and do not trust end-user-supplied
  forwarding headers. Validate the trusted peer IP and ensure the proxy
  overwrites/removes incoming forwarding headers rather than appending
  untrusted client values.
- With a same-host localhost reverse proxy, for example, Uvicorn can bind
  to `127.0.0.1` and trust only `127.0.0.1` forwarding. This example does
  not expose a service or create a provider account.
- An HTTP-only deployment must fail closed. If a valid request is rejected
  behind a proxy, fix the proxy network and trusted-forwarding setup; never
  disable the production scheme or Host checks.
- In a future authorized deployment, check from an external client that the
  HTTPS API responds with HSTS, that a plaintext request is denied by the
  edge or app, and that wrong/duplicated Host and spoofed forwarding headers
  never reach authenticated handlers. Internal load-balancer health probes
  must use the authorized HTTPS scheme or be separately assessed.

## Shared offices, schools and carrier-grade NAT

A login is throttled by **source plus account** (and invalid attempts also by
account). A correct password can recover from an attacker-induced account
global lockout, provided the source+account key has not been exhausted.

Registration uses a separate **source-wide** shared PostgreSQL attempt
budget. The previous five-attempt limit could deny all unrelated users
behind one NAT after just five registrations. The default is now 30 attempts
per 300-second window, bounded to 10–100 by production configuration
validation. Check and record are serialized with PostgreSQL advisory
transaction locks across workers. Registrations, whether successful or
rejected after admission, count toward the source limit. Retain the strict
five-guess password budget for individual source-account combinations.

A user who controls or shares a NAT can still consume this finite
registration budget, and rotating addresses can evade source-based quotas.
These are **residual operational risks**, not a guarantee of abuse
prevention. Any future public deployment needs its own trusted edge
capacity controls, monitoring and a non-automated account recovery process.
Never attempt circumvention by trusting unvalidated forwarded IP headers.

## Automated evidence

- `tests/unit/test_production_configuration.py`: validates separate auth
  thresholds and rejects unsafe API origins.
- `tests/adversarial/test_https_public_origin_guard.py`: exercises production
  HTTPS/Host checks in an isolated ASGI client (not over real TLS).
- `tests/adversarial/test_registration_abuse_control.py`: checks pre-hash
  throttling and rejects untrusted forwarding headers.
- `tests/integration/test_postgres_security.py`: disposable local PostgreSQL
  concurrency test of the source-wide registration budget and isolation from
  login keys.

These tests are necessary but not a live load/security assessment. Consult
`TEST_REPORT.md` for exact commit and CI execution results.


## Cross-account password-hashing budget

The ordinary `LOGIN_MAX_ATTEMPTS=5` budget protects a particular
source+account combination, but rotating 100 different emails from the same
source bypasses that expensive Argon2 protection. Production now charges
**all** login attempts, including successful logins, against the independent
`LOGIN_SOURCE_MAX_ATTEMPTS=60` source budget in each 300-second window. The
allowed production configuration range is 20–200 and must exceed the
per-account limit. A missing verified transport source fails closed before any
password check. The budget is persisted via the same shared PostgreSQL
transaction/advisory lock infrastructure and cannot be reset by a correct
password for another account. A forwarded IP supplied by the client is not a
trusted identity.

This introduces an explicit availability trade-off: busy schools, offices, or
carrier NATs can hit their source budget. The service must show HTTP 429 with
Retry-After and allow users to retry after the window. It cannot distinguish
all legitimate users behind one IP without an edge identity provider. Nor
can it prevent denial of service through many source IPs. An owner-approved
public deployment still needs proxy-level capacity controls and monitoring.

## API key storage and migration

New API credentials have 224 random bits, rendered as `obk_` plus 56 lowercase
hex digits. They are returned in plaintext **only at rotation**; the database
stores a `sha256:`-prefixed SHA-256 verifier. Querying the database cannot
retrieve the original credential, and supplying the stored verifier to the API
does not authenticate. Production rejects malformed keys before SQL lookup
and does not fall back to plaintext comparisons. The local demo retains a
development-only legacy lookup for synthetic keys.

Alembic revision `006_api_key_hashing` upgrades previously issued canonical
API keys in PostgreSQL without changing their client-visible value. **A
noncanonical, weak or synthetic legacy key blocks the upgrade**, rather than
silently turning an easily guessed demo credential into a valid production
token. Inspect this failure only in an authorized maintenance process;
rotate or explicitly disable invalid legacy credentials before retrying.
Never include any raw key in deployment logs, diagnostics, test reports or
screenshots. The migration is irreversible: a PostgreSQL downgrade from 006
is deliberately refused while active hashed keys remain. Restoring an older
application version requires a reviewed data-restoration and credential
rotation plan, not a blind Alembic downgrade. This work does **not** implement
backup/restore or authorize live deployment.

After migration, production startup also rejects a database containing any
plaintext/noncanonical API-key value, even if Alembic reports revision 006.
Existing sessions and application data are not silently deleted. The
disposable PostgreSQL CI suite verifies canonical legacy-key conversion,
production authentication by the original raw key, rejection of unsafe
downgrade, and failure with weak legacy keys without data loss.

Production secrets must not be committed to this repository.


## Audited local-proxy entrypoint, remote database TLS and limits

Run the API behind an **owner-approved local HTTPS reverse proxy** using
`python -m scripts.serve_secure_api`. The code's `secure_uvicorn_options`
enforces loopback binding (`127.0.0.1:8000`), disables hot reload, and passes
only explicit `TRUSTED_PROXY_IPS` to Uvicorn's forwarding-header trust
mechanism. Production configuration rejects missing, wildcard, CIDR,
multicast, duplicate, or hostname-based proxy trust settings. This is an
application-side guard, not proof that an upstream firewall, TLS certificate,
load balancer or proxy has been configured correctly.

Remote PostgreSQL URLs must include `sslmode=verify-full` so the
production application verifies the database's TLS server identity, rather
than trusting an encrypted connection to an arbitrary host. Host-local
PostgreSQL access may use a private transport, which must be verified as
private in the deployment network. No production database address, account
or certificate is included in this repository.

**External deployment acceptance remains unproven:** the owner must approve
an eligible no-card zero-cost provider; verify its age and usage terms;
deploy with synthetic data only; confirm actual TLS termination, trusted
proxy peer IPs, Host forwarding, direct-backend isolation and remote database
certificate verification; record repeatable external requests and failure
results. Never enable public multi-tenant use solely because local ASGI
tests pass. Do not trust browser-side LLM downloads as an alternative to
server-side inference.
