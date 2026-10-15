# OneBoard System Architecture & Technical Specifications

## Architectural Topology

OneBoard uses a clean layered architecture designed for local execution, low latency, robust data isolation, and high resilience:

```
┌─────────────────────────────────────────────────────────────┐
│                    Presentation Layer                       │
│    React 18 + Vite SPA · Tailwind CSS · Glassmorphism UI    │
│  State Management · Lucide Icons · SSE Stream Processing    │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / SSE / WebSockets
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Gateway Layer                    │
│    Request Validation · Dependency Injection · CORS Config  │
│  Authentication · Rate Limiting · Dynamic Routing Router    │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
┌───────────────▼───────────────┐ ┌─────────────▼─────────────┐
│    Multi-Agent Orchestration  │ │  Workflow Runtime Engine  │
│  7 Domain Advisers (Council)  │ │  DAG Engine · Cycle Check │
│  Adversarial Challenge Graph  │ │  HITL Approval Gates      │
│  Synthesis & Sovereign Veto   │ │  Deterministic Tool Call  │
└───────────────┬───────────────┘ └─────────────┬─────────────┘
                │                               │
┌───────────────▼───────────────────────────────▼─────────────┐
│              Deterministic Business & Data Layer            │
│  Financial Math (MRR/Runway) · Evidence Content Hashing     │
│  Empirical Error Recalibration · Audit Trail Recording      │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
┌───────────────▼───────────────┐ ┌─────────────▼─────────────┐
│     Inference Gateway Layer   │ │   Persistence Vault       │
│  Ollama Local Daemon (Airgap) │ │   SQLite / PostgreSQL     │
│  Multi-Provider Fallback      │ │   ChromaDB Vector Store   │
│  Deterministic Simulation     │ │   Local File Document Hub │
└───────────────────────────────┘ └───────────────────────────┘
```

---

## 1. Multi-Agent Council Protocol

The Agent Council uses a LangGraph-inspired directed execution graph:
1. **Context Ingestion**: Retrieves verified evidence records, current business state, and recent decision outcomes.
2. **Independent Agent Evaluation**: The 7 domain advisers evaluate the proposal in parallel with distinct prompt boundaries:
   - `Chief of Staff`: Strategic coherence, priority alignment.
   - `Finance Adviser`: Unit economics, runway implications, budget limits.
   - `Marketing Adviser`: Funnel velocity, target audience positioning, CAC.
   - `Operations Adviser`: Capacity constraints, tool dependencies.
   - `Product Adviser`: Feature scope, user impact.
   - `Legal Counsel`: Contractual clauses, IP rights, regulatory liabilities.
   - `Technology Adviser`: Scalability, architectural complexity, tech debt.
3. **Structured Challenge Round**: Advisers cross-examine each other's claims. If a recommendation violates financial or operational constraints, counter-arguments are generated.
4. **Synthesis Protocol**: Highlights points of unanimous agreement, contested recommendations, and trade-off matrices.
5. **Founder Gate**: Commits decision only upon founder approval, registering expected numeric metrics.

---

## 2. Deterministic Financial Core

All business arithmetic is calculated in pure Python:
- **MRR**: $\sum (\text{Active Monthly Subscriptions}) + \sum (\text{Annual Subscriptions} / 12)$
- **Net Burn Rate**: $\text{Monthly Operating Expenses} - \text{Monthly Revenue}$
- **Runway**: $\frac{\text{Current Cash Balance}}{\text{Net Monthly Burn Rate}}$
- **Unit Economics**: Customer Acquisition Cost (CAC) vs. Customer Lifetime Value (LTV).

No LLM generates or approximates financial statistics, eliminating mathematical hallucinations.

---

## 3. Workflow Execution Runtime

- **DAG Representation**: Workflows are stored as structured JSON nodes and directional edges.
- **Cycle Detection**: Validated via depth-first search graph traversal prior to execution.
- **Human-in-the-Loop (HITL)**: Nodes marked `approval_required: true` transition the workflow run into `awaiting_approval` status, emitting an SSE notification to the founder UI. Execution resumes only when the founder approves via the API.
- **Sandboxed Tool Registry**: Registered tools operate on validated Python types without shell or subprocess invocation privileges.

---

## 4. Multi-Model Gateway & Offline Airgap

- **Primary Inference**: Local Ollama server (`http://localhost:11434`) running lightweight open-weight models (`qwen2.5:1.5b`, `llama3.2:1b`, `phi3.5`).
- **Dynamic Task Routing**: Small models for quick categorizations and summarization; reasoning models for multi-agent synthesis.
- **Deterministic Heuristic Fallback**: If Ollama or cloud connections are unavailable, OneBoard activates its rule-based heuristic generator, guaranteeing that the application remains fully testable, demonstrable, and operable anywhere without active API keys.
