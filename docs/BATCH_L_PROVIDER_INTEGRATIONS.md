# Batch L: provider integrations (79–91)

The default installation does not contact a provider. Legacy sandbox connectors remain separate from the external lifecycle. No real third-party account, vendor OAuth application, paid service or public HTTPS host is provisioned by this change.

## Operator configuration
Set `PUBLIC_API_ORIGIN` to the deployed HTTPS origin. Create a separate 32-byte random base64 encryption key for `PROVIDER_ENCRYPTION_KEYS`, select its ID with `PROVIDER_ACTIVE_KEY_ID`. Keep the previous key available while rotating tenant credential envelopes; after all active credentials and authorization verifiers have rotated, retire the previous key. The prior `PROVIDER_TOKEN_KEY` must remain available until legacy staged credentials are converted. Never put actual keys in source code.

`PROVIDER_CONNECTORS` is a server-side JSON map keyed by crm, email, calendar, finance, github, notion or google. Each enabled normalized adapter has an explicit trusted HTTPS host, authorization, token, identity, sync and revoke URLs, client ID and secret; writable adapters also have action/status URLs. A webhook secret (at least 32 characters) is optional. Configure redirect URI as PUBLIC_API_ORIGIN/api/integrations/providers/oauth/callback. Configure TLS, no redirects and access-log query redaction at the reverse proxy as well. No tenant controls any endpoint URL.

## Normalized adapter protocol
The transport is a real bounded HTTPS client for a trusted adapter implementing the following protocol. This is NOT the native HTTP API of each named vendor; a vendor-specific adapter or bridge is necessary for normalized mode. Native read-only adapters are included below.
- OAuth authorization code with S256 PKCE and actor/tenant-bound single-use state. Token endpoint returns Bearer access token, explicit granted scope(s), expiry, optional refresh token. Identity endpoint returns account_id. The adapter must preserve account identity across refresh.
- Sync endpoint accepts opaque cursor, scopes, limit <=100 and returns records [{id,revision,payload}], next_cursor and has_more. Persisted checkpoint and records commit atomically; revisions are deduplicated or presented for an explicit conflict decision. Provider records remain a distinct sourced collection, not invented financial or CRM facts.
- Action endpoint accepts action, payload, idempotency_key. Status endpoint accepts the same key and returns status (confirmed/rejected/pending/not_found/unknown), idempotency_key and remote_reference on confirmation. The adapter must persist delivery identity; OneBoard records dispatching before contacting it and never automatically replays an ambiguous write. A crashed or timed-out write can be reconciled by status.
- Revoke endpoint reports revoked=true only upon confirmation. Local disconnect clears credentials and cancels queued sync/undispatched actions even if remote revoke fails.
- Webhook POST /api/integrations/providers/webhook/{provider}/{tenant}/{connection_id}, exact raw JSON {event_id,account_id,type:"records.changed"}. Headers x-oneboard-timestamp (Unix seconds), x-oneboard-signature (hex HMAC-SHA256). Sign provider, tenant, connection_id, timestamp and raw body joined by newline bytes. Verify timestamp within 300 seconds before tenant scope; deduplicate event and body hash atomically with sync enqueue.

## Verification
Seven simulated provider contracts exercise OAuth PKCE, grants, identity, pages, checkpoints, duplicate/conflicting records and revocation. Additional tests verify state replay and tenant binding, refresh and rate limits, credential rotation, authenticated webhook replay and uncertain delivery. No simulated outcome is evidence of actual vendor authorization, real delivery or native vendor compatibility. The native vendors' approval, account-specific scopes and real service access remain separately gated.

## Native read-only adapters
Set an enabled provider's mode to native with a registered client_id/client_secret. All native endpoints are fixed in code. OAuth uses PKCE for Google and GitHub; confidential-client state and registered redirect validation for other native flows. The selected direct integrations are HubSpot CRM contacts, Gmail message identity/history metadata (no body), primary Google Calendar events, Stripe Connect balance transactions (not bank verification), GitHub public repository metadata (no private repo permission), Notion shared page metadata (not full page blocks), and Google Drive file metadata/changes. No native writes are enabled: use the normalized adapter contract for verified idempotent external delivery. Stripe mode must explicitly set stripe_livemode; Notion requires notion_read_only_app=true and native_scope matching token introspection. Notion/Stripe local reauthorization intervals are not provider-reported expiry. GitHub and Notion use resumable paginated scans and deduplication; Drive/Calendar/Gmail use native change/history/sync tokens; CRM and Stripe use overlapping incremental watermarks. An expired checkpoint requires an explicit full-resync reset, retaining earlier records for review. Native-provider webhook formats are not claimed; a trusted relay may emit the normalized HMAC protocol. An adapter endpoint or app identity change cannot reuse a previously connected credential. Provider contracts are simulated, not live authorization.

Vendor references:
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/workspace/drive/api/guides/manage-changes
- https://developers.google.com/workspace/calendar/api/guides/sync
- https://developers.google.com/workspace/gmail/api/guides/sync
- https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
- https://developers.notion.com/reference/create-a-token
- https://developers.notion.com/reference/introspect-token
- https://developers.hubspot.com/blog/oauth-token-management-hubspot-integrations
- https://docs.stripe.com/connect/oauth-reference
