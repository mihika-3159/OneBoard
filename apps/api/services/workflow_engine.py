from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, or_
import re
from datetime import datetime, timedelta
import json
import logging
import hashlib
from uuid import uuid4
from apps.api.services.workflow_conditions import condition_result, should_skip, resolve_data, validate_conditions
from apps.api.services.workflow_effects import stage_effect, preview_effect, canonical_digest
from apps.api.services.workflow_events import revision_number, fingerprint
from decimal import Decimal
from apps.api.services.financial_metrics import _money
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest, AuditLog
from apps.api.models.entities import Invoice, Customer, Commitment
from apps.api.models.goals_tasks import Task
from apps.api.models.operations import SideEffectOutbox

logger = logging.getLogger(__name__)

class ToolRegistry:
    """Explicitly registered safe business tools. Arbitrary execution strictly prohibited."""
    
    @staticmethod
    def read_overdue_invoices(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == business_id,
            or_(Invoice.status == "overdue", (Invoice.status == "sent") & (Invoice.due_date < datetime.utcnow()))
        ).all()
        return {
            "count": len(invoices),
            "invoices": [
                {"id": i.id, "number": i.invoice_number, "customer": i.customer_name, "amount": i.amount, "due_date": str(i.due_date)}
                for i in invoices
            ]
        }

    @staticmethod
    def calculate_invoice_totals(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == business_id,
            or_(Invoice.status == "overdue", (Invoice.status == "sent") & (Invoice.due_date < datetime.utcnow()))
        ).all()
        # A financial workflow must not bypass the dashboard's data
        # quality checks: a negative, NaN, or missing amount must fail the
        # workflow visibly, never become an actionable collection total.
        total = sum(
            (_money(invoice.amount, "invoice.amount") for invoice in invoices),
            Decimal("0.00"),
        )
        return {
            "total_overdue": float(total),
            "invoice_count": len(invoices),
            "verified": False,
            "source": "tenant_overdue_invoice_records_unreconciled",
        }

    @staticmethod
    def draft_invoice_reminder_emails(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == business_id,
            or_(Invoice.status == "overdue", (Invoice.status == "sent") & (Invoice.due_date < datetime.utcnow()))
        ).all()
        drafts = []
        for inv in invoices:
            drafts.append({
                "invoice_id": inv.id,
                "recipient": inv.customer_name,
                "subject": f"Reminder: Invoice {inv.invoice_number} is pending",
                "body": f"Dear {inv.customer_name},\nThis is a friendly note that invoice {inv.invoice_number} for ${inv.amount} is past due. Please let us know if you need any assistance."
            })
        return {"drafts_created": len(drafts), "drafts": drafts}

    @staticmethod
    def send_email_action(db: Session, business_id: str, recipient: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        # The demo adapter never sends an email. Do not claim delivery.
        return {
            "delivered": False,
            "status": "simulated",
            "channel": "demo_email",
            "recipient": recipient,
            "subject": subject,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def check_commitment_deadlines(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        commitments = db.query(Commitment).filter(
            Commitment.business_id == business_id,
            Commitment.status == "pending"
        ).all()
        return {
            "pending_count": len(commitments),
            "commitments": [
                {"id": c.id, "title": c.title, "counterparty": c.counterparty, "deadline": str(c.deadline), "risk": c.risk_level}
                for c in commitments
            ]
        }

    @staticmethod
    def update_task_status(db: Session, business_id: str, task_id: str, status: str, **kwargs) -> Dict[str, Any]:
        task = db.query(Task).filter(Task.id == task_id, Task.business_id == business_id).first()
        if task:
            task.status = status
            db.flush()
            return {"success": True, "task_id": task_id, "new_status": status}
        return {"success": False, "error": "Task not found"}


class WorkflowEngine:
    """Tenant-scoped workflow runner with deterministic DAG ordering and resumable approvals."""

    MAX_NODES = 100
    MAX_EDGES = 300

    @staticmethod
    def _definition_digest(wf: WorkflowDefinition) -> str:
        """Pin the full executable DAG, not only its node IDs, at approval time."""
        canonical = json.dumps(
            {"nodes": wf.nodes or [], "edges": wf.edges or []},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _ordered_nodes(self, definition: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return a stable topological order or fail before any step is executed."""
        import heapq

        if not isinstance(definition, dict):
            raise ValueError("Workflow definition must be an object")
        nodes = definition.get("nodes", [])
        edges = definition.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("Workflow nodes and edges must be lists")
        if not nodes:
            raise ValueError("Workflow must contain at least one node")
        if len(nodes) > self.MAX_NODES or len(edges) > self.MAX_EDGES:
            raise ValueError("Workflow exceeds node or edge limits")

        by_id = {}
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("Workflow node must be an object")
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id.strip():
                raise ValueError("Workflow node IDs must be nonempty strings")
            if len(node_id) > 100:
                raise ValueError("Workflow node ID exceeds 100 characters")
            if node_id != node_id.strip():
                raise ValueError("Workflow node IDs must not have surrounding whitespace")
            if node_id in by_id:
                raise ValueError("Duplicate workflow node ID")
            if not isinstance(node.get("data", {}), dict):
                raise ValueError("Workflow node data must be an object")
            by_id[node_id] = node

        indegree = {node_id: 0 for node_id in by_id}
        adjacency = {node_id: [] for node_id in by_id}
        seen_edges = set()
        for edge in edges:
            if not isinstance(edge, dict):
                raise ValueError("Workflow edge must be an object")
            source, target = edge.get("source"), edge.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                raise ValueError("Workflow edge endpoints must be strings")
            if source not in by_id or target not in by_id:
                raise ValueError("Dangling edge in workflow graph")
            if (source, target) in seen_edges:
                raise ValueError("Workflow contains a duplicate edge")
            seen_edges.add((source, target))
            adjacency[source].append(target)
            indegree[target] += 1

        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        order = []
        while ready:
            node_id = heapq.heappop(ready)
            order.append(node_id)
            for target in adjacency[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    heapq.heappush(ready, target)
        if len(order) != len(nodes):
            raise ValueError("Cycle detected in workflow graph")
        return [by_id[node_id] for node_id in order]

    @staticmethod
    def tool_policy(node_type, node_data):
        """Server-owned capabilities; labels and model-supplied risk cannot grant access."""
        connector = node_data.get("connector", "")
        operation = node_data.get("operation")
        if node_type in ("trigger", "approval", "condition"):
            return "control"
        if node_type == "data_fetch" and connector in ("demo_finance", "demo_commitments"):
            return "tenant_read"
        if node_type == "calculate" and connector in ("", "demo_finance"):
            return "tenant_read"
        if node_type == "action" and connector == "demo_email" and operation == "draft_invoice_reminders":
            return "local_draft"
        return "denied"

    @staticmethod
    def _action_digest(node):
        return hashlib.sha256(json.dumps(node,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()

    def validate_workflow(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        try:
            nodes = self._ordered_nodes(definition)
            validate_conditions(nodes, definition.get("edges", []))
            return {
                "is_valid": True,
                "node_count": len(nodes),
                "unsupported_tools": [n["id"] for n in nodes if self.tool_policy(n.get("type"),n.get("data") or {})=="denied"],
                "external_execution_authorized": False,
                "edge_count": len(definition.get("edges", [])),
            }
        except ValueError as exc:
            return {"is_valid": False, "error": str(exc)}

    @staticmethod
    def _record_draft_intent(db, run, node_id, node_type, node_data, result):
        if node_type == "action" and node_data.get("connector") == "demo_email" and node_data.get("operation") == "draft_invoice_reminders":
            stage_effect(db, run, node_id, "invoice_reminder_draft", result)

    def _execute_steps(
        self,
        db: Session,
        run: WorkflowRun,
        wf: WorkflowDefinition,
        ordered_nodes: List[Dict[str, Any]],
        start_index: int,
        step_results: Dict[str, Any],
        dry_run: bool = False,
    ) -> WorkflowRun:
        """Execute a continuation. Never infer verified success from mere completion."""
        token = (run.verification_details or {}).get("execution_token")
        run.current_step_id = None
        for node in ordered_nodes[start_index:]:
            # Row locks fence cancellation and recovery across workers. The
            # effect and its checkpoint are committed in the same transaction.
            db.expire_all()
            run = db.query(WorkflowRun).filter_by(id=run.id,business_id=run.business_id).with_for_update().populate_existing().one()
            if run.status != "running" or (run.verification_details or {}).get("execution_token") != token:
                db.rollback()
                return run
            wf=db.query(WorkflowDefinition).filter_by(id=run.workflow_id,business_id=run.business_id).with_for_update().populate_existing().one()
            details=run.verification_details or {}
            if not wf.is_active or not wf.is_valid or self._definition_digest(wf) != details.get("definition_digest") or revision_number(db,run.business_id,wf.id)!=details.get("definition_revision",0):
                run.status="paused"
                run.error_message="Workflow changed or deactivated; execution stopped"
                db.commit()
                return run
            node_id = node["id"]
            node_type = node.get("type")
            node_data = node.get("data") or {}
            label = node_data.get("label", node_id)

            if not dry_run and should_skip(node_id, wf.edges or [], step_results):
                step_results[node_id] = {"status":"skipped","reason":"inactive branch"}
                run.step_results = dict(step_results)
                db.commit()
                continue
            if dry_run:
                step_results[node_id] = {
                    "status": "simulated",
                    "label": label,
                    "would_request_approval": node_type == "approval" or node_data.get("risk") == "high",
                }
                continue

            if node_type == "approval" or node_data.get("risk") == "high":
                try:
                    if self.tool_policy(node_type,node_data)=="denied":
                        raise ValueError("Unsupported workflow tool")
                    resolved = resolve_data(node_data, node_id, wf.edges or [], step_results)
                    preview = preview_effect(db, run.business_id, node_type, resolved)
                    canonical_digest(preview)
                except (ValueError,TypeError) as exc:
                    step_results[node_id]={"status":"failed","error_type":type(exc).__name__}
                    run.status="failed";run.error_message="Cannot prepare approval for this step";run.completed_at=datetime.utcnow()
                    break
                payload = {"step_id":node_id,"node_data":node_data,"action_digest":self._action_digest(node),
                           "resolved_data":resolved,"effect_preview":preview,
                           "definition_digest":self._definition_digest(wf),"run_id":run.id}
                payload["payload_digest"] = canonical_digest(payload)
                request = ApprovalRequest(
                    business_id=run.business_id,
                    workflow_run_id=run.id,
                    action_type="workflow_step_approval",
                    risk_level="high",
                    title=f"Approval Required for '{wf.name}'",
                    description=f"Action checkpoint reached: '{label}'. External actions pending confirmation.",
                    payload=payload,
                )
                db.add(request)
                db.flush()
                step_results[node_id] = {
                    "status": "awaiting_founder_approval",
                    "request_id": request.id,
                    "payload_digest": payload["payload_digest"],
                    "timestamp": datetime.utcnow().isoformat(),
                }
                run.status = "awaiting_approval"
                run.current_step_id = node_id
                break

            try:
                resolved = resolve_data(node_data, node_id, wf.edges or [], step_results)
                # Force a real outer write transaction before a SQLite savepoint.
                if db.get_bind().dialect.name=="sqlite":
                    db.execute(text("UPDATE workflow_runs SET status=status WHERE id=:id AND business_id=:tenant"),
                               {"id":run.id,"tenant":run.business_id})
                with db.begin_nested():
                    result = (condition_result(resolved) if node_type == "condition" else
                              self._dispatch_node_tool(db, run.business_id, node_type, resolved))
                    if node_type=="trigger" and (run.verification_details or {}).get("event_payload") is not None:
                        result={**result,"event":run.verification_details["event_payload"]}
                    if isinstance(result, dict) and result.get("success") is False:
                        raise ValueError("Workflow tool reported failure")
                    self._record_draft_intent(db, run, node_id, node_type, resolved, result)
                    canonical_digest(result)
                    db.flush()
            except Exception as exc:
                logger.warning("Workflow run %s failed at step %s: %s", run.id, node_id, exc)
                step_results[node_id] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                run.status = "failed"
                run.error_message = f"Step '{node_id}' failed; inspect server logs"
                run.completed_at = datetime.utcnow()
                break

            step_results[node_id] = {
                "status": "success",
                "label": label,
                "result": result,
                "timestamp": datetime.utcnow().isoformat(),
            }
            run.step_results = dict(step_results)
            run.current_step_id = node_id
            run.verification_details={**(run.verification_details or {}),"checkpoint_at":datetime.utcnow().isoformat()}
            db.commit()
        else:
            # Reacquire after the last checkpoint before marking terminal.
            db.expire_all()
            run = db.query(WorkflowRun).filter_by(id=run.id,business_id=run.business_id).with_for_update().populate_existing().one()
            if run.status != "running" or (run.verification_details or {}).get("execution_token") != token:
                db.rollback()
                return run
            run.status = "completed"
            run.completed_at = datetime.utcnow()

        run.step_results = dict(step_results)
        run.verified_success = False
        run.verification_details = {
            **(run.verification_details or {}),
            "verified": False,
            "dry_run": dry_run,
            "node_order": [node["id"] for node in ordered_nodes],
            "definition_digest": self._definition_digest(wf),
            "reason": "Dry run only" if dry_run else "No independent outcome verification configured",
        }
        db.add(AuditLog(
            business_id=run.business_id,
            actor=f"Workflow: {wf.name}",
            action="resume_workflow" if start_index else "execute_workflow",
            target_entity="WorkflowRun",
            details={"run_id": run.id, "status": run.status, "steps_recorded": len(step_results)},
            risk_level="high" if run.status == "awaiting_approval" else "low",
        ))
        db.commit()
        db.refresh(run)
        return run

    def execute_workflow(
        self,
        db: Session,
        business_id: str,
        workflow_id: str,
        trigger_source: str = "manual",
        dry_run: bool = False,
        idempotency_key: Optional[str] = None,
        event_payload: Optional[dict] = None,
        expected_event_digest: Optional[str] = None,
    ) -> WorkflowRun:
        # A key is a non-secret client-supplied request identity. PostgreSQL
        # advisory transaction locking serializes first-use checks across
        # independent API processes, while the DB unique constraint is the
        # definitive integrity barrier.
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{8,128}", idempotency_key
            ):
                raise ValueError("Invalid workflow idempotency key")
            if db.get_bind().dialect.name == "postgresql":
                lock_hash = hashlib.sha256(
                    (business_id + ":" + idempotency_key).encode("utf-8")
                ).digest()[:8]
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": int.from_bytes(lock_hash, "big", signed=True)},
                )
            previous = db.query(WorkflowRun).filter(
                WorkflowRun.business_id == business_id,
                WorkflowRun.idempotency_key == idempotency_key,
            ).first()
            if previous:
                if (previous.workflow_id != workflow_id or
                        (previous.verification_details or {}).get("dry_run") != dry_run or
                        (previous.verification_details or {}).get("event_payload") != event_payload):
                    raise ValueError("Workflow idempotency key conflicts with a different request")
                return previous

        wf = db.query(WorkflowDefinition).filter(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.business_id == business_id,
        ).with_for_update().populate_existing().first()
        if not wf or not wf.is_active or not wf.is_valid:
            raise ValueError("Workflow not found, inactive or invalid for this business")
        if expected_event_digest is not None and fingerprint(db,wf)!=expected_event_digest:
            raise ValueError("Event definition changed before dispatch")
        ordered_nodes = self._ordered_nodes({"nodes": wf.nodes or [], "edges": wf.edges or []})
        validate_conditions(ordered_nodes,wf.edges or [])

        run = WorkflowRun(
            workflow_id=wf.id,
            business_id=business_id,
            idempotency_key=idempotency_key,
            workflow_name=wf.name,
            status="running",
            trigger_source=trigger_source,
            step_results={},
            verification_details={
                "verified": False,
                "dry_run": dry_run,
                "node_order": [node["id"] for node in ordered_nodes],
                "definition_digest": self._definition_digest(wf),
                "reason": "Execution started, outcome not yet verified",
                "execution_token": str(uuid4()), "checkpoint_protocol": 1, "recovery_count": 0,
                "event_payload":event_payload,
                "definition_revision":revision_number(db,business_id,wf.id),
                "checkpoint_at":datetime.utcnow().isoformat(),
            },
        )
        db.add(run)
        db.flush()
        # Persist this checkpoint BEFORE any tool is invoked. If the API
        # worker crashes after returning control to an external adapter,
        # later workers can see 'running' and quarantine it for review.
        # A retry with the same tenant/key returns this existing run and
        # never blindly dispatches the steps a second time.
        db.commit()
        db.refresh(run)
        return self._execute_steps(db, run, wf, ordered_nodes, 0, {}, dry_run=dry_run)

    def reconcile_interrupted_runs(
        self, db: Session, business_id: str, older_than_seconds: int = 900
    ) -> int:
        """Quarantine stale running records, never replay uncertain effects.

        After a crash between a durable approval claim and final commit, the
        run may be 'running' while a tool's effect is unknown. Automatic retry
        is unsafe. An authorized operator may mark only sufficiently old
        records as paused for manual review, without dispatching any tool.
        """
        if not business_id or not 300 <= older_than_seconds <= 86400:
            raise ValueError("Recovery requires a tenant and age between 5 minutes and 1 day")
        cutoff = datetime.utcnow() - timedelta(seconds=older_than_seconds)
        stale = db.query(WorkflowRun).filter(
            WorkflowRun.business_id == business_id,
            WorkflowRun.status == "running",
            WorkflowRun.started_at < cutoff,
        ).all()
        changed = 0
        for run in stale:
            run=db.query(WorkflowRun).filter_by(business_id=business_id,id=run.id,status="running").with_for_update().populate_existing().first()
            if not run:continue
            # Recent durable checkpoints are not interrupted runs.
            try:
                checkpoint_at=datetime.fromisoformat((run.verification_details or {}).get("checkpoint_at",""))
                if checkpoint_at>=cutoff:continue
            except (ValueError,TypeError):pass
            # Conditional transition avoids resurrecting or pausing a run
            # that another worker has already completed.
            claimed = db.query(WorkflowRun).filter(
                WorkflowRun.id == run.id,
                WorkflowRun.business_id == business_id,
                WorkflowRun.status == "running",
            ).update({
                "status": "paused",
                "error_message": "Execution interrupted; manual review required before any retry",
                "verified_success": False,
            }, synchronize_session=False)
            if claimed:
                db.add(AuditLog(
                    business_id=business_id,
                    actor="Workflow recovery",
                    action="quarantine_interrupted_workflow",
                    target_entity="WorkflowRun",
                    details={"run_id": run.id, "automatic_replay": False},
                    risk_level="high",
                ))
                changed += 1
        db.commit()
        return changed

    def _dispatch_node_tool(
        self, db: Session, business_id: str, node_type: str, node_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        if self.tool_policy(node_type,node_data) == "denied":
            raise ValueError("Unsupported workflow tool or node type")
        connector = node_data.get("connector", "")

        if node_type == "trigger":
            return {"triggered": True, "type": "control"}
        # Never choose an executable tool from an untrusted, human-readable
        # label. A node named "send invoice email" must not silently execute
        # a different tool because its label contains "invoice".
        if node_type == "data_fetch" and connector == "demo_finance":
            return ToolRegistry.read_overdue_invoices(db, business_id)
        if node_type == "calculate" and connector in ("", "demo_finance"):
            return ToolRegistry.calculate_invoice_totals(db, business_id)
        if node_type == "data_fetch" and connector == "demo_commitments":
            return ToolRegistry.check_commitment_deadlines(db, business_id)
        if node_type == "action" and connector == "demo_email" and (
            node_data.get("operation") == "draft_invoice_reminders"
        ):
            return ToolRegistry.draft_invoice_reminder_emails(db, business_id)
        # No live send action is implemented. Do not return a fabricated
        # delivery receipt or call a side-effecting tool by inference.
        raise ValueError("Unsupported workflow tool or node type")

    def approve_and_resume_run(
        self, db: Session, run_id: str, request_id: str, business_id: Optional[str] = None
    ) -> WorkflowRun:
        """Claim one pending approval atomically, then execute remaining nodes once."""
        if not business_id:
            raise PermissionError("Business context required for workflow approval")
        # All state-changing paths acquire the run lock before approval rows.
        run = db.query(WorkflowRun).filter(
            WorkflowRun.id == run_id,
            WorkflowRun.business_id == business_id,
        ).with_for_update().populate_existing().first() if isinstance(db,Session) else None
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.id == request_id,
            ApprovalRequest.business_id == business_id,
            ApprovalRequest.workflow_run_id == run_id,
        ).first()
        if not isinstance(db,Session):
            run = db.query(WorkflowRun).filter(WorkflowRun.id==run_id,WorkflowRun.business_id==business_id).first()
        if not request or not run:
            raise ValueError("Approval or workflow run not found")
        if request.status != "pending" or run.status != "awaiting_approval":
            raise ValueError("Approval is not pending or run cannot be resumed")
        checkpoint = (request.payload or {}).get("step_id")
        if not checkpoint or checkpoint != run.current_step_id:
            raise ValueError("Approval checkpoint does not match workflow run")

        wf_query = db.query(WorkflowDefinition).filter(
            WorkflowDefinition.id == run.workflow_id,
            WorkflowDefinition.business_id == business_id,
        )
        wf = wf_query.with_for_update().populate_existing().first() if isinstance(db,Session) else wf_query.first()
        if not wf:
            raise ValueError("Workflow definition is unavailable")
        ordered_nodes = self._ordered_nodes({"nodes": wf.nodes or [], "edges": wf.edges or []})
        order_ids = [node["id"] for node in ordered_nodes]
        if (order_ids != (run.verification_details or {}).get("node_order") or
                self._definition_digest(wf) != (run.verification_details or {}).get("definition_digest")):
            raise ValueError("Workflow definition changed since approval was requested")
        try:
            checkpoint_index = order_ids.index(checkpoint)
        except ValueError as exc:
            raise ValueError("Approval checkpoint no longer exists") from exc

        approved_node = ordered_nodes[checkpoint_index]
        pinned = request.payload or {}
        if "node_data" in pinned and pinned["node_data"] != (approved_node.get("data") or {}):
            raise ValueError("Approval payload changed")
        if "action_digest" in pinned and pinned["action_digest"] != self._action_digest(approved_node):
            raise ValueError("Approval action digest changed")

        required = {"step_id","node_data","action_digest","resolved_data","effect_preview","definition_digest","run_id","payload_digest"}
        if not required <= set(pinned) or pinned["run_id"] != run.id or pinned["definition_digest"] != self._definition_digest(wf):
            raise ValueError("Legacy or incomplete approval payload; create a fresh run")
        if (canonical_digest({k:v for k,v in pinned.items() if k!="payload_digest"}) != pinned["payload_digest"]
            or (run.step_results or {}).get(checkpoint,{}).get("payload_digest")!=pinned["payload_digest"]):
            raise ValueError("Approval payload digest changed")
        if isinstance(db,Session) and revision_number(db,business_id,wf.id)!=(run.verification_details or {}).get("definition_revision",0):
            raise ValueError("Workflow revision changed since approval was requested")
        if not wf.is_active or not wf.is_valid:
            raise ValueError("Workflow inactive")
        resolved = resolve_data(approved_node.get("data") or {},checkpoint,wf.edges or [],run.step_results or {})
        if resolved != pinned["resolved_data"] or preview_effect(db,business_id,approved_node.get("type"),resolved) != pinned["effect_preview"]:
            raise ValueError("Approval inputs changed; create a fresh run")
        now = datetime.utcnow()
        claimed = db.query(ApprovalRequest).filter(
            ApprovalRequest.id == request_id,
            ApprovalRequest.status == "pending",
            ApprovalRequest.business_id == business_id,
        ).update({"status": "approved", "reviewed_at": now}, synchronize_session=False)
        if claimed != 1:
            db.rollback()
            raise ValueError("Approval was already resolved")
        run_claimed = db.query(WorkflowRun).filter(
            WorkflowRun.id == run_id,
            WorkflowRun.business_id == business_id,
            WorkflowRun.status == "awaiting_approval",
        ).update({"status": "running","verification_details":{**(run.verification_details or {}),"execution_token":str(uuid4()),"checkpoint_at":datetime.utcnow().isoformat()}}, synchronize_session=False)
        if run_claimed != 1:
            db.rollback()
            raise ValueError("Workflow run was already resumed")
        # Keep approval claim, effect intent and checkpoint in one transaction.
        db.flush()
        db.refresh(run)

        step_results = dict(run.step_results or {})
        # Approval nodes are control checkpoints. A high-risk executable node,
        # however, must actually run after authorization; previously it was
        # silently skipped and reported only as "approved".
        approved_node = ordered_nodes[checkpoint_index]
        if approved_node.get("type") == "approval":
            step_results[checkpoint] = {
                "status": "approved",
                "request_id": request_id,
                "timestamp": now.isoformat(),
            }
        else:
            try:
                with db.begin_nested():
                    result = (condition_result(resolved) if approved_node.get("type")=="condition" else
                              self._dispatch_node_tool(db,business_id,approved_node.get("type"),resolved))
                    if isinstance(result,dict) and result.get("success") is False:
                        raise ValueError("Approved workflow tool reported failure")
                    if pinned["effect_preview"] is not None and result != pinned["effect_preview"]:
                        raise ValueError("Approved effect differs from preview")
                    self._record_draft_intent(db,run,checkpoint,approved_node.get("type"),resolved,result)
                    canonical_digest(result)
                    db.flush()
            except Exception as exc:
                logger.warning("Approved workflow action %s failed: %s", checkpoint, exc)
                step_results[checkpoint] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                run.status = "failed"
                run.error_message = f"Approved step '{checkpoint}' failed; inspect server logs"
                run.completed_at = datetime.utcnow()
                run.step_results = dict(step_results)
                db.commit()
                db.refresh(run)
                return run
            step_results[checkpoint] = {
                "status": "success",
                "approval_request_id": request_id,
                "result": result,
                "timestamp": datetime.utcnow().isoformat(),
            }
        run.step_results = dict(step_results)
        run.verification_details={**(run.verification_details or {}),"checkpoint_at":datetime.utcnow().isoformat()}
        db.commit()
        return self._execute_steps(db,run,wf,ordered_nodes,checkpoint_index+1,step_results)

    def cancel_run(self,db,tenant,run_id):
        run=db.query(WorkflowRun).filter_by(business_id=tenant,id=run_id).with_for_update().first()
        if not run:
            raise ValueError("Run unavailable")
        if run.status in ("completed","cancelled"):
            return run
        run.status="cancelled"
        run.completed_at=datetime.utcnow()
        db.query(SideEffectOutbox).filter_by(business_id=tenant,run_id=run.id,state="pending").update(
            {"state":"cancelled"},synchronize_session=False)
        run.verified_success=False
        db.query(ApprovalRequest).filter_by(business_id=tenant,workflow_run_id=run_id,status="pending").update(
            {"status":"cancelled","reviewed_at":datetime.utcnow()},synchronize_session=False)
        db.commit()
        return run

    def recover_run(self,db,tenant,run_id):
        run=db.query(WorkflowRun).filter_by(business_id=tenant,id=run_id).with_for_update().first()
        details=run.verification_details or {} if run else {}
        if not run or run.status not in ("paused","failed") or details.get("checkpoint_protocol")!=1 or details.get("dry_run"):
            raise ValueError("Run is not recoverable")
        if details.get("recovery_count",0)>=2:
            raise ValueError("Recovery limit reached")
        wf=db.query(WorkflowDefinition).filter_by(business_id=tenant,id=run.workflow_id,is_active=True,is_valid=True).first()
        if not wf or self._definition_digest(wf)!=details.get("definition_digest") or revision_number(db,tenant,wf.id)!=details.get("definition_revision",0):
            raise ValueError("Workflow changed")
        nodes=self._ordered_nodes({"nodes":wf.nodes,"edges":wf.edges})
        results=dict(run.step_results or {})
        index=next((i for i,n in enumerate(nodes) if results.get(n["id"],{}).get("status") not in ("success","approved","skipped")),len(nodes))
        if index<len(nodes):
            previous=results.get(nodes[index]["id"],{})
            if previous.get("status") in ("rejected","awaiting_founder_approval"):
                raise ValueError("Rejected or unresolved approval cannot be recovered")
            results.pop(nodes[index]["id"],None)
        run.status="running";run.error_message=None;run.completed_at=None
        run.verification_details={**details,"execution_token":str(uuid4()),"recovery_count":details.get("recovery_count",0)+1,"checkpoint_at":datetime.utcnow().isoformat()}
        db.commit()
        return self._execute_steps(db,run,wf,nodes,index,results)


workflow_engine = WorkflowEngine()
