from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import json
import logging
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest, AuditLog
from apps.api.models.entities import Invoice, Customer, Commitment
from apps.api.models.goals_tasks import Task

logger = logging.getLogger(__name__)

class ToolRegistry:
    """Explicitly registered safe business tools. Arbitrary execution strictly prohibited."""
    
    @staticmethod
    def read_overdue_invoices(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == business_id,
            Invoice.status == "overdue"
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
            Invoice.status == "overdue"
        ).all()
        total = sum(i.amount for i in invoices)
        return {"total_overdue": total, "invoice_count": len(invoices)}

    @staticmethod
    def draft_invoice_reminder_emails(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == business_id,
            Invoice.status == "overdue"
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
        # Demo email adapter simulation
        return {
            "delivered": True,
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
            db.commit()
            return {"success": True, "task_id": task_id, "new_status": status}
        return {"success": False, "error": "Task not found"}


class WorkflowEngine:
    """Tenant-scoped workflow runner with deterministic DAG ordering and resumable approvals."""

    MAX_NODES = 100
    MAX_EDGES = 300

    def _ordered_nodes(self, definition: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return a stable topological order or fail before any step is executed."""
        import heapq

        nodes = definition.get("nodes", [])
        edges = definition.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("Workflow nodes and edges must be lists")
        if len(nodes) > self.MAX_NODES or len(edges) > self.MAX_EDGES:
            raise ValueError("Workflow exceeds node or edge limits")

        by_id = {}
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("Workflow node must be an object")
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id.strip():
                raise ValueError("Workflow node IDs must be nonempty strings")
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

    def validate_workflow(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        try:
            nodes = self._ordered_nodes(definition)
            return {
                "is_valid": True,
                "node_count": len(nodes),
                "edge_count": len(definition.get("edges", [])),
            }
        except ValueError as exc:
            return {"is_valid": False, "error": str(exc)}

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
        run.current_step_id = None
        for node in ordered_nodes[start_index:]:
            node_id = node["id"]
            node_type = node.get("type")
            node_data = node.get("data") or {}
            label = node_data.get("label", node_id)

            if dry_run:
                step_results[node_id] = {
                    "status": "simulated",
                    "label": label,
                    "would_request_approval": node_type == "approval" or node_data.get("risk") == "high",
                }
                continue

            if node_type == "approval" or node_data.get("risk") == "high":
                request = ApprovalRequest(
                    business_id=run.business_id,
                    workflow_run_id=run.id,
                    action_type="workflow_step_approval",
                    risk_level="high",
                    title=f"Approval Required for '{wf.name}'",
                    description=f"Action checkpoint reached: '{label}'. External actions pending confirmation.",
                    payload={"step_id": node_id, "node_data": node_data},
                )
                db.add(request)
                db.flush()
                step_results[node_id] = {
                    "status": "awaiting_founder_approval",
                    "request_id": request.id,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                run.status = "awaiting_approval"
                run.current_step_id = node_id
                break

            try:
                result = self._dispatch_node_tool(db, run.business_id, node_type, node_data)
                if isinstance(result, dict) and result.get("success") is False:
                    raise ValueError("Workflow tool reported failure")
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
        else:
            run.status = "completed"
            run.completed_at = datetime.utcnow()

        run.step_results = dict(step_results)
        run.verified_success = False
        run.verification_details = {
            "verified": False,
            "dry_run": dry_run,
            "node_order": [node["id"] for node in ordered_nodes],
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
    ) -> WorkflowRun:
        wf = db.query(WorkflowDefinition).filter(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.business_id == business_id,
        ).first()
        if not wf:
            raise ValueError("Workflow not found for this business")
        ordered_nodes = self._ordered_nodes({"nodes": wf.nodes or [], "edges": wf.edges or []})

        run = WorkflowRun(
            workflow_id=wf.id,
            business_id=business_id,
            workflow_name=wf.name,
            status="running",
            trigger_source=trigger_source,
            step_results={},
        )
        db.add(run)
        db.flush()
        return self._execute_steps(db, run, wf, ordered_nodes, 0, {}, dry_run=dry_run)

    def _dispatch_node_tool(
        self, db: Session, business_id: str, node_type: str, node_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        connector = node_data.get("connector", "")
        label = str(node_data.get("label", "")).lower()

        if node_type == "trigger":
            return {"triggered": True, "type": "control"}
        if connector == "demo_finance" or "invoice" in label:
            return ToolRegistry.read_overdue_invoices(db, business_id)
        if node_type == "calculate" or "calculate" in label:
            return ToolRegistry.calculate_invoice_totals(db, business_id)
        if "draft" in label or "email" in label:
            return ToolRegistry.draft_invoice_reminder_emails(db, business_id)
        if "commitment" in label:
            return ToolRegistry.check_commitment_deadlines(db, business_id)
        raise ValueError("Unsupported workflow tool or node type")

    def approve_and_resume_run(
        self, db: Session, run_id: str, request_id: str, business_id: Optional[str] = None
    ) -> WorkflowRun:
        """Claim one pending approval atomically, then execute remaining nodes once."""
        if not business_id:
            raise PermissionError("Business context required for workflow approval")
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.id == request_id,
            ApprovalRequest.business_id == business_id,
            ApprovalRequest.workflow_run_id == run_id,
        ).first()
        run = db.query(WorkflowRun).filter(
            WorkflowRun.id == run_id,
            WorkflowRun.business_id == business_id,
        ).first()
        if not request or not run:
            raise ValueError("Approval or workflow run not found")
        if request.status != "pending" or run.status != "awaiting_approval":
            raise ValueError("Approval is not pending or run cannot be resumed")
        checkpoint = (request.payload or {}).get("step_id")
        if not checkpoint or checkpoint != run.current_step_id:
            raise ValueError("Approval checkpoint does not match workflow run")

        wf = db.query(WorkflowDefinition).filter(
            WorkflowDefinition.id == run.workflow_id,
            WorkflowDefinition.business_id == business_id,
        ).first()
        if not wf:
            raise ValueError("Workflow definition is unavailable")
        ordered_nodes = self._ordered_nodes({"nodes": wf.nodes or [], "edges": wf.edges or []})
        order_ids = [node["id"] for node in ordered_nodes]
        if order_ids != (run.verification_details or {}).get("node_order"):
            raise ValueError("Workflow definition changed since approval was requested")
        try:
            checkpoint_index = order_ids.index(checkpoint)
        except ValueError as exc:
            raise ValueError("Approval checkpoint no longer exists") from exc

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
        ).update({"status": "running"}, synchronize_session=False)
        if run_claimed != 1:
            db.rollback()
            raise ValueError("Workflow run was already resumed")
        db.commit()  # Durable claim: a crash cannot cause automatic duplicate execution.
        db.refresh(run)

        step_results = dict(run.step_results or {})
        step_results[checkpoint] = {
            "status": "approved",
            "request_id": request_id,
            "timestamp": now.isoformat(),
        }
        return self._execute_steps(
            db, run, wf, ordered_nodes, checkpoint_index + 1, step_results
        )


workflow_engine = WorkflowEngine()
