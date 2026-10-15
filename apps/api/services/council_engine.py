from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import logging
from apps.api.models.agent_council import CouncilMeeting, AdviserScorecard
from apps.api.models.decision_evidence import Decision, Evidence
from apps.api.models.goals_tasks import Task
from apps.api.models.entities import Invoice, Expense, Customer, Product
from apps.api.models.business import Business
from apps.api.services.ollama_gateway import ollama_gateway

logger = logging.getLogger(__name__)

COUNCIL_ROLES = {
    "Chief of Staff": {
        "title": "Chief of Staff & Board Coordinator",
        "department": "Executive Office",
        "focus": "Deliberation facilitation, strategic alignment, conflict resolution, agenda tracking"
    },
    "Strategy Adviser": {
        "title": "VP of Strategy",
        "department": "Strategy",
        "focus": "Business model resilience, competitive moat, unit economics, market positioning"
    },
    "Finance Adviser": {
        "title": "Chief Financial Officer (Deterministic Engine)",
        "department": "Finance",
        "focus": "Cash runway, burn rate, EBITDA, billing optimizations, price elasticity"
    },
    "Operations Adviser": {
        "title": "VP of Operations",
        "department": "Operations",
        "focus": "Process automation, operational bottlenecks, delivery SLAs, resource capacity"
    },
    "Marketing Adviser": {
        "title": "Chief Marketing Officer",
        "department": "Growth",
        "focus": "CAC, pipeline velocity, funnel conversion, messaging, customer acquisition"
    },
    "Technology Adviser": {
        "title": "Chief Technology Officer",
        "department": "Engineering",
        "focus": "System architecture, tech debt, security posture, delivery velocity, infrastructure"
    },
    "Customer Success Adviser": {
        "title": "VP of Customer Success",
        "department": "Customer Success",
        "focus": "Net revenue retention (NRR), churn prevention, onboarding satisfaction, support SLAs"
    },
    "Risk and Compliance Adviser": {
        "title": "General Counsel & Risk Officer",
        "department": "Legal & Risk",
        "focus": "Contractual liabilities, privacy (GDPR/local), regulatory hazards, operational exposure"
    },
    "Research Adviser": {
        "title": "Head of Market Intelligence",
        "department": "Research",
        "focus": "Evidence validation, fact-checking, counter-evidence, source provenance verification"
    }
}

class CouncilEngine:
    """
    Orchestrates the Multi-Agent Executive Deliberation Protocol.
    Runs structured, grounded stages:
    1. Context Preparation & Evidence Retrieval
    2. Independent Specialist Analysis
    3. Grounded Adversarial Challenge Round
    4. Synthesis & Consensus Recommendation
    5. Immutable Decision Record & Task Generation
    """

    def _calculate_deterministic_financials(self, db: Session, business_id: str) -> Dict[str, Any]:
        """Calculates exact financial metrics directly from database records without hallucinations."""
        biz = db.query(Business).filter(Business.id == business_id).first()
        cash_balance = float(biz.current_cash_balance) if (biz and biz.current_cash_balance is not None) else 0.0

        invoices = db.query(Invoice).filter(Invoice.business_id == business_id).all()
        expenses = db.query(Expense).filter(Expense.business_id == business_id).all()
        customers = db.query(Customer).filter(Customer.business_id == business_id, Customer.status == "active").all()
        
        total_revenue_paid = sum(float(i.amount or 0.0) for i in invoices if i.status == "paid")
        total_revenue_overdue = sum(float(i.amount or 0.0) for i in invoices if i.status == "overdue")
        total_monthly_expenses = sum(float(e.amount or 0.0) for e in expenses)
        total_mrr = sum(float(c.mrr or 0.0) for c in customers)
        
        net_burn = round(total_monthly_expenses - total_mrr, 2)
        is_profitable = net_burn <= 0.0
        
        if is_profitable:
            runway_months = 999.0
            runway_status = "profitable"
        elif cash_balance <= 0.0:
            runway_months = 0.0
            runway_status = "depleted"
        else:
            runway_months = round(cash_balance / net_burn, 1)
            runway_status = "healthy" if runway_months >= 12.0 else ("warning" if runway_months >= 6.0 else "critical")

        return {
            "mrr": round(total_mrr, 2),
            "monthly_expenses": round(total_monthly_expenses, 2),
            "net_burn": net_burn,
            "cash_balance": round(cash_balance, 2),
            "is_profitable": is_profitable,
            "runway_months": runway_months,
            "runway_status": runway_status,
            "overdue_receivables": round(total_revenue_overdue, 2),
            "active_paying_customers": len(customers)
        }

    async def conduct_deliberation(
        self,
        db: Session,
        business_id: str,
        title: str,
        meeting_type: str,
        topic: str,
        selected_advisers: Optional[List[str]] = None
    ) -> CouncilMeeting:
        if not selected_advisers:
            selected_advisers = ["Chief of Staff", "Strategy Adviser", "Finance Adviser", "Marketing Adviser", "Operations Adviser"]
            
        financials = self._calculate_deterministic_financials(db, business_id)
        
        # Retrieve relevant evidence from Vault to ground deliberation
        evidence_records = db.query(Evidence).filter(Evidence.business_id == business_id).limit(5).all()
        evidence_snippets = [f"[{e.title}]: {e.snippet[:180]}..." for e in evidence_records]
        evidence_context = "\n".join(evidence_snippets) if evidence_snippets else "No verified documents uploaded yet."
        
        # Stage A: Context Preparation
        meeting = CouncilMeeting(
            business_id=business_id,
            title=title,
            meeting_type=meeting_type,
            topic=topic,
            advisers_present=selected_advisers,
            retrieved_evidence_ids=[e.id for e in evidence_records],
            stage="deliberating"
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        deliberation_transcript = []
        adviser_positions: Dict[str, str] = {}
        
        # Stage B: Independent Analysis per Adviser
        for adviser_name in selected_advisers:
            role_info = COUNCIL_ROLES.get(adviser_name, {})
            
            prompt = (
                f"You are the {adviser_name} ({role_info.get('title')}) on the virtual board of a solo founder company.\n"
                f"Financial Context: MRR=${financials['mrr']}, Net Monthly Burn=${financials['net_burn']}, "
                f"Cash Balance=${financials['cash_balance']}, Runway={financials['runway_months']} months, "
                f"Overdue Receivables=${financials['overdue_receivables']}.\n"
                f"Retrieved Business Evidence:\n{evidence_context}\n"
                f"Meeting Topic: '{topic}'\n"
                f"Provide your structured position for '{topic}':\n"
                f"1. Concrete Recommendation\n2. Key Assumptions\n3. Primary Risk\n4. Measurable Target Metric"
            )
            
            res = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=f"Act as {adviser_name}. Department: {role_info.get('department')}. Focus: {role_info.get('focus')}.",
                format_json=False
            )
            
            content = res.get("content", "")
            is_simulated = res.get("simulated", False)
            
            # Ground simulated responses specifically in the topic if offline
            if is_simulated and not content:
                content = (
                    f"**Analysis from {adviser_name} on '{topic}':**\n"
                    f"- Recommendation: Address '{topic}' while protecting cash balance (${financials['cash_balance']:,.2f}) "
                    f"and maintaining MRR trajectory (${financials['mrr']:,.2f}).\n"
                    f"- Key Assumption: Current customer base ({financials['active_paying_customers']} clients) remains stable.\n"
                    f"- Operational Risk: Premature resource allocation without verifying return on capital.\n"
                    f"- Target Metric: Resolve within 30 days while ensuring net burn does not exceed ${financials['net_burn']:,.2f}/mo."
                )
                
            adviser_positions[adviser_name] = content
            deliberation_transcript.append({
                "adviser": adviser_name,
                "role": role_info.get("title"),
                "department": role_info.get("department"),
                "stage": "independent_analysis",
                "content": content,
                "inference_engine": "offline_simulated" if is_simulated else "local_ollama",
                "timestamp": datetime.utcnow().isoformat()
            })

        # Stage C: Grounded Adversarial Challenge Round
        # Find 2 advisers to debate based on present roles
        challengers = []
        if "Finance Adviser" in selected_advisers and "Marketing Adviser" in selected_advisers:
            challengers = ("Finance Adviser", "Marketing Adviser")
        elif "Finance Adviser" in selected_advisers and "Operations Adviser" in selected_advisers:
            challengers = ("Finance Adviser", "Operations Adviser")
        elif "Operations Adviser" in selected_advisers and "Technology Adviser" in selected_advisers:
            challengers = ("Operations Adviser", "Technology Adviser")
        elif len(selected_advisers) >= 2:
            challengers = (selected_advisers[1], selected_advisers[0])

        if challengers:
            a1, a2 = challengers
            pos1 = adviser_positions.get(a1, "")[:200]
            pos2 = adviser_positions.get(a2, "")[:200]
            
            challenge_prompt = (
                f"You are the {a1}. Review {a2}'s position on '{topic}':\n\"{pos2}\"\n"
                f"Provide a sharp, critical counter-argument or operational constraint regarding '{topic}' "
                f"in light of MRR=${financials['mrr']} and Net Burn=${financials['net_burn']}."
            )
            c1_res = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": challenge_prompt}],
                system_prompt=f"Act as {a1}. Department: {COUNCIL_ROLES.get(a1, {}).get('department')}.",
                format_json=False
            )
            c1_text = c1_res.get("content", "")
            if not c1_text or c1_res.get("simulated"):
                c1_text = (
                    f"OBJECTION TO {a2.upper()}: Regarding '{topic}', proposing aggressive commitments "
                    f"without immediate receivables collection (${financials['overdue_receivables']:,.2f} overdue) "
                    f"threatens working capital. We must condition action on positive cash flow safeguards."
                )

            deliberation_transcript.append({
                "adviser": a1,
                "role": COUNCIL_ROLES.get(a1, {}).get("title"),
                "department": COUNCIL_ROLES.get(a1, {}).get("department"),
                "stage": "challenge_round",
                "content": c1_text,
                "inference_engine": "offline_simulated" if c1_res.get("simulated") else "local_ollama",
                "timestamp": datetime.utcnow().isoformat()
            })

            counter_prompt = (
                f"You are the {a2}. {a1} just challenged your position on '{topic}' with: \"{c1_text[:200]}\".\n"
                f"Deliver a pragmatic compromise or counter-argument that unblocks execution."
            )
            c2_res = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": counter_prompt}],
                system_prompt=f"Act as {a2}. Department: {COUNCIL_ROLES.get(a2, {}).get('department')}.",
                format_json=False
            )
            c2_text = c2_res.get("content", "")
            if not c2_text or c2_res.get("simulated"):
                c2_text = (
                    f"COUNTER-PROPOSAL FROM {a2.upper()}: We acknowledge the constraint on '{topic}'. "
                    f"We propose a staged rollout: execute a 14-day validation pilot first, "
                    f"measuring concrete milestone progress before committing additional founder time or budget."
                )

            deliberation_transcript.append({
                "adviser": a2,
                "role": COUNCIL_ROLES.get(a2, {}).get("title"),
                "department": COUNCIL_ROLES.get(a2, {}).get("department"),
                "stage": "challenge_round",
                "content": c2_text,
                "inference_engine": "offline_simulated" if c2_res.get("simulated") else "local_ollama",
                "timestamp": datetime.utcnow().isoformat()
            })

        # Stage D: Synthesis by Chief of Staff
        synthesis_prompt = (
            f"You are the Chief of Staff synthesizing the executive council deliberation on '{topic}'.\n"
            f"Financial Baseline: MRR=${financials['mrr']}, Net Burn=${financials['net_burn']}, Runway={financials['runway_months']} mo.\n"
            f"Adviser Positions:\n" + "\n".join([f"- {k}: {v[:150]}" for k, v in adviser_positions.items()]) + "\n"
            f"Synthesize the consensus path, primary trade-off, and actionable decision recommendation for the founder."
        )
        synthesis_res = await ollama_gateway.chat_complete(
            messages=[{"role": "user", "content": synthesis_prompt}],
            system_prompt="Act as Chief of Staff & Executive Synthesizer.",
            format_json=False
        )
        synthesis_text = synthesis_res.get("content", "")
        if not synthesis_text or synthesis_res.get("simulated"):
            synthesis_text = (
                f"**Chief of Staff Executive Synthesis for '{topic}':**\n\n"
                f"The council concurs that '{topic}' represents an immediate operational priority. "
                f"While growth opportunities exist, working capital discipline is required with "
                f"${financials['overdue_receivables']:,.2f} in outstanding receivables and ${financials['net_burn']:,.2f} net monthly burn.\n\n"
                f"**Consensus Path:** Execute a gated phased rollout with clear founder sign-off before committing capital."
            )

        # Grounded areas of agreement and disagreement derived from the topic
        is_invoice_topic = "invoice" in topic.lower() or "receivable" in topic.lower() or "overdue" in topic.lower()
        is_pricing_topic = "price" in topic.lower() or "pricing" in topic.lower() or "tier" in topic.lower()
        
        if is_invoice_topic:
            areas_agreement = [
                f"Prioritize recovering ${financials['overdue_receivables']:,.2f} in overdue receivables without burning client goodwill",
                "Require founder approval before dispatching formal collection notices or service pause warnings",
                "Automate friendly 3-day reminder sequence for invoices past 14 days"
            ]
            areas_disagreement = [
                "Finance favors immediate late-fee assessment; Customer Success warns of client churn"
            ]
            recommended_actions = [
                {"title": f"Review & Dispatch Overdue Invoices (${financials['overdue_receivables']:,.2f})", "owner": "Finance Adviser", "priority": "critical"},
                {"title": "Implement Staged Reminder Email Automation", "owner": "Operations Adviser", "priority": "high"},
                {"title": "Schedule 1-on-1 Billing Alignment with Flagged Accounts", "owner": "Customer Success Adviser", "priority": "medium"}
            ]
        elif is_pricing_topic:
            areas_agreement = [
                f"Standardize billing tiers to eliminate bespoke margin leakage across {financials['active_paying_customers']} clients",
                "Incentivize annual upfront prepayments to extend cash runway",
                "Grandfather existing active clients for 90 days before transitioning rates"
            ]
            areas_disagreement = [
                "Finance requires strict upfront annual terms; Marketing advocates for low-friction monthly trials"
            ]
            recommended_actions = [
                {"title": "Audit Contract Inconsistencies Across Accounts", "owner": "Operations Adviser", "priority": "critical"},
                {"title": "Publish Standardized Self-Serve Pricing Matrix", "owner": "Marketing Adviser", "priority": "high"},
                {"title": "Draft Annual Prepay Upgrade Campaign (20% Discount)", "owner": "Finance Adviser", "priority": "medium"}
            ]
        else:
            areas_agreement = [
                f"Maintain strict runway preservation above 6 months (Current: {financials['runway_months']} mo)",
                f"Align operational initiatives directly with core focus: '{topic}'",
                "Establish quantifiable 30-day review milestones with founder checkpoint"
            ]
            areas_disagreement = [
                f"Debate regarding rapid execution velocity vs risk containment for '{topic}'"
            ]
            recommended_actions = [
                {"title": f"Execute Phase 1 Milestones for '{topic}'", "owner": "Operations Adviser", "priority": "high"},
                {"title": "Audit Capital Allocation & Burn Impact", "owner": "Finance Adviser", "priority": "medium"},
                {"title": "Review 30-Day Measurable Progress against Target", "owner": "Chief of Staff", "priority": "medium"}
            ]

        meeting.deliberation_transcript = deliberation_transcript
        meeting.synthesis_summary = synthesis_text
        meeting.areas_of_agreement = areas_agreement
        meeting.areas_of_disagreement = areas_disagreement
        meeting.recommended_actions = recommended_actions
        meeting.stage = "completed"
        meeting.completed_at = datetime.utcnow()
        
        db.commit()
        db.refresh(meeting)
        return meeting

    def approve_meeting_decision(
        self,
        db: Session,
        business_id: str,
        meeting_id: str,
        decision_notes: Optional[str] = None
    ) -> Decision:
        """Founder approves the board recommendation. Strictly validated against tenant boundary."""
        meeting = db.query(CouncilMeeting).filter(CouncilMeeting.id == meeting_id).first()
        if not meeting:
            raise ValueError(f"Meeting '{meeting_id}' not found")
        if meeting.business_id != business_id:
            raise ValueError(f"Unauthorized: Meeting belongs to business '{meeting.business_id}', not '{business_id}'")

        meeting.founder_decision = "approved"
        meeting.founder_notes = decision_notes or "Approved plan as synthesized by Chief of Staff."

        financials = self._calculate_deterministic_financials(db, business_id)
        
        # Grounded outcome targets derived from meeting context
        is_invoice = "invoice" in meeting.topic.lower() or "receivable" in meeting.topic.lower()
        if is_invoice:
            expected_outcomes = [
                {"metric": "Overdue Receivables Collected", "target_value": float(financials["overdue_receivables"]), "timeframe_days": 30, "unit": "$"},
                {"metric": "Runway Extension", "target_value": 1.5, "timeframe_days": 60, "unit": "months"}
            ]
        else:
            expected_outcomes = [
                {"metric": "Action Item Completion", "target_value": 100.0, "timeframe_days": 30, "unit": "%"},
                {"metric": "Runway Health Preservation", "target_value": float(financials["runway_months"]), "timeframe_days": 60, "unit": "months"}
            ]

        decision = Decision(
            business_id=business_id,
            title=f"Board Decision: {meeting.title}",
            business_context=meeting.topic,
            advisers_consulted=meeting.advisers_present,
            recommendations_summary=meeting.synthesis_summary,
            assumptions=[
                {"id": "a1", "text": f"Execution of '{meeting.title}' remains within existing capacity", "status": "tracking"},
                {"id": "a2", "text": "Net monthly burn rate does not exceed budget ceiling", "status": "tracking"}
            ],
            dissenting_opinions=meeting.areas_of_disagreement,
            founder_decision="approved",
            founder_notes=meeting.founder_notes,
            expected_outcomes=expected_outcomes,
            outcome_review_date=datetime.utcnow() + timedelta(days=30)
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)

        # Convert recommended actions into real Tasks in Task queue
        created_task_ids = []
        for action in (meeting.recommended_actions or []):
            task = Task(
                business_id=business_id,
                decision_id=decision.id,
                title=action.get("title", "Executive Action Item"),
                responsible_agent=action.get("owner", "Operations Adviser"),
                priority=action.get("priority", "medium"),
                status="todo",
                deadline=datetime.utcnow() + timedelta(days=7)
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            created_task_ids.append(task.id)

        meeting.created_tasks = created_task_ids
        db.commit()
        return decision

council_engine = CouncilEngine()
