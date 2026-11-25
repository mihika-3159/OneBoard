"""Only registered transactional intents may produce effects. No external transport."""
import hashlib,json
from apps.api.models.operations import SideEffectOutbox


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


# New effect types must register a transaction-only intent handler here and
# implement a separate explicitly authorized, idempotent dispatch adapter.
EFFECTS={"invoice_reminder_draft"}


def stage_effect(db,run,step_id,kind,payload):
    if kind not in EFFECTS:
        raise ValueError("Unregistered workflow effect")
    digest=canonical_digest(payload)
    row=db.query(SideEffectOutbox).filter_by(business_id=run.business_id,run_id=run.id,step_id=step_id).first()
    if row:
        if row.kind!=kind or canonical_digest(row.payload)!=digest:
            raise ValueError("Conflicting effect replay")
        return row
    row=SideEffectOutbox(business_id=run.business_id,run_id=run.id,step_id=step_id,kind=kind,payload=payload,state="pending")
    db.add(row)
    db.flush()
    return row


def preview_effect(db,tenant,node_type,data):
    if node_type=="action" and data.get("connector")=="demo_email" and data.get("operation")=="draft_invoice_reminders":
        from apps.api.services.workflow_engine import ToolRegistry
        return ToolRegistry.draft_invoice_reminder_emails(db,tenant)
    return None
