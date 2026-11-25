# OneBoard hackathon external acceptance

Target: a controlled synthetic-data hackathon demonstration, not public commercial production. No payments, bank accounts, real customer data, provider credentials or paid infrastructure are required by the tests. No public deployment is authorized by this record.

## Infrastructure and HTTPS
Apply for the GitHub Student Developer Pack (https://education.github.com/pack/join) using the student's genuine school email. Microsoft Azure for Students Starter (https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0144p/) is a candidate for academic development, subject to academic email verification and actual subscription resource availability. Free App Service limits are not proof that the backend, database roles, persistent workers or Ollama fit. Codespaces is a bounded development/demo environment, not a permanent public host. No approved host has been provisioned.

On an authorized host use a canonical HTTPS origin, private restricted PostgreSQL role and verified remote TLS if separate, and either the provider's verified managed edge or the checked-in Caddy example for a host controlled by the operator. Set the exact permitted proxy address and ensure the database/Ollama/Uvicorn are not publicly reachable. The existing external GET-only probe checks valid certificate, HSTS, response headers, Host rejection and spoofed forwarded headers. Never infer network isolation from a passing probe. Use actual host network configuration and a separately approved isolation check. No live DNS, certificate, tunnel or network has been configured in this run.

## Backup
An existing USB flash drive or external SSD can store an encrypted backup copy, preferably physically separate from the host. Use only encrypted ciphertext and its verification manifest. A second location protects against loss of the original site; a USB connected to the same machine is not offsite. Test recovery into a separate disposable database. Keep the private decryption key separately, never in the repository or on the backup medium. Manual copies are acceptable for a synthetic demonstration; no automatic offsite service has been activated.

## Integrations
All seven native read-only contracts have simulated OAuth, identity, sync and revocation tests: Gmail metadata, Calendar events, Drive metadata, GitHub public repository metadata, Notion page metadata, HubSpot contacts and Stripe balance transactions. No new OAuth app or real provider account has been created. A real test requires registered app credentials, eligible account and HTTPS callback. The finance adapter requires an explicit Stripe test/live mode and matching key prefix; use sandbox only. For this hackathon do not configure Stripe at all until eligibility and an authorized test account are confirmed. Do not create charges, transfers, payouts or customer payment records. Synthetic contract tests send no network requests.

## Financial review
The synthetic review CI job uses integer and decimal expectations authored independently from the financial calculation routines, known input fixtures, boundary cases, reconciliation and provider contract tests. It produces a JUnit report, not a bank statement or an independent accountant's signed opinion. The reviewer can compare hand calculations with the app's ledger entries and recorded metrics. The test suite must pass on the candidate commit.

## Accessibility
Browser automation checks WCAG rules, accessible tree and keyboard journeys. For actual NVDA/VoiceOver, see SCREEN_READER_ACCEPTANCE.md. A human session is still not performed. It requires a person using the assistive technology; the coding agent has no native screen-reader audio session.

## Privacy
Draft only: see HACKATHON_POLICY_DRAFT.md. Do not activate a public registration policy or collect real customer data based on this draft.
