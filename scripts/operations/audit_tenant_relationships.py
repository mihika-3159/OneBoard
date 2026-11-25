"""Read-only owner audit: report counts, never record IDs or credentials."""
import json
import os
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from apps.api.core.database import Base

def audit(engine):
    import apps.api.models.business,apps.api.models.entities,apps.api.models.goals_tasks
    import apps.api.models.agent_council,apps.api.models.decision_evidence,apps.api.models.memory
    import apps.api.models.workflow,apps.api.models.integrations,apps.api.models.operations
    refs=[("memory_documents","memory_chunks","document_id"),("memory_chunks","semantic_vectors","chunk_id"),
          ("workflow_definitions","workflow_runs","workflow_id"),("workflow_runs","approval_requests","workflow_run_id"),
          ("workflow_runs","side_effect_outbox","run_id"),("workflow_definitions","workflow_schedules","workflow_id"),
          ("workflow_runs","workflow_schedules","last_run_id"),("invoices","settlement_evidence","invoice_id"),
          ("customers","invoices","customer_id"),("customers","support_tickets","customer_id"),
          ("goals","tasks","goal_id"),("decisions","tasks","decision_id"),("tasks","approval_requests","task_id"),
          ("users","user_sessions","user_id"),("users","account_security","user_id")]
    report={}
    with engine.connect() as c:
        if c.dialect.name=="postgresql":
            c.execute(text("SET TRANSACTION READ ONLY"))
            owner=c.execute(text("SELECT current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.businesses'::regclass)")).scalar_one()
            if not owner: raise RuntimeError("Migration-owner audit connection required")
        for table in Base.metadata.tables.values():
            if "business_id" in table.c:
                report["missing_workspace:"+table.name]=c.execute(text(f"SELECT count(*) FROM {table.name} x LEFT JOIN businesses b ON b.id=x.business_id WHERE b.id IS NULL")).scalar_one()
        for parent,child,column in refs:
            report[f"invalid_ref:{child}.{column}"]=c.execute(text(f"SELECT count(*) FROM {child} x LEFT JOIN {parent} p ON p.id=x.{column} AND p.business_id=x.business_id WHERE x.{column} IS NOT NULL AND p.id IS NULL")).scalar_one()
        report["invalid_ref:sync_history.integration_id"]=c.execute(text("SELECT count(*) FROM sync_history s LEFT JOIN integration_accounts i ON s.integration_id=i.id WHERE i.id IS NULL")).scalar_one()
        report["invalid_ref:businesses.owner_id"]=c.execute(text("SELECT count(*) FROM businesses b LEFT JOIN users u ON u.id=b.owner_id AND u.business_id=b.id WHERE b.owner_id IS NOT NULL AND u.id IS NULL")).scalar_one()
        report["invalid_ref:business_memberships.user_id"]=c.execute(text("SELECT count(*) FROM business_memberships m LEFT JOIN users u ON u.id=m.user_id WHERE u.id IS NULL")).scalar_one()
    return {"counts":report,"invalid_total":sum(report.values()),"polymorphic_json_refs_not_automatically_validated":True}
def main():
    if os.environ.get("ONEBOARD_RELATIONSHIP_AUDIT_APPROVED")!="YES":
        raise SystemExit("Explicit owner approval required")
    url=make_url(os.environ["DATABASE_URL"])
    if url.host not in ("127.0.0.1","localhost","::1") and url.query.get("sslmode")!="verify-full":
        raise SystemExit("Remote audit requires verified TLS")
    engine=create_engine(url)
    try:
        result=audit(engine)
        print(json.dumps(result,indent=2))
        if result["invalid_total"]: raise SystemExit(1)
    finally: engine.dispose()
if __name__=="__main__": main()
