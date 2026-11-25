# OneBoard system architecture

OneBoard is a local-first engineering prototype, not an independently certified production SaaS. The React 18/Vite frontend communicates with FastAPI over authenticated HTTP and newline-delimited JSON streams. There is no WebSocket or SSE requirement. SQLite supports local development; PostgreSQL is required in production with separate migration and restricted runtime roles, tenant-scoped database policies, and signed tenant context.

## Execution layers

- **Presentation:** eleven workspace sections, lazy-loaded views, shared recovery states, explicit permissions and accessible controls. The workflow canvas previews persisted definitions; edits are saved as versioned definitions with optimistic concurrency.
- **Application:** FastAPI routes enforce authentication and founder/owner authorization, scoped API keys, CSRF and origin checks, session revocation, MFA and bounded request sizes.
- **Council and agents:** nine adviser roles (Chief of Staff, Strategy, Finance, Operations, Marketing, Technology, Customer Success, Risk and Compliance, Research). Council output is advisory, not verified fact. Durable read-only agent execution uses explicit grants and checkpoints, not unbounded delegation.
- **Workflows:** validated DAGs, version pinning, approval gates, durable runs, outbox and scheduling, idempotency and recovery of interrupted operations. External writes require explicit authorization and must not be replayed automatically if their outcome is uncertain.
- **Financial logic:** deterministic exact monetary arithmetic, append-only journal, statement comparison, settlement evidence, forecasts and reconciliation. User-supplied evidence does not establish independent bank verification.
- **Memory:** tenant-owned relational records, bounded chunking, genuine embeddings where available, lexical/hybrid retrieval, provenance and citation checks. No separate ChromaDB service is required.
- **Inference:** configured Ollama models and supported provider protocols, bounded contexts, quotas, admission control, private PostgreSQL inference queue where configured, and explicit fallback labeling. Local fallback is not genuine AI.
- **Operations:** protected provider lifecycle, encrypted portable archives, retention/deletion, scoped monitoring, readiness checks and operator-controlled deployment.

See the individual Batch E–P engineering records for interfaces, test scope and external requirements. Do not infer live provider verification, independent audit, hosted capacity or offsite recovery from CI.
