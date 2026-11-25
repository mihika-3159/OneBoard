# Batch P follow-up acceptance (131–148)

The earlier commit adds immutable Action and Ollama pins, Python lock checks, SBOM generation, build hash receipts, secret scanning, static analysis, critical coverage thresholds, property tests, restricted PostgreSQL production browser tests, real-model tenant load, browser matrices and release receipts.

This follow-up corrects the invalid unquoted YAML scalar containing :all:, checks in npm integrity locks for Playwright and axe-core, adds Windows/macOS and Linux browser coverage, frontend bundle budgets, seeded real disposable database restart cycles, and synchronizes architecture, manual and competition documentation. The previous browser and README test failures are addressed. Provenance remains a CI identity/hash receipt, not independent signed attestation. Full dynamic security and combined cross-workflow release evidence need validation beyond the existing restricted-HTTPS checks. The exact browser package integrities were cross-checked against immutable published package locks before being added.

All evidence must be collected on the same candidate revision. CI configuration is not a passing test result or an external production approval. See TEST_REPORT.md for historic results and external gates for independent acceptance.
