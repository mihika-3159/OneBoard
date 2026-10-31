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
        self, db: Session, business_id: str, title: str, meeting_type: str,
        topic: str, selected_advisers: Optional[List[str]] = None
    ) -> CouncilMeeting:
        """Use real tenant facts and visible adviser positions, never scripted debate."""
        if not topic or not topic.strip():
            raise ValueError("A meeting topic is required")
        if selected_advisers is None:
            selected_advisers = [
                "Chief of Staff", "Strategy Adviser", "Finance Adviser",
                "Marketing Adviser", "Operations Adviser"
            ]
        if (not selected_advisers or len(set(selected_advisers)) != len(selected_advisers)
                or any(name not in COUNCIL_ROLES for name in selected_advisers)):
            raise ValueError("Select distinct, recognized advisers")

        topic = topic.strip()
        financials = self._calculate_deterministic_financials(db, business_id)
        facts = (
            f"MRR={financials['mrr']}; monthly expenses={financials['monthly_expenses']}; "
            f"net burn={financials['net_burn']}; cash={financials['cash_balance']}; "
            f"runway={financials['runway_months'] if financials['runway_months'] is not None else financials['runway_status']}; "
            f"overdue receivables={financials['overdue_receivables']}; "
            f"data status={financials['financial_data_status']}."
        )
        meeting = CouncilMeeting(
            business_id=business_id, title=title, meeting_type=meeting_type,
            topic=topic, advisers_present=selected_advisers, stage="deliberating"
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        transcript = []
        positions = {}
        for name in selected_advisers:
            role = COUNCIL_ROLES[name]
            res = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": (
                    f"Topic: {topic}\nRecorded financial facts: {facts}\n"
                    f"Focus: {role['focus']}.\n"
                    "Provide a position, assumptions, risks and a measurable next step. "
                    "Do not invent customers, contracts, sources or numerical targets."
                )}],
                system_prompt=f"Act as {name}; use only supplied facts."
            )
            simulated = bool(res.get("simulated", False))
            # The gateway's offline fallback contains canned Northstar Studio
            # claims; never attribute that text to a real business or adviser.
            content = (
                f"No LLM analysis available. For '{topic}', review {role['focus']}. "
                f"Available financial facts: {facts}"
                if simulated else (res.get("content") or "No adviser response returned.")
            )
            positions[name] = content
            transcript.append({
                "adviser": name, "role": role["title"],
                "department": role["department"], "stage": "independent_analysis",
                "content": content, "simulated": simulated,
                "source": "deterministic_fallback" if simulated else "local_ollama_unverified",
                "timestamp": datetime.utcnow().isoformat()
            })

        disagreements = []
        challengers = [n for n in selected_advisers if n != "Chief of Staff"]
        if len(challengers) >= 2:
            first, second = challengers[:2]
            challenge = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": (
                    f"Topic: {topic}\nRecorded facts: {facts}\n"
                    f"{first} position: {positions[first][:1500]}\n"
                    f"{second} position: {positions[second][:1500]}\n"
                    "Identify a specific tension only if the positions support one; "
                    "otherwise say there is no demonstrated disagreement. "
                    "Do not invent a quote, source or target."
                )}],
                system_prompt="Compare actual positions; do not impersonate advisers."
            )
            simulated = bool(challenge.get("simulated", False))
            comparison = (
                f"Offline comparison: positions from {first} and {second} are recorded above. "
                "No independent challenge was generated."
                if simulated else (challenge.get("content") or "No challenge returned.")
            )
            transcript.append({
                "adviser": "Council facilitator", "role": "Position comparison",
                "department": "Executive Office", "stage": "challenge_round",
                "content": comparison, "simulated": simulated,
                "source": "deterministic_fallback" if simulated else "local_ollama_unverified",
                "compared_advisers": [first, second],
                "timestamp": datetime.utcnow().isoformat()
            })
            if not simulated and comparison.strip():
                disagreements.append(
                    f"Unverified comparison ({first} / {second}): {comparison[:800]}"
                )

        topic_short = " ".join(topic.split())[:110]
        owner = next((n for n in selected_advisers if n != "Chief of Staff"), selected_advisers[0])
        actions = [{
            "title": f"Define evidence and next steps for: {topic_short}",
            "owner": owner, "priority": "medium", "source": "meeting_topic"
        }]
        if financials["financial_data_status"] == "recorded":
            if financials["runway_status"] in ("critical", "critical_depleted"):
                actions.append({
                    "title": f"Review cash runway and net burn ({financials['net_burn']} per month)",
                    "owner": "Finance Adviser" if "Finance Adviser" in selected_advisers else owner,
                    "priority": "high", "source": "tenant_financial_snapshot"
                })
            if financials["overdue_receivables"] > 0:
                actions.append({
                    "title": f"Review overdue receivables ({financials['overdue_receivables']})",
                    "owner": "Finance Adviser" if "Finance Adviser" in selected_advisers else owner,
                    "priority": "medium", "source": "tenant_financial_snapshot"
                })

        visible_positions = "\n".join(
            f"{name}: {positions[name][:1500]}" for name in selected_advisers
        )
        synthesis = await ollama_gateway.chat_complete(
            messages=[{"role": "user", "content": (
                f"Topic: {topic}\nRecorded facts: {facts}\n"
                f"Actual adviser positions:\n{visible_positions}\n"
                f"Challenge: {transcript[-1]['content'] if len(challengers) >= 2 else 'Not performed'}\n"
                "Summarize only supported advice and trade-offs. "
                "Do not invent evidence, numeric targets or consensus."
            )}],
            system_prompt="Synthesize the visible transcript, labelling assumptions."
        )
        if synthesis.get("simulated", False):
            summary = (
                f"Offline council summary (no LLM inference). Topic: {topic}. "
                f"Recorded financial facts: {facts} "
                f"Suggested review tasks: {'; '.join(a['title'] for a in actions)}. "
                "No independent agreement or disagreement established."
            )
        else:
            summary = (
                "AI-generated synthesis (unverified; review adviser positions): "
                + (synthesis.get("content") or "No synthesis returned.")
            )

        meeting.deliberation_transcript = transcript
        meeting.synthesis_summary = summary
        meeting.areas_of_agreement = []
        meeting.areas_of_disagreement = disagreements
        meeting.recommended_actions = actions
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
