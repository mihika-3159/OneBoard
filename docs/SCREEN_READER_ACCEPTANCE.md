# Human assistive-technology acceptance record

Status: NOT PERFORMED. Automated browser accessibility-tree, axe and keyboard tests are not a human screen-reader test. No human participant or native screen-reader audio session was available to the coding agent. Do not fill this record from automated results.

Use an isolated synthetic workspace and the exact candidate commit. No real customer data, external writes, spending or credentials are needed.

## Test environments

- Windows: NVDA with Firefox and Chromium.
- macOS: VoiceOver with Safari.
- Record OS, browser and screen-reader versions, date, candidate SHA, reviewer and observed behavior.

## Journeys

| Journey | Acceptance condition |
|---|---|
| Registration, login, logout and expired session | Fields have names, errors and busy status announced, no inaccessible keyboard trap, workspace unavailable after expiry. |
| Navigation | All eleven sections announced, current section identifiable, skip link reaches content. |
| Alerts and teach-process dialogs | Dialog announced, initial focus inside, keyboard focus contained, Escape closes when permitted, focus restored. |
| Workflow editing | Saved workflow selection and definition controls usable; text alternative exposes step names/types and directed dependencies without interpreting the canvas visually. |
| Command, council, agents | Progress and cancellation announced, outcome and fallback distinctions readable. |
| Memory, operations and accountability | Search, upload, records, outcomes and conflicts accessible without pointer. |
| Finance | Tables read with correct headers, amounts, currency, errors, confirmations and uncertainty labels. |
| Settings and integrations | Auth, security, archive and provider controls identified; destructive confirmations understandable without relying on color. |
| Responsive/zoom | At 200% and narrow viewport, all controls remain reachable and relevant status remains available. |

Record PASS/FAIL/NOT RUN for each combination, exact reproduction steps, observed speech or braille output and issue reference. Repeat failures after fixes. A human review is not equivalent to independent legal certification and no reviewer signature may be fabricated.

Automated engineering acceptance is a separate gate. Use the exact candidate's browser artifacts for axe and keyboard evidence, never as a substitute for this record.
