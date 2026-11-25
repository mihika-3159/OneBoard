# Batch P: testing, supply chain and release engineering

Requirements 131–148. This implementation extends existing mandatory verification, not production certification.

| ID | Engineering changes / verification |
|---|---|
| 131 | Five GitHub Actions pinned to verified upstream commits across workflows; Ollama release archive pinned and SHA-256 checked. Lock checker rejects mutable Actions. Experimental tooling and container service tags remain separately scoped. |
| 132 | Direct Python specification checked against hashed lock plus pip check; frontend build requires npm ci. |
| 133 | Browser runner and both exact runtime versions checked against pinned Playwright release; application npm lock left untouched. Browser package integrity lock still needed. |
| 134 | CycloneDX Python lock inventory and npm lock-derived SBOM. |
| 135 | SHA-256 build receipt tied to CI run and commit; independent job validates downloaded bundle before use. This is not independently signed provenance. |
| 136 | Additional high-confidence npm, DigitalOcean, Azure DevOps, Shopify and SendGrid token detectors. |
| 137 | Mandatory Bandit high-severity backend gate and TypeScript AST sink scanner. |
| 138 | Restricted-role disposable HTTPS browser journey, unauthenticated access and foreign-origin deletion denial. Broader DAST remains outstanding. |
| 139 | Per-module critical coverage floors, branch coverage recorded. Actual coverage results required before acceptance. |
| 140 | Generated exact arithmetic, condition, tenant-context and malformed CSV properties; seed-reproducible. |
| 141 | Dedicated production-mode same-origin browser job with real restricted PostgreSQL runtime and checked build. |
| 142 | Four authenticated tenants, two concurrent clients and twelve genuine local inference results. Existing distributed queue tests retained. |
| 143 | Existing ten-minute inference and HTTP soak plus deterministic infrastructure faults retained; randomized long-duration failure injection still needed. |
| 144 | Chromium, Firefox, WebKit Linux browser matrix; existing Windows startup retained. Native Windows/macOS browser coverage remains unverified. |
| 145 | Machine-readable release engineering receipt with artifact hashes; prior suite artifacts retained. Cross-workflow consolidation still needed. |
| 146 | Existing HTTP p95/RSS and inference RSS bounds, plus critical coverage thresholds. More comprehensive baseline-based regression gates still needed. |
| 147 | Release checks separated into a reusable module; existing broader architecture refactor remains open. |
| 148 | README reflects provider routing and synchronization code versus unverified live deployment; broader manuals and marketing audit remains open. |

Batch O regression fixes included: reset registration/recovery modes after success or expiration; clear an interrupted read warning when that exact read recovers; scope the outage regression assertion to the provider error; update mandatory browser count from 26 to 29.

Do not mark complete until actual CI results and outstanding coverage are resolved. All tests use synthetic data and disposable infrastructure. No external production operations or paid providers are authorized.
