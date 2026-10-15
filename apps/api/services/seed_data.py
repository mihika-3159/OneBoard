from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import uuid
from apps.api.models.business import Business
from apps.api.models.entities import Product, Customer, Lead, Invoice, Expense, Commitment, SupportTicket
from apps.api.models.goals_tasks import Goal, Task, Project
from apps.api.models.decision_evidence import Decision, Evidence
from apps.api.models.agent_council import CouncilMeeting, AdviserScorecard
from apps.api.models.memory import MemoryDocument, MemoryChunk, EntityRelationship, MemoryConflict
from apps.api.models.workflow import CustomAgent, WorkflowDefinition
from apps.api.models.integrations import IntegrationAccount
from apps.api.services.memory_engine import memory_engine

DEMO_BUSINESS_ID = "northstar-studio-001"

def seed_northstar_studio(db: Session, reset: bool = False):
    """Generates the full Northstar Studio demonstration SaaS environment."""
    existing = db.query(Business).filter(Business.id == DEMO_BUSINESS_ID).first()
    if existing:
        if not reset:
            return existing
        # Clear existing records for clean reset
        for model in [Business, Product, Customer, Lead, Invoice, Expense, Commitment, SupportTicket,
                      Goal, Task, Project, Decision, Evidence, CouncilMeeting, AdviserScorecard,
                      MemoryDocument, MemoryChunk, EntityRelationship, MemoryConflict,
                      CustomAgent, WorkflowDefinition, IntegrationAccount]:
            db.query(model).delete()
        db.commit()

    now = datetime.utcnow()

    # 1. Business Profile
    business = Business(
        id=DEMO_BUSINESS_ID,
        name="Northstar Studio",
        description="B2B Developer Tooling SaaS providing automated API webhook orchestration and monitoring.",
        industry="B2B Developer SaaS",
        currency="USD",
        timezone="America/New_York",
        business_model="Subscription SaaS",
        products_summary=["Starter Tier ($29/mo)", "Growth Tier ($59/mo)", "Enterprise Tier ($199/mo)"],
        target_customers=["Tech Founders", "DevOps Engineers", "Agencies"],
        strategic_objectives=["Attain $25k MRR", "Maintain 12-month runway", "Achieve 95% automated test coverage"],
        constraints={"max_monthly_ad_spend": 3500.0, "min_runway_months": 6.0},
        founder_preferences={"autonomous_risk_tolerance": "medium", "communication_style": "concise"},
        monthly_burn_rate=12200.0,
        current_cash_balance=132840.0,
        runway_months=7.2
    )
    db.add(business)

    # 2. Products
    p1 = Product(id="prod-1", business_id=DEMO_BUSINESS_ID, name="Starter Plan", tier="Starter", price=29.0, billing_interval="monthly", description="Up to 100k events/mo, 3 endpoints, community support.", active_customers_count=14)
    p2 = Product(id="prod-2", business_id=DEMO_BUSINESS_ID, name="Growth Plan", tier="Growth", price=59.0, billing_interval="monthly", description="Up to 1M events/mo, unlimited endpoints, priority webhooks.", active_customers_count=20)
    p3 = Product(id="prod-3", business_id=DEMO_BUSINESS_ID, name="Enterprise Plan", tier="Enterprise", price=199.0, billing_interval="monthly", description="Dedicated throughput, custom exporter, 99.9% SLA.", active_customers_count=4)
    db.add_all([p1, p2, p3])

    # 3. Customers (38 realistic active SaaS customers)
    sample_customers = [
        ("Sarah Chen", "Acme Technologies", "sarah@acmetech.io", "Enterprise", 199.0, "active", 49.0, 95), # Note contract price $49 discrepancy!
        ("Marcus Vance", "Vance Logistics", "m.vance@vancelog.com", "Growth", 59.0, "active", None, 82),
        ("Elena Rostova", "FinEdge Advisory", "elena@finedge.ch", "Enterprise", 199.0, "active", None, 98),
        ("David Kim", "Nova Labs", "david@novalabs.dev", "Growth", 59.0, "onboarding", None, 70),
        ("Priya Patel", "DevPulse Analytics", "priya@devpulse.io", "Growth", 59.0, "active", None, 91),
        ("Liam O'Connor", "Emerald Cloud", "liam@emeraldcloud.ie", "Starter", 29.0, "active", None, 88),
        ("Amira Mansoor", "Nile Payments", "amira@nilepay.eg", "Growth", 59.0, "active", None, 84),
        ("Carlos Mendes", "Rio Scale", "carlos@rioscale.br", "Growth", 59.0, "churn_risk", None, 58),
        ("Hana Tanaka", "Kyoto Systems", "hana@kyotosys.jp", "Enterprise", 199.0, "active", None, 96),
        ("Lucas Meyer", "Berlin Stream", "lucas@berlinstream.de", "Starter", 29.0, "active", None, 89)
    ]
    # Add remaining to reach 38
    for i in range(11, 39):
        sample_customers.append((f"Client {i}", f"Partner Org {i}", f"user{i}@company{i}.com", "Growth" if i % 2 == 0 else "Starter", 59.0 if i % 2 == 0 else 29.0, "active", None, 80 + (i % 18)))

    for name, comp, email, tier, mrr, status, contract_p, health in sample_customers:
        cust = Customer(
            business_id=DEMO_BUSINESS_ID,
            name=name,
            company=comp,
            email=email,
            tier=tier,
            mrr=mrr,
            status=status,
            contract_price=contract_p,
            health_score=health,
            last_contact_at=now - timedelta(days=3)
        )
        db.add(cust)

    # 4. Leads & Pipeline
    leads = [
        ("Kavita Rao", "CloudNest", "kavita@cloudnest.ai", "Inbound", "Qualified", 1200.0),
        ("Tom Bradley", "Apex Digital", "tom@apexdigital.co", "Webinar", "Proposal", 2400.0),
        ("Julian Thorne", "Vanguard Security", "j.thorne@vanguardsec.net", "Referral", "Won", 3600.0),
        ("Sophie Laurent", "Atelier Paris", "sophie@atelierparis.fr", "Inbound", "Contacted", 700.0)
    ]
    for name, comp, email, src, stage, val in leads:
        db.add(Lead(business_id=DEMO_BUSINESS_ID, name=name, company=comp, email=email, source=src, pipeline_stage=stage, estimated_value=val))

    # 5. Invoices (Paid and Overdue)
    inv1 = Invoice(business_id=DEMO_BUSINESS_ID, customer_name="Acme Technologies", invoice_number="INV-2026-001", amount=199.0, status="paid", due_date=now - timedelta(days=15), paid_at=now - timedelta(days=14))
    inv2 = Invoice(business_id=DEMO_BUSINESS_ID, customer_name="Vance Logistics", invoice_number="INV-2026-002", amount=590.0, status="overdue", due_date=now - timedelta(days=8))
    inv3 = Invoice(business_id=DEMO_BUSINESS_ID, customer_name="Rio Scale", invoice_number="INV-2026-003", amount=1180.0, status="overdue", due_date=now - timedelta(days=12))
    inv4 = Invoice(business_id=DEMO_BUSINESS_ID, customer_name="Nova Labs", invoice_number="INV-2026-004", amount=59.0, status="sent", due_date=now + timedelta(days=5))
    inv5 = Invoice(business_id=DEMO_BUSINESS_ID, customer_name="Apex Digital", invoice_number="INV-2026-005", amount=2400.0, status="overdue", due_date=now - timedelta(days=4))
    db.add_all([inv1, inv2, inv3, inv4, inv5])

    # 6. Expenses
    exp1 = Expense(business_id=DEMO_BUSINESS_ID, category="Infrastructure", vendor="AWS / Cloudflare", amount=3450.0, description="Server cluster & edge ingress")
    exp2 = Expense(business_id=DEMO_BUSINESS_ID, category="Software", vendor="GitHub & Datadog", amount=1200.0, description="Observability & dev tools")
    exp3 = Expense(business_id=DEMO_BUSINESS_ID, category="Marketing", vendor="Search & Developer Ads", amount=2800.0, description="Inbound dev community campaigns")
    exp4 = Expense(business_id=DEMO_BUSINESS_ID, category="Legal", vendor="Startup Legal Counsel", amount=1500.0, description="Terms of service & privacy audits")
    exp5 = Expense(business_id=DEMO_BUSINESS_ID, category="Operations", vendor="Payment & Accounting Fees", amount=3250.0, description="Stripe processing & compliance")
    db.add_all([exp1, exp2, exp3, exp4, exp5])

    # 7. Customer Commitments (Demo Scenario C)
    c1 = Commitment(
        business_id=DEMO_BUSINESS_ID,
        title="Custom Webhook Exporter Delivery",
        counterparty="Sarah Chen (Acme Technologies)",
        counterparty_email="sarah@acmetech.io",
        description="Agreed to ship high-throughput custom exporter for Acme's telemetry pipeline by end of current sprint.",
        deadline=now + timedelta(days=3),
        status="pending",
        risk_level="critical",
        evidence_source="Email: Contract addendum with Acme"
    )
    c2 = Commitment(
        business_id=DEMO_BUSINESS_ID,
        title="SOC2 Compliance Evidence Package",
        counterparty="Elena Rostova (FinEdge Advisory)",
        counterparty_email="elena@finedge.ch",
        description="Provide vendor security questionnaire and pen-test summary.",
        deadline=now + timedelta(days=18),
        status="pending",
        risk_level="medium",
        evidence_source="Meeting Notes: Q1 Enterprise Review"
    )
    db.add_all([c1, c2])

    # 8. Support Tickets
    st1 = SupportTicket(business_id=DEMO_BUSINESS_ID, customer_name="Vance Logistics", subject="Retry rate limit hit on burst traffic", priority="urgent", status="open", proposed_resolution="Increase burst buffer ceiling to 5,000 req/sec.")
    st2 = SupportTicket(business_id=DEMO_BUSINESS_ID, customer_name="Nova Labs", subject="Documentation clarification on HMAC secret rotation", priority="medium", status="open", proposed_resolution="Provide code snippet for zero-downtime key rotation.")
    db.add_all([st1, st2])

    # 9. Goals and Tasks
    g1 = Goal(business_id=DEMO_BUSINESS_ID, title="Reach $25k Monthly Recurring Revenue", target_metric="MRR", baseline_value=18450.0, target_value=25000.0, current_value=18450.0, unit="$", deadline=now + timedelta(days=90), priority="critical")
    g2 = Goal(business_id=DEMO_BUSINESS_ID, title="Extend Cash Runway Beyond 10 Months", target_metric="Runway", baseline_value=7.2, target_value=10.0, current_value=7.2, unit="months", deadline=now + timedelta(days=60), priority="high")
    db.add_all([g1, g2])

    t1 = Task(business_id=DEMO_BUSINESS_ID, title="Complete Custom Webhook Exporter code review", responsible_agent="Technology Adviser", priority="critical", deadline=now + timedelta(days=2), status="todo")
    t2 = Task(business_id=DEMO_BUSINESS_ID, title="Send invoice reminders to overdue accounts", responsible_agent="Operations Adviser", priority="high", deadline=now + timedelta(days=1), status="todo")
    t3 = Task(business_id=DEMO_BUSINESS_ID, title="Reconcile pricing discrepancies across documentation", responsible_agent="Chief of Staff", priority="medium", deadline=now + timedelta(days=4), status="todo")
    db.add_all([t1, t2, t3])

    # 10. Memory Documents & Deliberate Conflict Staging (Demo Scenario A)
    doc1 = memory_engine.add_document_with_chunks(
        db, DEMO_BUSINESS_ID,
        title="Official Pricing Guide 2026.pdf",
        raw_content="Northstar Studio Pricing Guide:\n\nStarter Plan: $29/month.\nGrowth Plan: $59/month for growing engineering teams.\nEnterprise Plan: $199/month including custom integrations and dedicated support.",
        file_type="pdf"
    )
    doc2 = memory_engine.add_document_with_chunks(
        db, DEMO_BUSINESS_ID,
        title="Acme Technologies Custom Proposal.docx",
        raw_content="Customer Proposal for Acme Technologies (Sarah Chen):\n\nWe propose standard Growth tier provisioning at a discounted promotional rate of $49/month with an agreed 12-month commitment.",
        file_type="txt"
    )

    # Conflict Record
    conflict = MemoryConflict(
        business_id=DEMO_BUSINESS_ID,
        entity_type="Product.price",
        entity_name="Growth Tier Price Discrepancy",
        source_a_name="Official Pricing Guide 2026.pdf",
        source_a_value="$59/month",
        source_b_name="Acme Proposal.docx",
        source_b_value="$49/month",
        discrepancy_classification="customer_specific_contract",
        explanation="Published catalog specifies $59/mo, while bespoke customer proposal references $49/mo contract pricing.",
        suggested_resolution="Confirm contract clause: preserve $49/mo for Acme contract record while keeping public tier at $59/mo.",
        status="unresolved"
    )
    db.add(conflict)

    # 11. Entity Relationships (Graph memory)
    r1 = EntityRelationship(business_id=DEMO_BUSINESS_ID, source_type="Customer", source_id="Sarah Chen", source_label="Sarah Chen (Acme)", relationship="owns", target_type="Commitment", target_id="c1", target_label="Custom Webhook Exporter")
    r2 = EntityRelationship(business_id=DEMO_BUSINESS_ID, source_type="Product", source_id="prod-2", source_label="Growth Plan ($59)", relationship="promotes", target_type="Customer", target_id="David Kim", target_label="Nova Labs")
    r3 = EntityRelationship(business_id=DEMO_BUSINESS_ID, source_type="Task", source_id="t1", source_label="Code Review", relationship="depends_on", target_type="Commitment", target_id="c1", target_label="Custom Webhook Exporter")
    db.add_all([r1, r2, r3])

    # 12. Historical Decision & Scorecard with Inaccurate Prediction (Demo Scenario E)
    historical_decision = Decision(
        business_id=DEMO_BUSINESS_ID,
        title="Q1 Inbound Developer Growth Campaign",
        business_context="Launched paid developer ad campaign across social and technical newsletters to accelerate trial signups.",
        advisers_consulted=["Marketing Adviser", "Finance Adviser", "Chief of Staff"],
        recommendations_summary="Marketing Adviser recommended allocating $3,000 to technical newsletter sponsorships.",
        dissenting_opinions=[{"adviser": "Finance Adviser", "objection": "Estimated CAC was overly optimistic based on historical benchmarks."}],
        assumptions=[
            {"id": "h1", "text": "Newsletter CTR will exceed 2.4%", "status": "failed"},
            {"id": "h2", "text": "Trial to paid conversion holds at 8%", "status": "valid"}
        ],
        founder_decision="approved",
        expected_outcomes=[
            {"metric": "Qualified Leads", "predicted_value": 50.0, "timeframe_days": 30}
        ],
        actual_outcomes=[
            {"metric": "Qualified Leads", "predicted_value": 50.0, "actual_value": 14.0, "absolute_error": 36.0, "percentage_error": 72.0, "verified_at": (now - timedelta(days=10)).isoformat(), "notes": "CTR was only 0.8%, missing forecast significantly."}
        ],
        outcome_verified=True,
        outcome_notes="Marketing Adviser forecast was inaccurate; Finance Adviser's reservation was validated."
    )
    db.add(historical_decision)

    # Adviser Scorecards
    for role_name, info in [
        ("Chief of Staff", "Executive Office"),
        ("Finance Adviser", "Finance"),
        ("Marketing Adviser", "Growth"),
        ("Operations Adviser", "Operations"),
        ("Technology Adviser", "Engineering"),
        ("Customer Success Adviser", "Customer Success"),
        ("Strategy Adviser", "Strategy"),
        ("Risk and Compliance Adviser", "Legal & Risk"),
        ("Research Adviser", "Research")
    ]:
        err = 72.0 if role_name == "Marketing Adviser" else 8.5
        db.add(AdviserScorecard(
            business_id=DEMO_BUSINESS_ID,
            adviser_name=role_name,
            department=info,
            total_recommendations=6 if role_name in ["Chief of Staff", "Finance Adviser", "Marketing Adviser"] else 3,
            approved_recommendations=5,
            predictions_tracked=2 if role_name == "Marketing Adviser" else 1,
            average_prediction_error_pct=err,
            evidence_completeness_score=0.94 if role_name == "Research Adviser" else 0.88,
            action_completion_rate=0.90,
            verified_outcome_rate=0.86
        ))

    # 13. Reusable Workflow Library Templates
    wf_template = WorkflowDefinition(
        business_id=DEMO_BUSINESS_ID,
        name="Weekly Overdue Invoice & Reminder Dispatch",
        description="Audits open customer receivables, calculates outstanding totals, and drafts personalized reminders with founder approval.",
        category="Finance & Receivables",
        trigger_type="schedule",
        trigger_config={"cron": "0 9 * * 5", "frequency": "Weekly Friday at 9:00 AM"},
        is_active=True,
        is_template=True,
        nodes=[
            {"id": "node_1", "type": "trigger", "position": {"x": 50, "y": 180}, "data": {"label": "Schedule Trigger (Friday 9 AM)", "connector": "scheduler"}},
            {"id": "node_2", "type": "data_fetch", "position": {"x": 320, "y": 180}, "data": {"label": "Audit Overdue Invoices", "connector": "demo_finance"}},
            {"id": "node_3", "type": "calculate", "position": {"x": 590, "y": 180}, "data": {"label": "Calculate Total Balance", "formula": "sum"}},
            {"id": "node_4", "type": "approval", "position": {"x": 860, "y": 180}, "data": {"label": "Founder Approval Gate", "risk": "high"}},
            {"id": "node_5", "type": "action", "position": {"x": 1130, "y": 180}, "data": {"label": "Dispatch Reminder Emails", "connector": "demo_email"}}
        ],
        edges=[
            {"id": "e1-2", "source": "node_1", "target": "node_2"},
            {"id": "e2-3", "source": "node_2", "target": "node_3"},
            {"id": "e3-4", "source": "node_3", "target": "node_4"},
            {"id": "e4-5", "source": "node_4", "target": "node_5"}
        ],
        estimated_time_saved_hours=3.5,
        recommended_by="Operations Adviser"
    )
    db.add(wf_template)

    # 14. Custom Agent in Agent Studio
    custom_agent = CustomAgent(
        business_id=DEMO_BUSINESS_ID,
        name="Customer Onboarding Specialist",
        role_title="Onboarding & Retention Agent",
        department="Customer Success",
        description="Assists newly registered SaaS users with webhook configurations, identifies stalled setups, and drafts check-in messages.",
        system_prompt="You are Northstar Studio's Customer Onboarding Specialist. Monitor new signups and proactively suggest configuration guidance.",
        selected_model="qwen2.5:7b",
        allowed_tools=["read_crm", "check_product_telemetry", "draft_email"],
        requires_approval_for=["send_email"],
        max_steps=4
    )
    db.add(custom_agent)

    # 15. Integration Accounts
    integrations = [
        ("local_files", "Local Files & Storage", "connected", True),
        ("demo_crm", "Customer CRM & Pipeline", "connected", True),
        ("demo_finance", "Finance & Invoicing Ledger", "connected", True),
        ("demo_email", "Email Service (Demo Adapter)", "connected", True),
        ("demo_calendar", "Executive Calendar", "connected", True),
        ("github", "GitHub Repository Connector", "connected", True),
        ("notion", "Notion Workspace Connector", "connected", True),
        ("google", "Google Workspace (Sheets/Drive)", "auth_required", False)
    ]
    for c_type, name, stat, is_m in integrations:
        db.add(IntegrationAccount(
            business_id=DEMO_BUSINESS_ID,
            connector_type=c_type,
            name=name,
            status=stat,
            is_mock=is_m,
            last_sync=now - timedelta(hours=1),
            records_synced={"records": 42}
        ))

    db.commit()
    db.refresh(business)
    return business
