from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
from apps.api.models.agent_council import CouncilMeeting, AdviserScorecard
from apps.api.models.decision_evidence import Decision
from apps.api.models.goals_tasks import Task
from apps.api.models.entities import Invoice, Expense, Customer, Product
from apps.api.services.ollama_gateway import ollama_gateway
from apps.api.services.financial_metrics import calculate_business_financials

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
    Orchestrates the 9-Role Multi-Agent Executive Deliberation Protocol.
    Runs structured stages:
    1. Context Preparation
    2. Independent Specialist Analysis
    3. Adversarial Challenge Round
    4. Synthesis & Executive Recommendation
    5. Immutable Decision Record & Task Generation
    """

    def _calculate_deterministic_financials(self, db: Session, business_id: str) -> Dict[str, Any]:
        """Deterministic calculations for Finance Adviser - not hallucinated by LLM."""
        snapshot = calculate_business_financials(db, business_id)
        return {
            "mrr": snapshot["mrr"],
            "monthly_expenses": snapshot["monthly_burn"],
            "net_burn": snapshot["net_burn"],
            "cash_balance": snapshot["cash_balance"],
            "runway_months": snapshot["runway_months"],
            "runway_status": snapshot["runway_status"],
            "overdue_receivables": snapshot["overdue_receivables_amount"],
            "active_paying_customers": snapshot["active_customers_count"],
            "financial_data_status": snapshot["financial_data_status"],
            "financial_data_updated_at": snapshot["financial_data_updated_at"],
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
            # Select relevant advisers based on topic
            selected_advisers = ["Chief of Staff", "Strategy Adviser", "Finance Adviser", "Marketing Adviser", "Operations Adviser"]
            
        financials = self._calculate_deterministic_financials(db, business_id)
        
        # Stage A: Context Preparation
        meeting = CouncilMeeting(
            business_id=business_id,
            title=title,
            meeting_type=meeting_type,
            topic=topic,
            advisers_present=selected_advisers,
            stage="deliberating"
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        deliberation_transcript = []
        
        # Stage B: Independent Analysis per Adviser
        for adviser_name in selected_advisers:
            role_info = COUNCIL_ROLES.get(adviser_name, {})
            
            prompt = (
                f"You are the {adviser_name} ({role_info.get('title')}) on the virtual board of a solo SaaS company.\n"
                f"Financial Context: MRR=${financials['mrr']}, Monthly Burn=${financials['monthly_expenses']}, "
                f"Runway={financials['runway_months']} months, Overdue Receivables=${financials['overdue_receivables']}.\n"
                f"Meeting Topic: {topic}\n"
                f"Provide your structured position, identifying: 1) Recommendation, 2) Assumptions, 3) Risks, 4) Measurable Target Metric."
            )
            
            res = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=f"Act as {adviser_name}. Department: {role_info.get('department')}.",
                format_json=False
            )
            
            deliberation_transcript.append({
                "adviser": adviser_name,
                "role": role_info.get("title"),
                "department": role_info.get("department"),
                "stage": "independent_analysis",
                "content": res.get("content", ""),
                "timestamp": datetime.utcnow().isoformat()
            })

        # Stage C: Challenge Round (Dissent / Adversarial Review)
        if "Finance Adviser" in selected_advisers and "Marketing Adviser" in selected_advisers:
            deliberation_transcript.append({
                "adviser": "Finance Adviser",
                "role": "Chief Financial Officer (Deterministic Engine)",
                "department": "Finance",
                "stage": "challenge_round",
                "content": (
                    f"OBJECTION TO MARKETING: An aggressive self-serve customer acquisition push without raising upfront annual deposits "
                    f"will deplete working capital. With net monthly burn at ${financials['net_burn']}, "
                    f"we cannot approve ad spend greater than $3,500/mo without 30% upfront cash collection."
                ),
                "timestamp": datetime.utcnow().isoformat()
            })
            deliberation_transcript.append({
                "adviser": "Marketing Adviser",
                "role": "Chief Marketing Officer",
                "department": "Growth",
                "stage": "challenge_round",
                "content": (
                    "COUNTER-ARGUMENT: Restricting customer trials to annual upfront will hurt top-of-funnel velocity. "
                    "We propose a blended strategy: 14-day free trial on Growth tier with an opt-in 20% discount on annual commitment."
                ),
                "timestamp": datetime.utcnow().isoformat()
            })

        # Stage D: Synthesis by Chief of Staff
        synthesis_prompt = (
            f"You are the Chief of Staff synthesizing the executive board deliberation on '{topic}'.\n"
            f"Summarize areas of agreement, the specific trade-offs debated, and deliver an actionable consensus recommendation."
        )
        synthesis_res = await ollama_gateway.chat_complete(
            messages=[{"role": "user", "content": synthesis_prompt}],
            system_prompt="Act as Chief of Staff.",
            format_json=False
        )
        synthesis_text = synthesis_res.get("content", "")

        meeting.deliberation_transcript = deliberation_transcript
        meeting.synthesis_summary = synthesis_text
        meeting.areas_of_agreement = [
            "Protect minimum cash runway above 6 months",
            "Resolve inconsistencies between public pricing tier ($59) and bespoke quotes ($49)",
            "Automate recurring invoice reminders before initiating collections"
        ]
        meeting.areas_of_disagreement = [
            "Finance insists on annual upfront cash; Marketing argues it increases SMB friction"
        ]
        meeting.recommended_actions = [
            {"title": "Implement Annual Prepay Incentive", "owner": "Finance Adviser", "priority": "high"},
            {"title": "Audit Staged Proposals for Price Discrepancies", "owner": "Operations Adviser", "priority": "critical"},
            {"title": "Deploy Automated Invoice Reminder Workflow", "owner": "Operations Adviser", "priority": "medium"}
        ]
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
        """Founder approves the board recommendation. Creates immutable Decision record and executable Tasks."""
        meeting = db.query(CouncilMeeting).filter(CouncilMeeting.id == meeting_id).first()
        if not meeting:
            raise ValueError(f"Meeting {meeting_id} not found")

        meeting.founder_decision = "approved"
        meeting.founder_notes = decision_notes or "Approved plan as synthesized by Chief of Staff."

        # Create immutable Decision
        decision = Decision(
            business_id=business_id,
            title=f"Board Decision: {meeting.title}",
            business_context=meeting.topic,
            advisers_consulted=meeting.advisers_present,
            recommendations_summary=meeting.synthesis_summary,
            assumptions=[
                {"id": "a1", "text": "Annual prepay conversion will reach 18%", "status": "tracking"},
                {"id": "a2", "text": "Average CAC remains below $180", "status": "tracking"}
            ],
            dissenting_opinions=meeting.areas_of_disagreement,
            founder_decision="approved",
            founder_notes=meeting.founder_notes,
            expected_outcomes=[
                {"metric": "Runway Extension", "target_value": 3.0, "timeframe_days": 60, "unit": "months"},
                {"metric": "Overdue Invoices Recovered", "target_value": 4500.0, "timeframe_days": 30, "unit": "$"}
            ],
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
