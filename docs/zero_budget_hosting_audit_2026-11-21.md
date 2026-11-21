# OneBoard zero-budget hosted SaaS feasibility audit (21 November 2026)

**Scope:** public multi-tenant FastAPI/React application, PostgreSQL, background execution, LLM inference, operations. User is under 18 in UAE, **no parental consent and no spending/payment card**. This is a sourcing/feasibility audit, **not** live deployment testing or legal advice. Do not open accounts or assume eligibility when terms are ambiguous.

## Essential competition constraint

Dubai Create AI Agents Championship official rules: January 2027 submission requires prototype, pitch deck and demo video; May 2027 finalists demonstrate a fully working AI Agent live. Entry must be at idea/prototype/early-MVP stage and **not already fully commercialized**. No published blanket requirement for public 24/7 hosting throughout the contest. Full functional readiness and commercial launch are different.
Source: https://www.dubaichamberdigital.com/en/create-ai-agents

## Hosting candidates and exclusions (official vendor sources, accessed 21 Nov 2026)

| Provider/service | Free technical offer | Age/consent and constraints | Verdict |
|---|---|---|---|
| Enzonic Python | 1 always-on free Python host, 512 MB RAM, 50% CPU, 10 GB SSD, no card; claimed free capacity subject to availability. | Enzonic generic hosting TOS says age >=13 or local digital-consent age, but no explicit verification that UAE minor can execute these terms without guardian. Separate Enzonic Clips terms require guardian agreement, **do not conflate product-specific terms**. 512 MB cannot host Ollama 7B and likely cannot support heavy concurrency; no production SLA verified. | **Priority technical proof-of-concept, not minor-eligibility cleared or certified** |
| HelioHost Johnny/Tommy | Free Python, Django/Flask, PostgreSQL, SSL, 1 GB storage, no stated payment needed. | Terms say >=13, ban banking/investment/credit-like financial services, and restrict free hosts to noncommercial use (hobby projects and new microbusiness subject to review). Johnny uptime goal 97%, **not an SLA**; monthly panel login required. Verify whether OneBoard financial analysis qualifies as prohibited before deploying. | Potential **noncommercial demo backup**, not production financial SaaS |
| Netlify Free | Static hosting, functions, database, hard 300-credit monthly limit; no charges on free tier. | Self-Serve Subscription Agreement sec. 2.2 says 13+ but higher local minimum ages can apply; some AI features 18+; service suspension / no uptime SLA on free tier. Must confirm UAE minor account eligibility. | Good **frontend/static demo candidate**, not full background worker |
| Vercel Hobby | Free static/React/Next and short serverless functions; age minimum 16 in 19 October 2026 TOS. | Hobby strictly personal or noncommercial; application with actual commercial SaaS use is out of scope. Time-limited serverless cannot host persistent scheduler or local Ollama. | **Noncommercial presentation frontend** candidate, not full SaaS |
| Hugging Face | Accounts age >=13. Static Spaces free; free accounts in good standing may have up to 2 Gradio ZeroGPU Spaces, with visitor usage quota. | New ordinary Gradio/Docker CPU Basic Spaces require PRO/paid account despite CPU hourly price $0. Free ZeroGPU limited and not a drop-in persistent FastAPI+Ollama host. | Experimental **AI demonstration** only |
| Neon PostgreSQL | 2026 Free tier claims 100 projects and 1 GB/project, limited compute. | Current Neon platform terms incorporate Databricks MCSA; do not rely on outdated Neon EULA (>16) alone. No affirmative no-consent UAE minor eligibility or backup/RPO/SLA proof. | Best **database technical candidate**, legally/operationally **unconfirmed** |
| Enzonic Databases | Advertises free scale-to-zero PostgreSQL, short backup retention, no card. | Different Enzonic product pages give **conflicting free allocations** (5 DB at 1 GB each versus 10 DB at 3 GB each). Cannot trust exact current quota without signup verification; TOS minor issues remain. | Fallback DB experiment only |
| Supabase Free | PostgreSQL 500 MB, 2 projects, may pause after week of inactivity; no managed automatic backups on Free. | Contract requires legal power/authority. No explicit standalone authorization for UAE minor without consent established. | **Not cleared**; additional backups needed |
| Render Free | Python app works but spins down after idle; free Postgres expires after 30 days; provider says free not for production. | Age/binding-contract capacity not cleared for an unaccompanied minor. Persistent disk/jobs require paid tier. | Demo only, **not recommended** |
| PythonAnywhere Beginner | Free restricted web app with one worker, limited outbound networking and no always-on jobs. | TOS section 5 explicitly requires legal age to form binding contract. | **Excluded** |
| Railway | TOS 16+ but if under age of legal contract requires guardian agreement; usage credits finite. | Parent/guardian unavailable. | **Excluded** |
| Replit | Basic access 13+, but current TOS says under 18 requires guardian permission. | Parent/guardian unavailable. | **Excluded** |
| Deno Deploy | Serverless JavaScript host. | Terms explicitly require age >=18. | **Excluded** |
| GroqCloud | Free development API with quotas. | Cloud Services Agreement requires age >=18. | **Excluded** |
| OpenRouter | Some free models without credit purchase (50 requests/day base), rate-limited. | Terms require age >=18. | **Excluded** |
| Google AI Studio / Gemini API | Free API quota for certain models, but content can be used for model improvements. | Gemini API additional terms require age >=18. | **Excluded** |
| Cerebras | Current developer pricing uses credit linked to valid payment method; promotional credit expires. | No-card budget prohibits this route. | **Excluded** |
| GitHub Models | Former free inference API. | Retired 30 July 2026. | **Unavailable** |
| AWS Educate | Educational labs at zero cost, no card. | Learner terms require involvement of parent/guardian/educator for under-18; lab environment not durable hosting (time limited). | **Not long-lived hosting** |
| Cloudflare Workers/Workers AI | Free Workers 100k requests/day, 10ms CPU/request; Workers AI 10k neurons/day. | Cloudflare account's unaccompanied-minor eligibility not confirmed; Python Workers ASGI support does not guarantee existing SQLAlchemy/worker architecture compatibility. | **Research only**, not eligibility-cleared |
| HelioHost banking classification | Financial dashboard is analysis, not a payment/banking platform, but terms prohibit certain financial services. | Do not assume exemption. Seek written vendor clarification for public SaaS. | Blocked pending clarification |

## Architecture implications from current repo

- `apps/api/core/config.py` requires production PostgreSQL, HTTPS-only CORS, secure cookies, strong auth secret, demo mode off. Do **not** downgrade these checks to deploy on SQLite for real founder data.
- `apps/api/requirements.txt` has FastAPI, SQLAlchemy, pydantic, APScheduler, openpyxl, pypdf, etc. A 512 MB host **requires measured cold-start, steady-state and peak memory**, not assumption.
- Ollama model profiles include 7B/8B/14B; they will **not** run alongside API on a 512 MB free host. AI inference requires separate eligible computing infrastructure or a reproducible local-model live demonstration.
- Scheduled jobs/approval continuation need durable DB state and a safe leased/locked executor. Serverless sleep + in-process APScheduler cannot meet that gate.
- Provider database availability != data durability. An off-site encrypted backup, tested restore, encryption, retention, tenant boundaries, log redaction, upgrade/rollback and secrets rotation are release requirements.
- A free-host website may be a **demo**, but a hosted multi-tenant system accepting sensitive real customer data must pass independent operations and security tests. No unverified 'Level 3 certified' language.

## Zero-cost experiments to run (in order, only after provider eligibility is affirmed)

1. Use **disposable credentials and synthetic data only**. Confirm provider explicitly permits a 17-year-old UAE account holder without guardian signature and without billing method, and permits public SaaS/hackathon use. If not proven, stop.
2. Build a minimal isolated FastAPI `/health` release candidate on Enzonic Python; measure startup, idle/resume, uptime, memory and service restarts for 48h. Don't expose OneBoard's private repo, secrets or endpoints just for this experiment.
3. Test a synthetic-data PostgreSQL instance on eligible Neon/other vendor with TLS, connection pooling, Alembic migrations, concurrent login throttle, tenant isolation and restart recovery. Measure backup/restore.
4. Test a static frontend on age-eligible Vercel Hobby/Netlify with a limited **noncommercial hackathon demo**, no live financial/customer data.
5. Check whether a separately hosted, consent-eligible free model endpoint exists. Never pass real business records to trial/free model providers with unclear prompt privacy/training policies. If no endpoint qualifies, keep full Ollama on local controlled hardware for recording/judging.
6. Run complete founder E2E, authorization, load, failover, data restoration and deployment smoke checks. Require a written go/no-go decision on 6 Dec.

## Sources

- Competition: https://www.dubaichamberdigital.com/en/create-ai-agents
- Enzonic Python: https://www.enzonic.com/python
- Enzonic TOS: https://enzonic.com/legal/tos
- Enzonic DB: https://www.enzonic.com/cloud/databases and https://databases.enzonic.com/
- HelioHost TOS: https://heliohost.org/terms/
- HelioHost offerings: https://wiki.helionet.org/Johnny
- Netlify Free: https://www.netlify.com/pricing/
- Netlify Self-Serve: https://www.netlify.com/pdf/self-serve-subscription-agreement.pdf
- Vercel TOS: https://vercel.com/legal/terms
- Vercel Hobby: https://vercel.com/docs/plans/hobby
- HF Spaces: https://huggingface.co/docs/hub/spaces-overview and https://huggingface.co/terms-of-service
- Neon plans: https://neon.com/blog/neon-free-plan-1-gb-per-project
- Neon current legal: https://neon.com/platform-terms and https://www.databricks.com/legal/mcsa
- Supabase: https://supabase.com/terms and https://supabase.com/docs/guides/platform/free-project-pausing
- Render: https://render.com/docs/free
- PythonAnywhere TOS: https://www.pythonanywhere.com/terms_v2/
- Railway: https://railway.com/legal/terms
- Replit: https://replit.com/terms-of-service
- Deno: https://docs.deno.com/deploy/terms_and_conditions/
- Groq: https://console.groq.com/docs/legal/services-agreement
- OpenRouter: https://openrouter.ai/terms
- Google API: https://ai.google.dev/gemini-api/terms
- Cerebras: https://www.cerebras.ai/pricing
- GitHub Models: https://github.blog/changelog/2026-07-30-github-models-is-now-retired/
- AWS Educate: https://aws.amazon.com/legal/learner-terms-conditions/
- Cloudflare Workers/AI: https://developers.cloudflare.com/workers/platform/limits/ and https://developers.cloudflare.com/workers-ai/platform/pricing/

**Audit result:** no currently verified full stack simultaneously supports zero spend, no-card, age/no-consent eligibility, full Ollama inference, production-grade hosted multi-tenant durability and uninterrupted service. Unresolved account eligibility is a hard blocker, not a license to bypass terms.
