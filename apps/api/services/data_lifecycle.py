"""Owner-only export/deletion and opt-in document retention."""
from datetime import datetime,timedelta
import math
from decimal import Decimal
from sqlalchemy import select,delete
from apps.api.core.database import Base,tenant_lifecycle_lock
from apps.api.models.business import Business,User,BusinessMembership,UserSession
from apps.api.models.integrations import IntegrationAccount
from apps.api.models.memory import MemoryDocument,MemoryChunk,MemoryDocumentState,MemoryRelevanceFeedback
from apps.api.models.operations import SemanticVector,DataRetentionPolicy,AlertSnapshot
from apps.api.services.tenant_storage import _lock

EXCLUDED={"login_throttle_states","scheduled_job_leases","user_sessions","scheduler_cursors","account_security"}
SECRET_COLUMNS={"password_hash","hashed_password","api_key","token","token_hash",
                "encrypted_token","configuration","vector","embedding","mfa_ciphertext","pending_mfa_ciphertext","recovery_hashes","email_challenge_hash","email_challenge_ciphertext"}
def _safe(value):
    if isinstance(value,Decimal):return format(value,'f')
    if isinstance(value,float) and not math.isfinite(value):
        return None
    if isinstance(value,dict):
        return {k:_safe(v) for k,v in value.items() if k.lower() not in SECRET_COLUMNS}
    if isinstance(value,list):
        return [_safe(v) for v in value]
    return value

def owner(db,user):
    biz=db.query(Business).filter_by(id=user.business_id,owner_id=user.id).first()
    if biz is None:
        raise PermissionError("Workspace owner required")
    return biz

def _scope(table,tenant):
    if table.name=="businesses":
        return table.c.id==tenant
    if table.name=="sync_history":
        return table.c.integration_id.in_(select(IntegrationAccount.id).where(IntegrationAccount.business_id==tenant))
    if "business_id" in table.c:
        return table.c.business_id==tenant
    return None

def export_tables():
    return sorted(t.name for t in Base.metadata.tables.values()
                  if t.name not in EXCLUDED and _scope(t,"x") is not None)

def export_page(db,tenant,table_name,offset=0,limit=50):
    if table_name not in export_tables() or not 0<=offset<=1000000 or not 1<=limit<=100:
        raise ValueError("Invalid export table or page")
    table=Base.metadata.tables[table_name]
    columns=[c for c in table.c if c.name not in SECRET_COLUMNS]
    rows=db.execute(select(*columns).where(_scope(table,tenant)).order_by(*table.primary_key.columns).offset(offset).limit(limit+1)).mappings().all()
    return {"table":table_name,"rows":[_safe(dict(row)) for row in rows[:limit]],
            "next_offset":offset+limit if len(rows)>limit else None,
            "snapshot_consistent":False,"secrets_excluded":True}

def export_snapshot(db,user,max_bytes=32*1024*1024,max_rows=20000):
    """One bounded consistent JSON snapshot, never silently truncate.

    PostgreSQL REPEATABLE READ establishes a single MVCC view. SQLite's
    explicit read transaction does the same for the local-only database.
    Existing paginated exports remain explicitly non-snapshot.
    """
    import json
    from sqlalchemy.orm import Session
    from apps.api.core.database import scope_tenant_session
    tenant=user.business_id
    owner_id=user.id
    bind=db.get_bind()
    with bind.connect() as conn:
        if conn.dialect.name=="postgresql":
            conn=conn.execution_options(isolation_level="REPEATABLE READ")
        else:
            conn.exec_driver_sql("BEGIN")
        with Session(bind=conn) as snapshot:
            scope_tenant_session(snapshot,tenant)
            if not snapshot.query(Business.id).filter_by(id=tenant,owner_id=owner_id).first():
                raise PermissionError("Workspace owner required")
            payload={"snapshot_consistent":True,"secrets_excluded":True,
                     "backup_copies_included":False,"tables":{}}
            size=128
            count=0
            for name in export_tables():
                table=Base.metadata.tables[name]
                columns=[c for c in table.c if c.name not in SECRET_COLUMNS]
                rows=[]
                stmt=select(*columns).where(_scope(table,tenant)).order_by(*table.primary_key.columns).execution_options(yield_per=100)
                for row in snapshot.execute(stmt).mappings():
                    value=_safe(dict(row))
                    size+=len(json.dumps(value,default=str,ensure_ascii=False,separators=(",",":")).encode("utf-8"))+1
                    count+=1
                    if size>max_bytes or count>max_rows:
                        raise ValueError("Snapshot exceeds bounded export limits; use paginated export")
                    rows.append(value)
                payload["tables"][name]=rows
            payload["row_count"]=count
            encoded=json.dumps(payload,default=str,ensure_ascii=False,separators=(",",":")).encode("utf-8")
            if len(encoded)>max_bytes:
                raise ValueError("Snapshot exceeds bounded export limits")
            return encoded

def delete_documents(db,tenant,ids):
    if not ids:
        return 0
    _lock(db,tenant)
    selected=select(MemoryDocument.id).where(MemoryDocument.business_id==tenant,MemoryDocument.id.in_(ids))
    chunks=select(MemoryChunk.id).where(MemoryChunk.business_id==tenant,MemoryChunk.document_id.in_(selected))
    db.execute(delete(MemoryRelevanceFeedback).where(MemoryRelevanceFeedback.business_id==tenant,MemoryRelevanceFeedback.chunk_id.in_(chunks)))
    db.execute(delete(MemoryDocumentState).where(MemoryDocumentState.business_id==tenant,MemoryDocumentState.document_id.in_(selected)))
    db.execute(delete(SemanticVector).where(SemanticVector.business_id==tenant,SemanticVector.chunk_id.in_(chunks)))
    db.execute(delete(MemoryChunk).where(MemoryChunk.business_id==tenant,MemoryChunk.document_id.in_(selected)))
    result=db.execute(delete(MemoryDocument).where(MemoryDocument.business_id==tenant,MemoryDocument.id.in_(ids)))
    return result.rowcount

def set_retention(db,tenant,days,resolved_alert_days=None,expired_session_days=None):
    values=(days,resolved_alert_days,expired_session_days)
    if any(v is not None and (isinstance(v,bool) or not isinstance(v,int) or not 30<=v<=3650) for v in values):
        raise ValueError("Retention must be disabled or 30–3650 days")
    _lock(db,tenant)
    row=db.get(DataRetentionPolicy,tenant)
    if row is None:
        row=DataRetentionPolicy(business_id=tenant)
        db.add(row)
    row.document_days,row.resolved_alert_days,row.expired_session_days=values
    row.updated_at=datetime.utcnow()
    db.commit()
    return {"document_days":days,"automatic_document_deletion_enabled":days is not None,
            "resolved_alert_days":resolved_alert_days,"expired_session_days":expired_session_days}

def apply_retention(db,tenant,now=None):
    _lock(db,tenant)
    row=db.get(DataRetentionPolicy,tenant)
    if row is None:
        return 0
    now=now or datetime.utcnow()
    count=0
    if row.document_days is not None:
        cutoff=now-timedelta(days=row.document_days)
        ids=[x[0] for x in db.query(MemoryDocument.id).filter(MemoryDocument.business_id==tenant,
                      MemoryDocument.created_at<cutoff).order_by(MemoryDocument.created_at).limit(200).all()]
        count+=delete_documents(db,tenant,ids)
    if row.resolved_alert_days is not None:
        cutoff=now-timedelta(days=row.resolved_alert_days)
        ids=[x[0] for x in db.query(AlertSnapshot.id).filter_by(business_id=tenant,is_active=False)
             .filter(AlertSnapshot.resolved_at<cutoff).order_by(AlertSnapshot.resolved_at).limit(200).all()]
        count+=db.execute(delete(AlertSnapshot).where(AlertSnapshot.business_id==tenant,AlertSnapshot.id.in_(ids))).rowcount
    if row.expired_session_days is not None:
        cutoff=now-timedelta(days=row.expired_session_days)
        ids=[x[0] for x in db.query(UserSession.id).filter_by(business_id=tenant)
             .filter(UserSession.expires_at<cutoff).order_by(UserSession.expires_at).limit(200).all()]
        count+=db.execute(delete(UserSession).where(UserSession.business_id==tenant,UserSession.id.in_(ids))).rowcount
    return count

def delete_workspace(db,user,confirmation):
    tenant=user.business_id
    if confirmation!="DELETE "+tenant:
        raise ValueError("Exact workspace deletion confirmation required")
    tenant_lifecycle_lock(db,tenant,exclusive=True)
    owner(db,user)
    _lock(db,tenant)
    counts={}
    preferred=["sync_history","semantic_vectors","memory_chunks","memory_documents",
               "side_effect_outbox","approval_requests","workflow_schedules","workflow_runs","workflow_definitions",
               "settlement_evidence","support_tickets","invoices","customers","tasks","goals","decisions",
               "user_sessions","business_memberships","users","businesses"]
    late={"user_sessions","business_memberships","users","businesses"}
    names=[n for n in preferred if n not in late]
    names += [t.name for t in Base.metadata.tables.values()
              if t.name not in names and t.name not in late and _scope(t,tenant) is not None]
    names += [n for n in preferred if n in late]
    user_ids=select(User.id).where(User.business_id==tenant)
    db.execute(delete(UserSession).where(UserSession.user_id.in_(user_ids)))
    db.execute(delete(BusinessMembership).where(BusinessMembership.user_id.in_(user_ids)))
    for name in names:
        table=Base.metadata.tables[name]
        condition=_scope(table,tenant)
        if condition is not None:
            counts[name]=db.execute(delete(table).where(condition)).rowcount
    db.commit()
    return {"status":"workspace_application_rows_deleted","deleted_counts":counts,
            "external_provider_data_deleted":False,"backup_copies_deleted":False}
