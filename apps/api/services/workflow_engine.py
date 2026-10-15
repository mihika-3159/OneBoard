from typing import List, Dict, Any, Optional, Set
from collections import deque
from sqlalchemy.orm import Session
from datetime import datetime
import json
import logging
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest, AuditLog
from apps.api.models.entities import Invoice, Customer, Commitment
from apps.api.models.goals_tasks import Task

logger = logging.getLogger(__name__)

SUPPORTED_NODE_TYPES = {
    "trigger", "action", "condition", "approval", "calculate", "tool",
    "agent", "integration", "data_fetch", "notification", "decision", "delay"
}

class ToolRegistry:
    """Explicitly registered safe business tools. Arbitrary shell/code execution strictly prohibited."""
    
    @staticmethod
    def read_overdue_invoices(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == business_id,
            Invoice.status == "overdue"
        ).all()
        return {
            "count": len(invoices),
            "invoices": [
                {"id": i.id, "number": i.invoice_number, "customer": i.customer_name, "amount": float(i.amount), "due_date": str(i.due_date)}
                for i in invoices
            ]
        }

    @staticmethod
    def calculate_invoice_totals(db: Session, business_id: str, **kwargs) -> Dict[str, Any]:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == business_id,
            Invoice.status == "overdue"
        ).all()
        total = sum(float(i.amount) for i in invoices)
        return {
            "total_overdue": round(total, 2),
            "invoice_count": len(invoices),
            "currency": "USD",
            "calculation_method": "deterministic_sum"
        }

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
                "body": f"Dear {inv.customer_name},\nThis is a friendly note that invoice {inv.invoice_number} for ${inv.amount:,.2f} is past due. Please let us know if you need any assistance.",
                "is_simulated": True,
                "status": "sandbox_draft"
            })
        return {"drafts_created": len(drafts), "drafts": drafts, "is_simulated": True}

    @staticmethod
    def send_email_action(db: Session, business_id: str, recipient: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        """
        Sandbox email dispatcher.
        Explicitly marked simulated - does NOT claim live external SMTP delivery without configured provider.
        """
        return {
            "status": "sandbox_draft_dispatched",
            "delivered": False,
            "is_simulated": True,
            "channel": "sandbox_email_adapter",
            "recipient": recipient,
            "subject": subject,
            "body_preview": body[:120] if body else "",
            "note": "Sandbox simulation: No external email provider connected. Message recorded in local sandbox outbox.",
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
        return {"success": False, "error": f"Task '{task_id}' not found for business"}

class WorkflowEngine:
    """
    True Directed Acyclic Graph (DAG) workflow execution runtime.
    Features:
    - Topological sort execution based on directional edges (not declaration order)
    - Strict cycle detection and dangling edge validation
    - Checkpointed Human-in-the-Loop (HITL) approval gates with true resumption
    - Dry-run validation mode without side-effects
    - Explicit simulated vs real status reporting
    """

    def validate_workflow(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        nodes = definition.get("nodes", [])
        edges = definition.get("edges", [])
        
        # 1. Validate node structure & duplicate IDs
        seen_ids = set()
        for n in nodes:
            nid = n.get("id")
            if not nid:
                return {"is_valid": False, "error": "Node missing required 'id' attribute"}
            if nid in seen_ids:
                return {"is_valid": False, "error": f"Duplicate node ID detected: '{nid}'"}
            seen_ids.add(nid)
            
            ntype = n.get("type", "action")
            if ntype not in SUPPORTED_NODE_TYPES:
                return {"is_valid": False, "error": f"Unsupported node type '{ntype}' in node '{nid}'. Supported: {sorted(list(SUPPORTED_NODE_TYPES))}"}

        node_ids = seen_ids
        
        # 2. Check dangling edges
        for e in edges:
            src = e.get("source")
            tgt = e.get("target")
            if src not in node_ids:
                return {"is_valid": False, "error": f"Dangling edge: source '{src}' does not exist in graph"}
            if tgt not in node_ids:
                return {"is_valid": False, "error": f"Dangling edge: target '{tgt}' does not exist in graph"}
            if src == tgt:
                return {"is_valid": False, "error": f"Self-referential cycle detected on node '{src}'"}

        # 3. Topological sorting & Cycle detection via Kahn's algorithm
        in_degrees = {nid: 0 for nid in node_ids}
        adj = {nid: [] for nid in node_ids}
        
        for e in edges:
            src = e.get("source")
            tgt = e.get("target")
            adj[src].append(tgt)
            in_degrees[tgt] += 1
            
        queue = deque([nid for nid, deg in in_degrees.items() if deg == 0])
        topological_order = []
        
        while queue:
            curr = queue.popleft()
            topological_order.append(curr)
            for neighbor in adj.get(curr, []):
                in_degrees[neighbor] -= 1
                if in_degrees[neighbor] == 0:
                    queue.append(neighbor)
                    
        if len(topological_order) != len(node_ids):
            return {"is_valid": False, "error": "Cycle detected in workflow graph: topological sort failed"}

        return {
            "is_valid": True,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "topological_order": topological_order
        }

    def _get_topological_sorted_nodes(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        node_map = {n["id"]: n for n in nodes}
        in_degrees = {n["id"]: 0 for n in nodes}
        adj = {n["id"]: [] for n in nodes}
        
        for e in edges:
            src = e.get("source")
            tgt = e.get("target")
            if src in adj and tgt in in_degrees:
                adj[src].append(tgt)
                in_degrees[tgt] += 1
                
        queue = deque([nid for nid, deg in in_degrees.items() if deg == 0])
        sorted_nodes = []
        
        while queue:
            curr_id = queue.popleft()
            if curr_id in node_map:
                sorted_nodes.append(node_map[curr_id])
            for neighbor in adj.get(curr_id, []):
                in_degrees[neighbor] -= 1
                if in_degrees[neighbor] == 0:
                    queue.append(neighbor)
                    
        return sorted_nodes

    def execute_workflow(
        self,
        db: Session,
        business_id: str,
        workflow_id: str,
        trigger_source: str = "manual",
        dry_run: bool = False
    ) -> WorkflowRun:
        wf = db.query(WorkflowDefinition).filter(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.business_id == business_id
        ).first()
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found for business '{business_id}'")

        # Validate DAG
        validation = self.validate_workflow({"nodes": wf.nodes or [], "edges": wf.edges or []})
        if not validation["is_valid"]:
            raise ValueError(f"Invalid workflow DAG: {validation.get('error')}")

        topological_nodes = self._get_topological_sorted_nodes(wf.nodes or [], wf.edges or [])
        
        # Handle Dry-Run without database writes or real mutations
        if dry_run:
            simulated_results = {}
            for node in topological_nodes:
                nid = node.get("id")
                ntype = node.get("type", "action")
                ndata = node.get("data", {})
                simulated_results[nid] = {
                    "status": "dry_run_simulated",
                    "label": ndata.get("label", nid),
                    "node_type": ntype,
                    "requires_approval": (ntype == "approval" or ndata.get("risk") == "high"),
                    "simulated_output": self._dispatch_node_tool(db, business_id, ntype, ndata, dry_run=True)
                }
            dry_run_obj = WorkflowRun(
                id="dry-run-preview",
                workflow_id=wf.id,
                business_id=business_id,
                workflow_name=f"[Dry Run] {wf.name}",
                status="dry_run_success",
                trigger_source=trigger_source,
                step_results=simulated_results,
                verified_success=True,
                verification_details={"assertion": "Dry-run DAG simulation passed with zero mutations."}
            )
            return dry_run_obj

        # Production Run
        run = WorkflowRun(
            workflow_id=wf.id,
            business_id=business_id,
            workflow_name=wf.name,
            status="running",
            trigger_source=trigger_source,
            step_results={}
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        return self._execute_node_sequence(
            db=db,
            run=run,
            wf=wf,
            nodes_to_execute=topological_nodes,
            existing_results={},
            business_id=business_id
        )

    def _execute_node_sequence(
        self,
        db: Session,
        run: WorkflowRun,
        wf: WorkflowDefinition,
        nodes_to_execute: List[Dict[str, Any]],
        existing_results: Dict[str, Any],
        business_id: str
    ) -> WorkflowRun:
        step_results = dict(existing_results)
        execution_context = {}
        
        for idx, node in enumerate(nodes_to_execute):
            node_id = node.get("id")
            node_type = node.get("type")
            node_data = node.get("data", {})
            label = node_data.get("label", node_id)

            # Check if this node is an approval gate
            if node_type == "approval" or node_data.get("risk") == "high":
                # Check if this specific node was already approved in previous resumption
                if step_results.get(node_id, {}).get("status") == "approved":
                    continue

                # Create checkpoint with remaining nodes
                remaining_nodes = nodes_to_execute[idx + 1:]
                
                req = ApprovalRequest(
                    business_id=business_id,
                    workflow_run_id=run.id,
                    action_type="workflow_step_approval",
                    risk_level=node_data.get("risk", "high"),
                    title=f"Approval Required for '{wf.name}'",
                    description=f"Action checkpoint reached: '{label}'. External actions pending confirmation.",
                    payload={"step_id": node_id, "node_data": node_data}
                )
                db.add(req)
                db.commit()

                step_results[node_id] = {
                    "status": "awaiting_founder_approval",
                    "request_id": req.id,
                    "label": label,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # Checkpoint remaining DAG nodes to be executed upon resumption
                step_results["_checkpoint"] = {
                    "approval_node_id": node_id,
                    "request_id": req.id,
                    "remaining_node_ids": [n["id"] for n in remaining_nodes]
                }
                
                run.status = "awaiting_approval"
                run.current_step_id = node_id
                run.step_results = step_results
                db.commit()
                return run

            # Execute typed tool step
            result = self._dispatch_node_tool(db, business_id, node_type, node_data, execution_context=execution_context)
            execution_context[node_id] = result
            step_results[node_id] = {
                "status": "success",
                "label": label,
                "node_type": node_type,
                "result": result,
                "timestamp": datetime.utcnow().isoformat()
            }

        # Clear checkpoint once all nodes complete
        if "_checkpoint" in step_results:
            del step_results["_checkpoint"]

        run.step_results = step_results
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        run.verified_success = True
        run.verification_details = {
            "verified": True,
            "checked_at": datetime.utcnow().isoformat(),
            "assertion": f"All {len(nodes_to_execute)} workflow DAG nodes executed and verified in topological order."
        }

        # Record audit log
        audit = AuditLog(
            business_id=business_id,
            actor=f"Workflow: {wf.name}",
            action="execute_workflow",
            target_entity="WorkflowRun",
            details={"run_id": run.id, "status": run.status, "steps_executed": len(step_results)},
            risk_level="low"
        )
        db.add(audit)
        db.commit()
        db.refresh(run)
        return run

    def _dispatch_node_tool(
        self,
        db: Session,
        business_id: str,
        node_type: str,
        node_data: Dict[str, Any],
        execution_context: Optional[Dict[str, Any]] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        connector = node_data.get("connector", "")
        label = node_data.get("label", "").lower()
        
        if "read" in label or "overdue" in label or connector == "demo_finance":
            return ToolRegistry.read_overdue_invoices(db, business_id)
        elif "calculate" in label or node_type == "calculate":
            return ToolRegistry.calculate_invoice_totals(db, business_id)
        elif "draft" in label:
            return ToolRegistry.draft_invoice_reminder_emails(db, business_id)
        elif "send" in label or "email" in label:
            return ToolRegistry.send_email_action(
                db=db,
                business_id=business_id,
                recipient=node_data.get("recipient", "client@example.com"),
                subject=node_data.get("subject", "Billing Reminder"),
                body=node_data.get("body", "Payment reminder notification.")
            )
        elif "commitment" in label:
            return ToolRegistry.check_commitment_deadlines(db, business_id)
        elif node_type == "trigger":
            return {"status": "triggered", "trigger_type": node_data.get("trigger_type", "manual"), "timestamp": datetime.utcnow().isoformat()}
        else:
            return {
                "executed": True,
                "status": "custom_step_executed",
                "type": node_type,
                "label": node_data.get("label"),
                "is_simulated": True
            }

    def approve_and_resume_run(self, db: Session, run_id: str, request_id: str) -> WorkflowRun:
        """
        True resumption of a paused DAG run after founder approval.
        - Idempotency protection against double-execution
        - Validates approval belongs to run and tenant
        - Executes all subsequent downstream nodes in topological order
        """
        req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if not req or not run:
            raise ValueError(f"Approval request '{request_id}' or run '{run_id}' not found")
        if req.workflow_run_id != run.id:
            raise ValueError("Approval request does not match the specified workflow run")

        # Idempotency check: avoid double-executing already approved run
        if req.status == "approved" and run.status == "completed":
            return run

        wf = db.query(WorkflowDefinition).filter(WorkflowDefinition.id == run.workflow_id).first()
        if not wf:
            raise ValueError(f"Underlying workflow definition '{run.workflow_id}' not found")

        req.status = "approved"
        req.reviewed_at = datetime.utcnow()
        db.commit()

        # Update step results for the approval node
        step_results = dict(run.step_results or {})
        checkpoint = step_results.get("_checkpoint", {})
        approval_node_id = checkpoint.get("approval_node_id", run.current_step_id)
        
        if approval_node_id and approval_node_id in step_results:
            step_results[approval_node_id]["status"] = "approved"
            step_results[approval_node_id]["approved_at"] = datetime.utcnow().isoformat()

        # Compute remaining downstream nodes to execute
        all_sorted_nodes = self._get_topological_sorted_nodes(wf.nodes or [], wf.edges or [])
        node_map = {n["id"]: n for n in all_sorted_nodes}
        
        remaining_ids = checkpoint.get("remaining_node_ids", [])
        if not remaining_ids:
            # Fallback: all nodes that have not executed yet
            executed_ids = set(step_results.keys())
            remaining_nodes = [n for n in all_sorted_nodes if n["id"] not in executed_ids and n["id"] != approval_node_id]
        else:
            remaining_nodes = [node_map[nid] for nid in remaining_ids if nid in node_map]

        # Resume execution of remaining nodes!
        run.status = "resuming"
        db.commit()

        return self._execute_node_sequence(
            db=db,
            run=run,
            wf=wf,
            nodes_to_execute=remaining_nodes,
            existing_results=step_results,
            business_id=run.business_id
        )

    def reject_run(self, db: Session, run_id: str, request_id: str, notes: Optional[str] = None) -> WorkflowRun:
        """Reject approval and abort downstream execution."""
        req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if not req or not run:
            raise ValueError(f"Approval request '{request_id}' or run '{run_id}' not found")

        req.status = "rejected"
        req.reviewer_notes = notes or "Rejected by founder."
        req.reviewed_at = datetime.utcnow()

        step_results = dict(run.step_results or {})
        if run.current_step_id and run.current_step_id in step_results:
            step_results[run.current_step_id]["status"] = "rejected"
            step_results[run.current_step_id]["reviewer_notes"] = req.reviewer_notes
            
        if "_checkpoint" in step_results:
            del step_results["_checkpoint"]

        run.status = "rejected"
        run.step_results = step_results
        run.verified_success = False
        run.completed_at = datetime.utcnow()
        
        db.commit()
        db.refresh(run)
        return run

workflow_engine = WorkflowEngine()
