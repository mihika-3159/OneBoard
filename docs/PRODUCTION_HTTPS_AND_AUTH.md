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
LOGIN_MAX_ATTEMPTS=5
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
