"""Bounded expiry cleanup, keyset browsing, and tenant-local query samples."""
from datetime import datetime,timedelta
import base64,hashlib,hmac,json,math,time
from sqlalchemy import select,delete,update,func,and_,or_
from apps.api.core.database import Base
from apps.api.models.business import LoginThrottleState,AccountSecurity
from apps.api.models.operations import (PortableArchive,PortableArchivePage,ProviderAuthorization,TenantResourceWindow,ScheduledJobLease,DatabasePerformanceSample)
from apps.api.services.tenant_storage import _lock,ROW_LIMITS
from apps.api.services import data_lifecycle as lifecycle
from apps.api.core.config import settings

def cleanup_global(db,now=None):
    now=time.time() if now is None else now
    # Retain throttle windows for at least 24h (maximum allowed lockout).
    # The conditional delete rechecks the clock under concurrent row locks.
    cutoff=now-86400
    ids=[x[0] for x in db.query(LoginThrottleState.identifier_hash).filter(LoginThrottleState.window_started_at<cutoff).order_by(LoginThrottleState.window_started_at,LoginThrottleState.identifier_hash).limit(1000)]
    count=db.execute(delete(LoginThrottleState).where(LoginThrottleState.identifier_hash.in_(ids),LoginThrottleState.window_started_at<cutoff)).rowcount
    # Do not delete job coordination identities or active leases. Clear only
    # expired owner tokens after generous grace; claim_job remains authoritative.
    count+=db.execute(update(ScheduledJobLease).where(ScheduledJobLease.owner_token.is_not(None),ScheduledJobLease.lease_until<now-86400).values(owner_token=None,lease_until=0)).rowcount
    db.commit();return count

def cleanup_tenant(db,tenant,now=None):
    now=now or datetime.utcnow();_lock(db,tenant)
    from datetime import timezone
    epoch=now.replace(tzinfo=timezone.utc).timestamp()
    count=db.execute(delete(TenantResourceWindow).where(TenantResourceWindow.business_id==tenant,TenantResourceWindow.window_started_at<epoch-86400)).rowcount
    ids=[x[0] for x in db.query(ProviderAuthorization.state_hash).filter(ProviderAuthorization.business_id==tenant,ProviderAuthorization.expires_at<=now).order_by(ProviderAuthorization.expires_at).limit(200)]
    count+=db.execute(delete(ProviderAuthorization).where(ProviderAuthorization.business_id==tenant,ProviderAuthorization.state_hash.in_(ids))).rowcount
    ids=[x[0] for x in db.query(PortableArchive.id).filter(PortableArchive.business_id==tenant,PortableArchive.expires_at<=now).order_by(PortableArchive.expires_at).limit(10)]
    count+=db.execute(delete(PortableArchivePage).where(PortableArchivePage.business_id==tenant,PortableArchivePage.archive_id.in_(ids))).rowcount
    count+=db.execute(delete(PortableArchive).where(PortableArchive.business_id==tenant,PortableArchive.id.in_(ids))).rowcount
    count+=db.execute(update(AccountSecurity).where(AccountSecurity.business_id==tenant,AccountSecurity.pending_mfa_expires<=now).values(pending_mfa_ciphertext=None,pending_mfa_expires=None)).rowcount
    count+=db.execute(update(AccountSecurity).where(AccountSecurity.business_id==tenant,AccountSecurity.email_challenge_expires<=now).values(email_challenge_hash=None,email_challenge_ciphertext=None,email_challenge_expires=None)).rowcount
    db.commit();return count

COLLECTIONS={
 "customers":"customers","leads":"leads","tasks":"tasks","goals":"goals","projects":"projects","invoices":"invoices",
 "expenses":"expenses","commitments":"commitments","support-tickets":"support_tickets","workflow-runs":"workflow_runs",
 "agent-runs":"agent_runs","workflow-events":"workflow_events","decisions":"decisions","memory-documents":"memory_documents",
 "journal":"journal_entries","bank-statements":"bank_statement_lines","forecasts":"finance_forecasts",
 "provider-records":"provider_records","provider-syncs":"provider_sync_jobs","provider-deliveries":"provider_deliveries",
 "audit":"audit_logs","approvals":"approval_requests","outbox":"side_effect_outbox","conflicts":"memory_conflicts",
}
def cursor_key():
    if len(settings.AUTH_SECRET_KEY)<32:raise ValueError("Cursor signing key unavailable")
    return hmac.new(settings.AUTH_SECRET_KEY.encode(),b"oneboard:collection-cursor:v1",hashlib.sha256).digest()
def make_cursor(tenant,collection,last):
    raw=json.dumps([tenant,collection,last],separators=(",",":")).encode()
    sig=hmac.new(cursor_key(),raw,hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig+raw).decode().rstrip("=")
def read_cursor(tenant,collection,cursor):
    if not isinstance(cursor,str) or not 1<=len(cursor)<=512:raise ValueError("Invalid collection cursor")
    try:
        raw=base64.b64decode(cursor+"="*(-len(cursor)%4),altchars=b"-_",validate=True)
        if not hmac.compare_digest(raw[:32],hmac.new(cursor_key(),raw[32:],hashlib.sha256).digest()):raise ValueError()
        owner,name,last=json.loads(raw[32:])
        if owner!=tenant or name!=collection or not isinstance(last,str) or not 1<=len(last)<=36:raise ValueError()
        return last
    except (TypeError,ValueError,UnicodeError):raise ValueError("Invalid collection cursor") from None

def collection_page(db,tenant,collection,cursor=None,limit=50):
    if collection not in COLLECTIONS or type(limit) is not int or not 1<=limit<=100:raise ValueError("Invalid collection or page size")
    table=Base.metadata.tables[COLLECTIONS[collection]]
    cols=[c for c in table.c if c.name not in lifecycle.SECRET_COLUMNS and c.name not in ("raw_content","file_path","embedding","owner_token","lease_owner","claim_token")]
    query=select(*cols).where(table.c.business_id==tenant)
    if cursor:query=query.where(table.c.id>read_cursor(tenant,collection,cursor))
    start=time.perf_counter()
    rows=db.execute(query.order_by(table.c.id).limit(limit+1)).mappings().all()
    elapsed=(time.perf_counter()-start)*1000
    # Only bounded result rows are observed, not planner rows scanned.
    return {"collection":collection,"records":[lifecycle._safe(dict(x)) for x in rows[:limit]],
        "next_cursor":make_cursor(tenant,collection,rows[limit-1]["id"]) if len(rows)>limit else None,
        "snapshot_consistent":False,"elapsed_ms":round(elapsed,3),"returned_rows":min(len(rows),limit)}

def sample(db,tenant):
    # Stable repeatable bounded workload, never exposes SQL or other tenants.
    _lock(db,tenant)
    latest=db.query(DatabasePerformanceSample.created_at).filter_by(business_id=tenant).order_by(DatabasePerformanceSample.created_at.desc()).first()
    now=datetime.utcnow()
    if latest and latest[0]>now-timedelta(hours=1):db.rollback();return None
    for collection in ("customers","workflow-runs","agent-runs","journal","provider-records"):
        result=collection_page(db,tenant,collection,limit=100)
        db.add(DatabasePerformanceSample(business_id=tenant,workload=collection,rows_examined=result["returned_rows"],elapsed_ms=result["elapsed_ms"],created_at=now))
    db.flush()
    # Hard cap protects even tenants with retention disabled.
    stale=[x[0] for x in db.query(DatabasePerformanceSample.id).filter_by(business_id=tenant).order_by(DatabasePerformanceSample.created_at.desc(),DatabasePerformanceSample.id.desc()).offset(1000).limit(200)]
    if stale:db.execute(delete(DatabasePerformanceSample).where(DatabasePerformanceSample.business_id==tenant,DatabasePerformanceSample.id.in_(stale)))
    db.commit();return True
def report(db,tenant):
    rows=db.query(DatabasePerformanceSample).filter_by(business_id=tenant).order_by(DatabasePerformanceSample.created_at.desc(),DatabasePerformanceSample.id.desc()).limit(1000).all()
    out={}
    for workload in sorted({r.workload for r in rows}):
        values=[r for r in rows if r.workload==workload]
        durations=sorted(r.elapsed_ms for r in values)
        median=durations[len(durations)//2];p95=durations[max(0,math.ceil(.95*len(durations))-1)]
        recent=values[0];baseline=values[1:25]
        typical=sorted(r.elapsed_ms for r in baseline)[len(baseline)//2] if baseline else None
        out[workload]={"samples":len(values),"median_ms":round(median,3),"p95_ms":round(p95,3),"latest_ms":recent.elapsed_ms,
           "latest_rows":recent.rows_examined,"regression":bool(typical is not None and recent.elapsed_ms>max(50,typical*3))}
    return {"workloads":out,"threshold":"latest > max(50 ms, 3x prior median)","scope":"tenant-local bounded read probes, not full DB capacity certification"}
def quota_report(db,tenant):
    result={}
    for name,limit in sorted(ROW_LIMITS.items()):
        table=Base.metadata.tables[name]
        used=db.execute(select(func.count()).select_from(table).where(table.c.business_id==tenant)).scalar_one()
        result[name]={"used":used,"limit":limit}
    return result
