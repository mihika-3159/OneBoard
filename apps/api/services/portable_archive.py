"""Immutable paged logical snapshots and non-destructive, signed same-workspace restore.

One transaction captures the source view; durable page numbers allow download
and upload to resume without holding an MVCC transaction across requests.
Credential/security identities and derived indexes are not portable.
"""
from datetime import datetime,timedelta
import base64,hashlib,hmac,json,math,re
from sqlalchemy import select,delete,func,insert,update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.sqltypes import DateTime,Integer,Float,Boolean,String,JSON
from apps.api.core.config import settings
from apps.api.core.database import Base,scope_tenant_session,tenant_lifecycle_lock
from apps.api.core.money import ExactMoney,storage_units
from apps.api.models.operations import PortableArchive,PortableArchivePage
from apps.api.models.business import Business
from apps.api.services import data_lifecycle as lifecycle
from apps.api.services.tenant_storage import _lock

FORMAT="oneboard-portable-v1"
MAX_BYTES=256*1024*1024
MAX_ROWS=200000
MAX_PAGE=8*1024*1024
TARGET_PAGE=1024*1024
MAX_PAGES=4000
EXCLUDED=lifecycle.EXCLUDED|{"users","business_memberships","security_events","semantic_vectors","provider_credentials","provider_authorizations","tenant_resource_windows","workflow_trigger_states"}
# Parents first, including relationships enforced by migrations rather than ORM.
ORDER=("businesses","products","customers","leads","goals","projects","decisions","evidence","tasks","invoices","expenses","commitments","support_tickets",
"settlement_evidence","journal_entries","bank_statement_lines","accounting_closes","finance_forecasts","unit_economics_observations",
"memory_documents","memory_chunks","memory_document_states","memory_relevance_feedback","entity_relationships","memory_conflicts",
"council_meetings","adviser_scorecards","custom_agents","agent_runs","workflow_definitions","workflow_revisions","workflow_runs","approval_requests","workflow_schedules","workflow_events","side_effect_outbox",
"integration_accounts","sync_history","provider_connections","provider_records","provider_record_conflicts","provider_sync_jobs","provider_webhook_receipts","provider_deliveries","provider_intents",
"local_customer_imports","alert_snapshots","audit_logs","data_retention_policies")
def tables():
    available=set(lifecycle.export_tables())-EXCLUDED
    if available!=set(ORDER):raise RuntimeError("Portable table inventory requires explicit review")
    return ORDER
def encode(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False,default=str)
def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
def signing_key():
    if settings.PORTABLE_ARCHIVE_SIGNING_KEY:
        try:key=base64.b64decode(settings.PORTABLE_ARCHIVE_SIGNING_KEY,validate=True)
        except (ValueError,TypeError):raise ValueError("Invalid portable archive signing key") from None
        if len(key)!=32:raise ValueError("Invalid portable archive signing key")
        return key
    if len(settings.AUTH_SECRET_KEY)<32:raise ValueError("Portable archive signing key unavailable")
    return hmac.new(settings.AUTH_SECRET_KEY.encode(),b"oneboard:portable-archive:v1",hashlib.sha256).digest()
def signature(manifest):
    return hmac.new(signing_key(),encode({k:v for k,v in manifest.items() if k!="signature"}).encode(),hashlib.sha256).hexdigest()
def manifest_public(row):
    return {"id":row.id,"kind":row.kind,"state":row.state,"page_count":row.page_count,"row_count":row.row_count,"byte_count":row.byte_count,
            "created_at":row.created_at.isoformat()+"Z","expires_at":row.expires_at.isoformat()+"Z","manifest":row.manifest if row.state in ("ready","applied") else None}
def lookup(db,tenant,ident,kind=None):
    query=db.query(PortableArchive).filter_by(business_id=tenant,id=ident)
    if kind:query=query.filter_by(kind=kind)
    row=query.first()
    if not row or row.expires_at<=datetime.utcnow():raise ValueError("Portable archive unavailable or expired")
    return row
def discard(db,tenant,ident):
    _lock(db,tenant)
    row=lookup(db,tenant,ident)
    db.query(PortableArchivePage).filter_by(business_id=tenant,archive_id=ident).delete(synchronize_session=False)
    db.delete(row);db.commit()
    return {"deleted":True}
def admission(db,tenant,kind):
    now=datetime.utcnow()
    stale=[x[0] for x in db.query(PortableArchive.id).filter(PortableArchive.business_id==tenant,PortableArchive.expires_at<=now).all()]
    if stale:
        db.query(PortableArchivePage).filter(PortableArchivePage.business_id==tenant,PortableArchivePage.archive_id.in_(stale)).delete(synchronize_session=False)
        db.query(PortableArchive).filter(PortableArchive.business_id==tenant,PortableArchive.id.in_(stale)).delete(synchronize_session=False)
    if db.query(PortableArchive).filter_by(business_id=tenant,kind=kind).count()>=1:raise ValueError("Delete or finish existing portable archive first")
def add_page(db,row,table,records,descriptors):
    content=encode(records);size=len(content.encode())
    if size>MAX_PAGE or row.byte_count+size>MAX_BYTES or row.row_count+len(records)>MAX_ROWS or row.page_count>=MAX_PAGES:
        raise ValueError("Portable archive capacity exceeded; nothing was truncated")
    d={"number":row.page_count,"table":table,"sha256":hash_text(content),"rows":len(records),"bytes":size}
    db.add(PortableArchivePage(archive_id=row.id,page_number=d["number"],business_id=row.business_id,table_name=table,
       content=content,checksum=d["sha256"],row_count=d["rows"],byte_count=size))
    row.page_count+=1;row.row_count+=len(records);row.byte_count+=size;descriptors.append(d);db.flush()
def capture(db,user):
    tenant,actor=user.business_id,user.id;signing_key()
    bind=db.get_bind()
    # Release caller's read transaction before opening the snapshot connection.
    db.rollback()
    with bind.connect() as conn:
        if conn.dialect.name=="postgresql":conn=conn.execution_options(isolation_level="REPEATABLE READ")
        else:conn.exec_driver_sql("BEGIN IMMEDIATE")
        with Session(bind=conn,autoflush=False) as snap:
            scope_tenant_session(snap,tenant)
            tenant_lifecycle_lock(snap,tenant)
            _lock(snap,tenant)
            if not snap.query(Business.id).filter_by(id=tenant,owner_id=actor).first():raise PermissionError("Workspace owner required")
            admission(snap,tenant,"export")
            row=PortableArchive(business_id=tenant,actor_id=actor,kind="export",state="building",expires_at=datetime.utcnow()+timedelta(days=2))
            snap.add(row);snap.flush()
            descriptors=[]
            for name in tables():
                table=Base.metadata.tables[name]
                cols=[c for c in table.c if c.name not in lifecycle.SECRET_COLUMNS]
                stmt=select(*cols).where(lifecycle._scope(table,tenant)).order_by(*table.primary_key.columns).execution_options(yield_per=50)
                batch=[];size=2
                for record in snap.execute(stmt).mappings():
                    value=lifecycle._safe(dict(record))
                    n=len(encode(value).encode())+1
                    if batch and (size+n>TARGET_PAGE or len(batch)>=250):
                        add_page(snap,row,name,batch,descriptors);batch=[];size=2
                    batch.append(value);size+=n
                if batch:add_page(snap,row,name,batch,descriptors)
            manifest={"format":FORMAT,"tenant":tenant,"snapshot_id":row.id,"captured_at":row.created_at.isoformat()+"Z",
                      "tables":list(tables()),"pages":descriptors,"rows":row.row_count,"bytes":row.byte_count,
                      "secrets_excluded":True,"consistent_snapshot":True}
            manifest["signature"]=signature(manifest)
            row.manifest=manifest;row.state="ready";snap.flush()
            result=manifest_public(row)
            snap.commit()
            # SQLite explicitly opened transaction belongs to connection.
            if conn.in_transaction():conn.commit()
            return result
def download(db,tenant,ident,number):
    archive=lookup(db,tenant,ident,"export")
    if archive.state!="ready" or type(number) is not int or not 0<=number<archive.page_count:raise ValueError("Invalid archive page")
    row=db.query(PortableArchivePage).filter_by(business_id=tenant,archive_id=ident,page_number=number).one()
    if hash_text(row.content)!=row.checksum:raise ValueError("Archive page integrity failure")
    return row.content,row.checksum
def validate_manifest(tenant,manifest):
    if not isinstance(manifest,dict) or manifest.get("format")!=FORMAT or manifest.get("tenant")!=tenant or manifest.get("tables")!=list(tables()) or manifest.get("secrets_excluded") is not True or manifest.get("consistent_snapshot") is not True:
        raise ValueError("Incompatible or foreign workspace archive")
    sig=manifest.get("signature")
    if not isinstance(sig,str) or not hmac.compare_digest(sig,signature(manifest)):raise ValueError("Archive signature invalid")
    pages=manifest.get("pages")
    if not isinstance(pages,list) or not 1<=len(pages)<=MAX_PAGES:raise ValueError("Invalid archive manifest pages")
    total_rows=total_bytes=0;previous=-1
    for i,p in enumerate(pages):
        if not isinstance(p,dict) or set(p)!={"number","table","sha256","rows","bytes"} or p["number"]!=i or p["table"] not in ORDER:
            raise ValueError("Invalid archive page descriptor")
        order=ORDER.index(p["table"])
        if order<previous:raise ValueError("Invalid archive table ordering")
        previous=order
        if not isinstance(p["sha256"],str) or not re.fullmatch("[a-f0-9]{64}",p["sha256"]) or type(p["rows"]) is not int or not 1<=p["rows"]<=250 or type(p["bytes"]) is not int or not 1<=p["bytes"]<=MAX_PAGE:
            raise ValueError("Invalid archive page size or checksum")
        total_rows+=p["rows"];total_bytes+=p["bytes"]
    if not 1<=total_rows<=MAX_ROWS or not 1<=total_bytes<=MAX_BYTES or manifest.get("rows")!=total_rows or manifest.get("bytes")!=total_bytes:raise ValueError("Invalid archive totals")
    return pages
def begin_import(db,user,manifest):
    tenant=user.business_id;lifecycle.owner(db,user);pages=validate_manifest(tenant,manifest)
    _lock(db,tenant);admission(db,tenant,"import")
    row=PortableArchive(business_id=tenant,actor_id=user.id,kind="import",state="uploading",manifest=manifest,expires_at=datetime.utcnow()+timedelta(days=2))
    db.add(row);db.commit()
    return {**manifest_public(row),"expected_pages":len(pages)}
def upload(db,tenant,ident,number,content):
    _lock(db,tenant);row=lookup(db,tenant,ident,"import")
    if row.state not in ("uploading","ready"):raise ValueError("Import is not accepting pages")
    pages=validate_manifest(tenant,row.manifest)
    if type(number) is not int or not 0<=number<len(pages):raise ValueError("Invalid import page")
    descriptor=pages[number]
    if not isinstance(content,str) or len(content.encode())!=descriptor["bytes"] or hash_text(content)!=descriptor["sha256"]:raise ValueError("Page checksum or size mismatch")
    old=db.query(PortableArchivePage).filter_by(business_id=tenant,archive_id=ident,page_number=number).first()
    if old:
        if old.checksum!=descriptor["sha256"]:raise ValueError("Conflicting page")
        return {"duplicate":True,"uploaded":row.page_count,"expected":len(pages)}
    try:records=json.loads(content)
    except (ValueError,RecursionError):raise ValueError("Invalid archive page JSON") from None
    if not isinstance(records,list) or len(records)!=descriptor["rows"] or any(not isinstance(x,dict) for x in records):raise ValueError("Invalid archive page rows")
    db.add(PortableArchivePage(archive_id=ident,page_number=number,business_id=tenant,table_name=descriptor["table"],content=content,
              checksum=descriptor["sha256"],row_count=descriptor["rows"],byte_count=descriptor["bytes"]))
    row.page_count+=1;row.row_count+=descriptor["rows"];row.byte_count+=descriptor["bytes"]
    if row.page_count==len(pages):row.state="ready"
    db.commit();return {"duplicate":False,"uploaded":row.page_count,"expected":len(pages)}
def progress(db,tenant,ident):
    row=lookup(db,tenant,ident)
    return {**manifest_public(row),"received_pages":[x[0] for x in db.query(PortableArchivePage.page_number).filter_by(business_id=tenant,archive_id=ident).order_by(PortableArchivePage.page_number).all()]}
def typed(column,value):
    if value is None:
        if not column.nullable:raise ValueError("Required archive field missing")
        return None
    t=column.type
    if isinstance(t,ExactMoney):storage_units(value);return value
    if isinstance(t,DateTime):
        if not isinstance(value,str):raise ValueError("Invalid archive timestamp")
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is not None:raise ValueError("Archive timestamp must be UTC-naive")
        return parsed
    if isinstance(t,Boolean):
        if type(value) is not bool:raise ValueError("Invalid archive boolean")
    elif isinstance(t,Integer):
        if type(value) is not int or not -(2**63)<=value<2**63:raise ValueError("Invalid archive integer")
    elif isinstance(t,Float):
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError("Invalid archive number")
    elif isinstance(t,String):
        if not isinstance(value,str) or (t.length and len(value)>t.length) or "\x00" in value:raise ValueError("Invalid archive string")
    elif isinstance(t,JSON):
        if len(encode(value).encode())>MAX_PAGE:raise ValueError("Archive JSON exceeds limit")
    else:raise ValueError("Unsupported archive column type")
    return value
def sanitized(name,row):
    # Never resume external effects or obsolete claims from backup.
    row=dict(row)
    if name=="businesses":return row
    if name=="memory_documents":row["file_path"]=None
    if name=="memory_document_states":row.update(status="pending" if row.get("active") else "superseded",indexed_count=0,attempts=0,model_key=None,lease_until=0,next_attempt_at=0,claim_token=None,error=None)
    if name=="integration_accounts":row.update(status="disconnected",configuration={},granted_scopes=[])
    if name=="provider_connections":row.update(state="disconnected",scopes=[],encrypted_credentials=None,expires_at=None,checkpoint=None,last_error="restored_reauthorization_required",last_sync=None)
    if name=="provider_sync_jobs" and row.get("state") in ("queued","retry"):row["state"]="cancelled"
    if name=="provider_deliveries" and row.get("state") in ("approved","dispatching"):row["state"]="cancelled" if row["state"]=="approved" else "uncertain"
    if name=="provider_intents" and row.get("state")=="staged_no_dispatch":row["state"]="cancelled_local"
    if name=="workflow_definitions":row.update(is_active=False,trigger_type="manual",trigger_config={})
    if name=="workflow_schedules":row.update(enabled=False)
    if name=="workflow_events":
        if row.get("status") in ("queued","running"):row["status"]="dead_letter";row["error"]="Restored event requires explicit review"
        row.update(owner_token=None,lease_until=0)
    if name=="workflow_runs" and row.get("status") not in ("completed","failed","cancelled"):row.update(status="cancelled",error_message="Restored historical run; no automatic execution")
    if name=="approval_requests" and row.get("status") in ("pending","approved"):row.update(status="rejected",reviewer_notes="Restored historical approval; no action authorized")
    if name=="side_effect_outbox" and row.get("state")=="pending":row["state"]="cancelled"
    if name=="custom_agents":row["status"]="paused"
    if name=="agent_runs":
        if row.get("status") not in ("completed","failed","cancelled","expired"):row["status"]="cancelled"
        row.update(lease_owner=None,lease_until=None)
    if name=="council_meetings" and row.get("stage") not in ("completed","executed"):row["stage"]="failed"
    if name=="data_retention_policies":
        for k in row:
            if k.endswith("_days"):row[k]=None
    return row
def restore(db,user,ident,confirmation):
    tenant=user.business_id
    if confirmation!="RESTORE "+tenant:raise ValueError("Exact restoration confirmation required")
    tenant_lifecycle_lock(db,tenant,exclusive=True);lifecycle.owner(db,user);_lock(db,tenant)
    archive=lookup(db,tenant,ident,"import")
    if archive.state=="applied":return {"status":"already_applied","inserted":0,"unchanged":0}
    if archive.state!="ready":raise ValueError("Upload every archive page before restoration")
    descriptors=validate_manifest(tenant,archive.manifest)
    inserted=unchanged=0
    try:
        for d in descriptors:
            page=db.query(PortableArchivePage).filter_by(business_id=tenant,archive_id=ident,page_number=d["number"]).one_or_none()
            if not page or page.table_name!=d["table"] or hash_text(page.content)!=d["sha256"]:raise ValueError("Archive page integrity failure")
            name=d["table"];table=Base.metadata.tables[name];columns=[c for c in table.c if c.name not in lifecycle.SECRET_COLUMNS]
            for value in json.loads(page.content):
                if set(value)!={c.name for c in columns}:raise ValueError("Archive schema mismatch")
                if name=="businesses":
                    if value["id"]!=tenant:raise ValueError("Foreign business row")
                    # Never change workspace ownership; update only profile fields
                    # if the destination profile already matches the snapshot.
                    existing=db.execute(select(*columns).where(table.c.id==tenant)).mappings().one()
                    if encode(lifecycle._safe(dict(existing)))!=encode(value):raise ValueError("Business profile differs; restore requires matching workspace profile")
                    unchanged+=1;continue
                if name=="sync_history":
                    from apps.api.models.integrations import IntegrationAccount
                    if not db.query(IntegrationAccount.id).filter_by(id=value["integration_id"],business_id=tenant).first():raise ValueError("Foreign integration history")
                elif value.get("business_id")!=tenant:raise ValueError("Foreign archive row")
                original={c.name:typed(c,value[c.name]) for c in columns}
                new=sanitized(name,original)
                where=[c==new[c.name] for c in table.primary_key.columns]
                existing=db.execute(select(*columns).where(*where,lifecycle._scope(table,tenant))).mappings().one_or_none()
                if existing is not None:
                    stored=encode(lifecycle._safe(dict(existing)))
                    if stored not in (encode(value),encode(lifecycle._safe({k:v for k,v in new.items() if k in value}))):
                        raise ValueError("Existing application record differs; restore never overwrites")
                    unchanged+=1;continue
                db.execute(insert(table).values(**new));inserted+=1
        archive.state="applied";db.commit()
    except (IntegrityError,ValueError,TypeError,KeyError,OverflowError) as exc:
        db.rollback()
        raise ValueError("Restoration rejected atomically: "+(str(exc) if isinstance(exc,ValueError) else "schema or ownership conflict")) from None
    return {"status":"applied","inserted":inserted,"unchanged":unchanged,"external_actions_replayed":False}
