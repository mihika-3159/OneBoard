from apps.api.services.inference_budget import inference_tenant
from apps.api.services.untrusted_content import DATA_BOUNDARY, quoted_data
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import asyncio
from apps.api.services.council_evidence import evidence_inventory, adviser_record, synthesis_record
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

def specialist_challenge_pairs(selected_advisers: List[str]) -> List[tuple[str, str]]:
    """Compare every selected specialist; nine known roles bound the chain."""
    specialists = [name for name in selected_advisers if name != "Chief of Staff"]
    return list(zip(specialists, specialists[1:]))


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
            "financial_data_issues": snapshot["financial_data_issues"],
            "financial_data_verified": snapshot["financial_data_verified"],
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
        if len(topic) > 8000 or not title.strip() or len(title) > 255:
            raise ValueError("Invalid meeting title or topic length")
        inventory = evidence_inventory(db, business_id)
        # Match the conservative byte-based inference context budget. Include
        # complete records, not a truncated JSON object.
        bounded = {}
        for key, value in inventory.items():
            trial = {**bounded, key: value}
            if len(json.dumps(trial, ensure_ascii=True)) <= 2200:
                bounded = trial
        # Preserve knowledge of unresolved conflicts even if the record itself
        # cannot fit into a model prompt.
        conflict_present = any(v["source"] == "unresolved_conflict" for v in inventory.values())
        inventory = bounded
        if conflict_present and not any(v["source"] == "unresolved_conflict" for v in inventory.values()):
            facts_conflict = True
        else:
            facts_conflict = False
        evidence_text = quoted_data("tenant_evidence_inventory", json.dumps(inventory), 3000)
        if facts_conflict:
            evidence_text += " Unresolved conflicting records exist; do not infer consensus."
        financials = self._calculate_deterministic_financials(db, business_id)
        facts = (
            f"MRR={financials['mrr']}; monthly expenses={financials['monthly_expenses']}; "
            f"net burn={financials['net_burn']}; cash={financials['cash_balance']}; "
            f"runway={financials['runway_months'] if financials['runway_months'] is not None else financials['runway_status']}; "
            f"overdue receivables={financials['overdue_receivables']}; "
            f"data status={financials['financial_data_status']}; "
            f"independently verified={financials['financial_data_verified']}; "
            f"data quality warnings={len(financials['financial_data_issues'])}."
        )
        if financials["financial_data_status"] == "needs_review":
            facts = (
                "WARNING: FINANCIAL INPUTS FAILED VALIDATION. The numbers "
                "below are partial/unreconciled and MUST NOT support numeric "
                "recommendations or a claim of financial health. "
                "Request correction of the underlying records. " + facts
            )
        meeting = CouncilMeeting(
            business_id=business_id, title=title, meeting_type=meeting_type,
            topic=topic, advisers_present=selected_advisers, stage="deliberating",
            checkpoint_at=datetime.utcnow(), retrieved_evidence_ids=[]
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        transcript = []
        try:
            return await asyncio.wait_for(self._deliberate(db, meeting, business_id, topic, selected_advisers,
                financials, facts, inventory, evidence_text, transcript, conflict_present), timeout=600)
        except BaseException:
            db.rollback()
            meeting.stage = "interrupted"
            meeting.checkpoint_at = datetime.utcnow()
            meeting.synthesis_summary = "Deliberation interrupted; no approval or actions are available."
            meeting.recommended_actions = []
            db.commit()
            raise

    async def _deliberate(self, db, meeting, business_id, topic, selected_advisers, financials, facts, inventory, evidence_text, transcript, conflict_present):
        def checkpoint(stage):
            meeting.deliberation_transcript = list(transcript)
            meeting.stage = stage
            meeting.checkpoint_at = datetime.utcnow()
            db.commit()

        positions = {}
        for name in selected_advisers:
            role = COUNCIL_ROLES[name]
            with inference_tenant(business_id):
                res = await ollama_gateway.chat_complete(
                    messages=[{"role": "user", "content": (
                        f"Topic: {topic}\nRecorded financial facts: {facts}\n"
                        f"Focus: {role['focus']}.\n"
                        f"{evidence_text}\n"
                        'Return JSON {"position":"at most 100 words", "citations":[{"id":"inventory id","quote":"exact text"}]}. '
                        "Cite only supplied records, use [] when unsupported, label assumptions. Do not invent numeric targets."
                    )}],
                    system_prompt=f"Act as {name}; use only supplied facts. "+DATA_BOUNDARY,
                    format_json=True
                )
            simulated = bool(res.get("simulated", False))
            # The gateway's offline fallback contains canned Northstar Studio
            # claims; never attribute that text to a real business or adviser.
            content = (
                f"No LLM analysis available. For '{topic}', review {role['focus']}. "
                f"Available financial facts: {facts}"
                if simulated else (res.get("content") or "No adviser response returned.")
            )
            verified = adviser_record(res, inventory)
            if verified:
                content = verified["position"]
            positions[name] = content
            transcript.append({
                "argument_id": f"argument-{len(transcript)+1}",
                "citations": verified["citations"] if verified else [],
                "evidence_status": verified["evidence_status"] if verified else "unsupported",
                "adviser": name, "role": role["title"],
                "department": role["department"], "stage": "independent_analysis",
                "content": content, "simulated": simulated,
                "output_limit_reached": bool(res.get("output_limit_reached")),
                "source": "deterministic_fallback" if simulated else "local_ollama_unverified",
                "timestamp": datetime.utcnow().isoformat()
            })
            checkpoint("independent_analysis")

        disagreements = []
        challengers = [n for n in selected_advisers if n != "Chief of Staff"]
        # Compare adjacent specialist positions so no selected adviser is silently
        # excluded from the challenge round. Adviser validation bounds calls.
        challenge_pairs = specialist_challenge_pairs(selected_advisers)
        challenge_summaries = []
        for first, second in challenge_pairs:
            with inference_tenant(business_id):
                challenge = await ollama_gateway.chat_complete(
                    messages=[{"role": "user", "content": (
                        f"Topic: {topic}\\nRecorded facts: {facts}\\n"
                        f"{first} position: {quoted_data('adviser_position',positions[first],1500)}\\n"
                        f"{second} position: {quoted_data('adviser_position',positions[second],1500)}\\n"
                        "In at most 70 words, identify a specific tension only if the positions support one; "
                        "otherwise say there is no demonstrated disagreement. "
                        "Do not invent a quote, source or target."
                    )}],
                    system_prompt="Compare actual positions; do not impersonate advisers. "+DATA_BOUNDARY
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
                "output_limit_reached": bool(challenge.get("output_limit_reached")),
                "source": "deterministic_fallback" if simulated else "local_ollama_unverified",
                "compared_advisers": [first, second],
                "timestamp": datetime.utcnow().isoformat()
            })
            checkpoint("challenge_round")
            challenge_summaries.append(f"{first} / {second}: {comparison[:800]}")
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
            f"{name}: {quoted_data('adviser_position',positions[name],1500)}" for name in selected_advisers
        )
        checkpoint("synthesis")
        with inference_tenant(business_id):
            synthesis = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": (
                    f"Topic: {topic}\nRecorded facts: {facts}\n"
                    f"Actual adviser positions:\n{visible_positions}\n"
                    f"Challenges: {'; '.join(challenge_summaries) if challenge_summaries else 'Not performed'}\n"
                    f"{evidence_text}\nArguments with stable IDs: {quoted_data('argument_inventory',json.dumps([{'id':a.get('argument_id'),'content':a['content'],'citations':a.get('citations',[])} for a in transcript if a.get('argument_id')]),12000)}\n"
                    'Return JSON {"arguments":[{"id":"argument ID","quote":"exact adviser words"}],"citations":[{"id":"record ID","quote":"exact record words"}]}. '
                    "Select only linked evidence; no invented claims, numeric targets or consensus."
                )}],
                system_prompt="Synthesize the visible transcript, labelling assumptions. "+DATA_BOUNDARY,
                format_json=True
            )
        structured = synthesis_record(synthesis, transcript, inventory)
        if conflict_present:
            structured["disposition"] = "resolve_conflict"
            structured["uncertainty"] = "high"
        meeting.structured_synthesis = structured
        meeting.retrieved_evidence_ids = [item["id"] for item in structured["citations"]]
        if synthesis.get("simulated", False):
            summary = (
                f"Offline council summary (no LLM inference). Topic: {topic}. "
                f"Recorded financial facts: {facts} "
                f"Suggested review tasks: {'; '.join(a['title'] for a in actions)}. "
                "No independent agreement or disagreement established."
            )
        else:
            summary = ("AI-generated synthesis (unverified; review adviser positions): "
                       + ("; ".join(a["adviser"] + ": " + a["quote"] for a in structured["arguments"])
                          if structured["arguments"] else "No evidence-linked synthesis accepted; collect evidence before acting."))

        meeting.deliberation_transcript = transcript
        meeting.synthesis_summary = summary
        meeting.areas_of_agreement = []
        meeting.areas_of_disagreement = disagreements
        if conflict_present:
            actions = [{"title": "Resolve conflicting tenant evidence before making a recommendation",
                        "owner": owner, "priority": "high", "source": "tenant_evidence_conflict"}]
        meeting.recommended_actions = actions
        incomplete = (not synthesis.get("simulated") and bool(synthesis.get("output_limit_reached"))) or any(a["output_limit_reached"] for a in transcript)
        mixed = any(a["simulated"] for a in transcript) and any(not a["simulated"] for a in transcript)
        meeting.stage = "partial" if incomplete or mixed or (synthesis.get("simulated") and any(not a["simulated"] for a in transcript)) else "completed"
        if meeting.stage == "partial":
            meeting.recommended_actions = []
        meeting.checkpoint_at = datetime.utcnow()
        meeting.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(meeting)
        return meeting

    def reconcile_interrupted(self, db, business_id):
        cutoff = datetime.utcnow() - timedelta(minutes=12)
        count = db.query(CouncilMeeting).filter(CouncilMeeting.business_id == business_id,
            CouncilMeeting.stage.in_(["deliberating", "independent_analysis", "challenge_round", "synthesis"]),
            ((CouncilMeeting.checkpoint_at < cutoff) | ((CouncilMeeting.checkpoint_at.is_(None)) & (CouncilMeeting.created_at < cutoff))))\
            .update({"stage": "interrupted", "recommended_actions": [], "synthesis_summary": "Deliberation interrupted; no approval available."}, synchronize_session=False)
        db.commit()
        return count

    def approve_meeting_decision(
        self,
        db: Session,
        business_id: str,
        meeting_id: str,
        decision_notes: Optional[str] = None
    ) -> Decision:
        """Founder approves the board recommendation. Creates immutable Decision record and executable Tasks."""
        meeting = db.query(CouncilMeeting).filter(
            CouncilMeeting.id == meeting_id,
            CouncilMeeting.business_id == business_id
        ).with_for_update().first()
        if not meeting:
            raise ValueError(f"Meeting {meeting_id} not found")

        if meeting.stage != "completed" or meeting.founder_decision is not None:
            raise ValueError("Meeting is not eligible for approval")

        meeting.founder_decision = "approved"
        meeting.founder_notes = decision_notes or "Approved plan as synthesized by Chief of Staff."

        # Create immutable Decision
        decision = Decision(
            business_id=business_id,
            title=f"Board Decision: {meeting.title}",
            business_context=meeting.topic,
            advisers_consulted=meeting.advisers_present,
            recommendations_summary=meeting.synthesis_summary,
            supporting_evidence_ids=meeting.retrieved_evidence_ids or [],
            assumptions=[],  # Do not invent financial or acquisition predictions.
            dissenting_opinions=meeting.areas_of_disagreement,
            founder_decision="approved",
            founder_notes=meeting.founder_notes,
            expected_outcomes=[],  # No unsupported monetary outcome targets.
            planned_actions=meeting.recommended_actions or [],
            outcome_review_date=datetime.utcnow() + timedelta(days=30)
        )
        # A single transaction avoids partial approvals and orphaned tasks.
        try:
            db.add(decision)
            db.flush()
            created_task_ids = []
            for action in (meeting.recommended_actions or []):
                task = Task(
                    business_id=business_id,
                    decision_id=decision.id,
                    title=action.get("title", "Review council recommendation"),
                    responsible_agent=action.get("owner", "Chief of Staff"),
                    priority=action.get("priority", "medium"),
                    status="todo",
                    deadline=datetime.utcnow() + timedelta(days=7)
                )
                db.add(task)
                db.flush()
                created_task_ids.append(task.id)
            meeting.created_tasks = created_task_ids
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(decision)
        return decision

council_engine = CouncilEngine()
