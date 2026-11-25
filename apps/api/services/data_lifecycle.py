"""Owner-only export/deletion and opt-in document retention."""
from datetime import datetime,timedelta
import math
from decimal import Decimal
from sqlalchemy import select,delete,func
from apps.api.core.database import Base,tenant_lifecycle_lock
from apps.api.models.business import Business,User,BusinessMembership,UserSession
from apps.api.models.integrations import IntegrationAccount
from apps.api.models.memory import MemoryDocument,MemoryChunk,MemoryDocumentState,MemoryRelevanceFeedback
from apps.api.models.operations import SemanticVector,DataRetentionPolicy,AlertSnapshot
from apps.api.services.tenant_storage import _lock

EXCLUDED={"login_throttle_states","scheduled_job_leases","user_sessions","scheduler_cursors","account_security","portable_archives","portable_archive_pages","database_performance_samples","provider_authorizations"}
SECRET_COLUMNS={"password_hash","hashed_password","api_key","token","token_hash",
                "encrypted_token","encrypted_credentials","encrypted_verifier","state_hash","checkpoint","claim_token","owner_token","lease_owner","configuration","vector","embedding","mfa_ciphertext","pending_mfa_ciphertext","recovery_hashes","email_challenge_hash","email_challenge_ciphertext"}
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

RETENTION_FIELDS=("document_days","resolved_alert_days","expired_session_days","completed_sync_days","resolved_conflict_days","completed_draft_days","performance_sample_days")

def set_retention(db,tenant,days,resolved_alert_days=None,expired_session_days=None,completed_sync_days=None,resolved_conflict_days=None,completed_draft_days=None,performance_sample_days=None):
    values=(days,resolved_alert_days,expired_session_days,completed_sync_days,resolved_conflict_days,completed_draft_days,performance_sample_days)
    if any(v is not None and (isinstance(v,bool) or not isinstance(v,int) or not 30<=v<=3650) for v in values):
        raise ValueError("Retention must be disabled or 30–3650 days")
    _lock(db,tenant)
    row=db.get(DataRetentionPolicy,tenant)
    if row is None:
        row=DataRetentionPolicy(business_id=tenant)
        db.add(row)
    for field,value in zip(RETENTION_FIELDS,values):setattr(row,field,value)
    row.updated_at=datetime.utcnow()
    db.commit()
    return {**dict(zip(RETENTION_FIELDS,values)),"automatic_document_deletion_enabled":days is not None}

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
    from apps.api.models.operations import ProviderSyncJob,ProviderRecordConflict,SideEffectOutbox,DatabasePerformanceSample
    from sqlalchemy import update
    # Preserve idempotency keys, conflict hashes and action receipts. Redact
    # expendable payload/diagnostics, never delete a deduplication tombstone.
    for field,model,stamp,condition,values in (
        ("completed_sync_days",ProviderSyncJob,ProviderSyncJob.finished_at,ProviderSyncJob.state.in_(["succeeded","failed","cancelled"]),{"error_code":None}),
        ("resolved_conflict_days",ProviderRecordConflict,ProviderRecordConflict.created_at,ProviderRecordConflict.state.in_(["keep_recorded","accept_incoming"]),{"incoming_payload":{}}),
        ("completed_draft_days",SideEffectOutbox,SideEffectOutbox.processed_at,SideEffectOutbox.state=="draft_ready",{"payload":{}}),
    ):
        days=getattr(row,field)
        if days is None:continue
        cutoff=now-timedelta(days=days)
        ids=[x[0] for x in db.query(model.id).filter(model.business_id==tenant,stamp<cutoff,condition,model.retention_redacted_at.is_(None)).order_by(stamp,model.id).limit(200)]
        count+=db.execute(update(model).where(model.business_id==tenant,model.id.in_(ids)).values(**values,retention_redacted_at=now)).rowcount
    if row.performance_sample_days is not None:
        cutoff=now-timedelta(days=row.performance_sample_days)
        ids=[x[0] for x in db.query(DatabasePerformanceSample.id).filter(DatabasePerformanceSample.business_id==tenant,DatabasePerformanceSample.created_at<cutoff).order_by(DatabasePerformanceSample.created_at,DatabasePerformanceSample.id).limit(200)]
        count+=db.execute(delete(DatabasePerformanceSample).where(DatabasePerformanceSample.business_id==tenant,DatabasePerformanceSample.id.in_(ids))).rowcount
    return count

def delete_workspace(db,user,confirmation):
    tenant=user.business_id
    if confirmation!="DELETE "+tenant:
        raise ValueError("Exact workspace deletion confirmation required")
    tenant_lifecycle_lock(db,tenant,exclusive=True)
    owner(db,user)
    _lock(db,tenant)
    counts={}
    # Keep parents alive until their indirect children have been deleted.
    # The explicit order reflects both ORM and migration-only composite FKs.
    scoped={t.name for t in Base.metadata.tables.values() if _scope(t,tenant) is not None}
    global_tables={"login_throttle_states","scheduled_job_leases","scheduler_cursors"}
    unknown=set(Base.metadata.tables)-scoped-global_tables
    if unknown:raise RuntimeError("Unclassified application ownership: "+", ".join(sorted(unknown)))
    early=["portable_archive_pages","sync_history","semantic_vectors","memory_relevance_feedback","memory_document_states","memory_chunks","memory_documents",
           "side_effect_outbox","approval_requests","workflow_schedules","workflow_events","workflow_trigger_states","workflow_revisions","workflow_runs","workflow_definitions",
           "bank_statement_lines","unit_economics_observations","finance_forecasts","accounting_closes","journal_entries","settlement_evidence","support_tickets","invoices","customers","tasks","goals","decisions",
           "provider_authorizations","provider_sync_jobs","provider_record_conflicts","provider_webhook_receipts","provider_deliveries","provider_records","provider_connections","portable_archives"]
    late=["account_security","user_sessions","business_memberships","users","businesses"]
    names=[n for n in early if n in scoped]+sorted(scoped-set(early)-set(late))+[n for n in late if n in scoped]
    integration_ids=[x[0] for x in db.query(IntegrationAccount.id).filter_by(business_id=tenant)]
    user_ids=select(User.id).where(User.business_id==tenant)
    # Cross-workspace memberships of deleted users are handled by the actual
    # FK cascade, even when row-level policy hides them from the runtime.
    db.execute(delete(UserSession).where(UserSession.user_id.in_(user_ids)))
    db.execute(delete(BusinessMembership).where(BusinessMembership.user_id.in_(user_ids)))
    for name in names:
        table=Base.metadata.tables[name]
        condition=table.c.integration_id.in_(integration_ids) if name=="sync_history" else _scope(table,tenant)
        counts[name]=db.execute(delete(table).where(condition)).rowcount
    db.flush()
    # Verify in the same transaction, before success is visible. The scoped
    # session still has its signed tenant context even after business deletion.
    remaining={}
    for name in names:
        table=Base.metadata.tables[name]
        condition=table.c.integration_id.in_(integration_ids) if name=="sync_history" else _scope(table,tenant)
        count=db.execute(select(func.count()).select_from(table).where(condition)).scalar_one()
        if count:remaining[name]=count
    if remaining:raise RuntimeError("Incomplete workspace deletion")
    db.commit()
    return {"status":"workspace_application_rows_deleted","deleted_counts":counts,"verified_remaining_rows":0,
            "external_provider_data_deleted":False,"backup_copies_deleted":False}
