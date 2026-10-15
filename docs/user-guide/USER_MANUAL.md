# OneBoard User Manual & Operator Guide

Welcome to **OneBoard**, the AI Operating System for solo founders and micro-businesses. This guide walks you through every major module of the platform.

---

## Getting Started

1. **Launch the Application**: Run `.\scripts\run_all.ps1` or start the FastAPI backend on port 8000 and Vite frontend on port 5173.
2. **Access the Web Dashboard**: Open your browser to `http://localhost:5173`.
3. **Explore Pre-Seeded Workspace**: OneBoard loads automatically with **NorthStar Studio**, a pre-configured design and software agency with realistic financial records, client accounts, past council meetings, and automated workflows.

---

## 1. Executive Dashboard

The **Overview** tab gives you a real-time status display of your solo enterprise:
- **Vital Metrics Bar**: Current Cash Balance, Monthly Recurring Revenue (MRR), Monthly Burn Rate, and Estimated Runway in months.
- **Runway Health Indicator**: Visual status warning (Green: >12 months, Yellow: 6-12 months, Red: <6 months).
- **Recent Council Decisions**: Quick view of recent approvals, objections, and scheduled outcome review dates.
- **Pending Action Items**: Tasks generated from recent board reviews requiring founder action.
- **Active Workflow Status**: Live indicators of automated background pipelines.

---

## 2. Multi-Agent Boardroom (Council Deliberation)

Convene your autonomous advisory council anytime you face a critical business decision:
1. Navigate to the **Boardroom** tab.
2. Click **"Convene New Council"**.
3. Choose a **Meeting Agenda Template** (e.g., Weekly Executive Review, Pricing Strategy, Hiring vs. Contracting, Product Launch, Operational Incident).
4. Select which advisers should attend (Chief of Staff, CFO, CMO, COO, CPO, Legal Counsel, CTO).
5. Enter your decision topic or business dilemma and click **"Begin Deliberation"**.
6. Watch the real-time deliberation stream as advisers deliver domain analyses, challenge one another's assumptions, and synthesize consensus recommendations.
7. Review the **Synthesis & Trade-offs** panel, add any founder notes, and choose **Approve**, **Modify**, or **Reject**.

---

## 3. Workflow Studio

Automate repetitive operational processes with built-in safety controls:
1. Navigate to the **Workflows** tab.
2. View existing active workflows (such as the *Lead Qualification Pipeline* or *Invoice Processing*).
3. Click **"Run Workflow"** to execute a pipeline.
4. **Approval Gates**: If a step requires founder sign-off (e.g., issuing an outbound proposal or committing budget), the workflow automatically pauses in `Awaiting Approval` state.
5. Review the execution log, inspect step outputs, and click **"Approve & Continue"** or **"Reject"**.

---

## 4. Evidence Vault

Maintain a single source of truth for your business:
1. Navigate to the **Evidence** tab.
2. View imported documents, customer contracts, financial statements, and CRM snapshots.
3. Click **"Upload Evidence"** to ingest CSV, XLSX, PDF, Markdown, or JSON files.
4. OneBoard automatically computes SHA-256 cryptographic hashes for tamper-proof provenance and extracts key entities for context retrieval during council deliberations.

---

## 5. Accountability Ledger

Eliminate hallucinated claims and measure whether AI advice actually produces real-world results:
1. Navigate to the **Accountability** tab.
2. View the **Adviser Accuracy Scorecards**: Inspect each adviser's recommendation history, approval rate, and average prediction error percentage.
3. View the **Decision Outcome Registry**: Track decisions whose review date has arrived.
4. Enter the actual real-world metric (e.g., target was 50 leads, actual was 45).
5. The system automatically calculates absolute and percentage error rates and updates the adviser's historical calibration score.

---

## 6. AI Model Gateway & Settings

Configure your inference preferences:
1. Navigate to the **Settings** tab.
2. View the status of your local **Ollama** daemon.
3. Toggle between local offline models (zero cost, 100% private) and optional cloud providers (Gemini, Anthropic, OpenAI).
4. Perform one-click database re-seeding or export audit logs.
