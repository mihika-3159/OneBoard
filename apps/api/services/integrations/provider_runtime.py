"""OAuth lifecycle, durable incremental sync, conflicts and delivery reconciliation."""
from datetime import datetime,timedelta
import base64,hashlib,hmac,json,re,secrets
from apps.api.models.operations import (ProviderConnection,ProviderAuthorization,ProviderSyncJob,ProviderRecord,ProviderRecordConflict,ProviderWebhookReceipt,ProviderDelivery)
from apps.api.services.tenant_storage import _lock
from apps.api.services.integrations import provider_crypto as crypto
from apps.api.services.integrations.provider_transport import CAPABILITIES,ProviderFailure,scopes_valid,adapter_for

def now():return datetime.utcnow()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def bounded_string(value,limit):
    if not isinstance(value,str) or not 1<=len(value)<=limit or any(ord(x)<32 for x in value):raise ValueError("Invalid provider field")
    return value
def key(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}",value):raise ValueError("Invalid request key")
    return value
def credential_purpose(row):
    if not row.adapter_fingerprint:raise ValueError("Missing adapter identity")
    return "oauth:"+row.adapter_fingerprint

def json_payload(value,limit=16384):
    if not isinstance(value,dict):raise ValueError("Provider payload must be an object")
    try:
        forbidden={"access_token","refresh_token","client_secret","password","authorization","api_key","private_key","encrypted_credentials","token"}
        def inspect(node,depth=0):
            if depth>12:raise ValueError()
            if isinstance(node,dict):
                if any(not isinstance(k,str) or k.lower() in forbidden for k in node):raise ValueError()
                for v in node.values():inspect(v,depth+1)
            elif isinstance(node,list):
                for v in node:inspect(v,depth+1)
        inspect(value)
        encoded=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
        if len(encoded)>limit:raise ValueError()
    except (ValueError,TypeError,RecursionError,UnicodeError):raise ValueError("Invalid or oversized provider payload") from None
    return value
def connection(db,tenant,provider,create=False):
    if provider not in CAPABILITIES:raise ValueError("Unknown provider")
    row=db.query(ProviderConnection).filter_by(business_id=tenant,provider=provider).first()
    if row is None and create:
        row=ProviderConnection(business_id=tenant,provider=provider,state="disconnected")
        db.add(row);db.flush()
    if row is None:raise ValueError("Provider connection unavailable")
    return row
def by_id(db,tenant,ident):
    row=db.query(ProviderConnection).filter_by(business_id=tenant,id=ident).first()
    if not row:raise ValueError("Provider connection unavailable")
    return row
def public(row):
    return {"id":row.id,"provider":row.provider,"state":row.state,"scopes":row.scopes,
            "expires_at":row.expires_at.isoformat()+"Z" if row.expires_at else None,
            "remote_account":row.remote_account,"last_sync":row.last_sync.isoformat()+"Z" if row.last_sync else None,
            "checkpoint_present":row.checkpoint is not None,"last_error":row.last_error,
            "credential_present":bool(row.encrypted_credentials),"generation":row.generation,
            "external_adapter_configured":True}
def invalidate_jobs(db,row):
    db.query(ProviderSyncJob).filter(ProviderSyncJob.business_id==row.business_id,ProviderSyncJob.connection_id==row.id,
      ProviderSyncJob.state.in_(["queued","retry"])).update({"state":"cancelled","finished_at":now()},synchronize_session=False)
    db.query(ProviderDelivery).filter_by(business_id=row.business_id,connection_id=row.id,state="approved").update({"state":"cancelled","updated_at":now()},synchronize_session=False)
def start_authorization(db,tenant,actor,provider,scopes):
    scopes=scopes_valid(provider,scopes)
    adapter=adapter_for(provider);crypto.keyring()
    if not set(scopes)<=adapter.allowed_scopes:raise ValueError("Scope unavailable for selected adapter")
    _lock(db,tenant)
    row=connection(db,tenant,provider,True)
    if row.state=="connected":raise ValueError("Disconnect before authorizing again")
    db.query(ProviderAuthorization).filter(ProviderAuthorization.business_id==tenant,ProviderAuthorization.expires_at<=now()).delete(synchronize_session=False)
    if db.query(ProviderAuthorization).filter_by(business_id=tenant).count()>=50:raise ValueError("Authorization attempt capacity reached")
    if row.adapter_fingerprint and row.adapter_fingerprint!=adapter.fingerprint and row.remote_account:
        raise ValueError("Adapter identity changed; existing connection cannot be reused")
    row.adapter_fingerprint=adapter.fingerprint
    row.generation+=1;row.state="authorizing";row.last_error=None;row.updated_at=now()
    invalidate_jobs(db,row)
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
    state_hash=hashlib.sha256(state.encode()).hexdigest()
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    auth=ProviderAuthorization(state_hash=state_hash,business_id=tenant,connection_id=row.id,actor_id=actor,
      generation=row.generation,scopes=scopes,encrypted_verifier=crypto.seal(verifier,tenant,state_hash,"pkce"),expires_at=now()+timedelta(minutes=10))
    db.add(auth);db.commit()
    return {"authorization_url":adapter.authorization_url(state,challenge,scopes),"expires_in":600,"provider":provider}

def grant(response,provider,requested,previous_refresh=None):
    if not isinstance(response,dict) or str(response.get("token_type","")).lower()!="bearer":raise ValueError("Invalid OAuth token type")
    access=bounded_string(response.get("access_token"),4096)
    refresh=response.get("refresh_token",previous_refresh)
    if refresh is not None:refresh=bounded_string(refresh,4096)
    raw=response.get("scope")
    granted=scopes_valid(provider,raw.split() if isinstance(raw,str) else raw)
    if set(granted)!=set(requested):raise ValueError("Provider grant does not match requested scopes")
    seconds=response.get("expires_in")
    if type(seconds) is not int or not 30<=seconds<=86400*365:raise ValueError("Invalid provider expiry")
    return {"access_token":access,"refresh_token":refresh},granted,now()+timedelta(seconds=seconds)

def complete_authorization(db,tenant,actor,state,code=None,denied=False):
    if not isinstance(state,str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}",state):raise ValueError("Invalid authorization state")
    state_hash=hashlib.sha256(state.encode()).hexdigest()
    _lock(db,tenant)
    auth=db.query(ProviderAuthorization).filter_by(business_id=tenant,state_hash=state_hash,actor_id=actor).first()
    if not auth or auth.consumed_at or auth.expires_at<=now():raise ValueError("Authorization expired or already used")
    row=by_id(db,tenant,auth.connection_id)
    if row.generation!=auth.generation or row.state!="authorizing":raise ValueError("Authorization superseded")
    verifier=crypto.unseal(auth.encrypted_verifier,tenant,state_hash,"pkce")
    ident=row.id;generation=row.generation;provider=row.provider;requested=list(auth.scopes)
    auth.consumed_at=now();auth.encrypted_verifier="consumed";db.commit()
    _lock(db,tenant);row=by_id(db,tenant,ident)
    if row.generation!=generation or row.state!="authorizing":raise ValueError("Authorization superseded")
    try:
        if denied:raise ValueError("Authorization denied")
        code=bounded_string(code,4096)
        adapter=adapter_for(provider)
        if adapter.fingerprint!=row.adapter_fingerprint:raise ValueError("Adapter identity changed")
        credentials,scopes,expiry=grant(adapter.exchange(code,verifier),provider,requested)
        identity=adapter.identity(credentials["access_token"])
        account=bounded_string(identity.get("account_id"),255)
        if row.remote_account and row.remote_account!=account:raise ValueError("Different remote account requires a separate workspace")
        row.remote_account=account;row.scopes=scopes
        row.encrypted_credentials=crypto.seal(credentials,tenant,row.id,credential_purpose(row))
        row.expires_at=expiry;row.state="connected";row.last_error=None
    except (ValueError,ProviderFailure):
        row.state="auth_required";row.encrypted_credentials=None;row.expires_at=None;row.scopes=[]
        row.last_error="authorization_failed";row.updated_at=now();db.commit()
        raise ValueError("Provider authorization failed; reconnect") from None
    row.updated_at=now();db.commit();return public(row)

def credentials(db,row,adapter):
    if adapter.fingerprint!=row.adapter_fingerprint:raise ProviderFailure("adapter_identity_changed")
    if row.state!="connected" or not row.encrypted_credentials or not row.expires_at:raise ProviderFailure("auth_required")
    try:value=crypto.unseal(row.encrypted_credentials,row.business_id,row.id,credential_purpose(row))
    except ValueError:raise ProviderFailure("credential_decryption_failed") from None
    if row.expires_at>now()+timedelta(seconds=30):return value["access_token"]
    if not value.get("refresh_token"):raise ProviderFailure("refresh_required")
    # A refresh response can rotate the token. If its outcome is uncertain,
    # never replay the old token automatically: require reauthorization.
    try:
        updated,scopes,expiry=grant(adapter.refresh(value["refresh_token"]),row.provider,row.scopes,value["refresh_token"])
        if bounded_string(adapter.identity(updated["access_token"]).get("account_id"),255)!=row.remote_account:raise ValueError()
        row.encrypted_credentials=crypto.seal(updated,row.business_id,row.id,credential_purpose(row));row.expires_at=expiry;row.updated_at=now()
        db.flush();return updated["access_token"]
    except (ValueError,ProviderFailure):raise ProviderFailure("refresh_uncertain_reauthorize") from None

def rotate_keys(db,tenant):
    _lock(db,tenant);count=0
    for row in db.query(ProviderConnection).filter_by(business_id=tenant).all():
        if row.encrypted_credentials:
            old=row.encrypted_credentials;row.encrypted_credentials=crypto.rotate(old,tenant,row.id,credential_purpose(row));count+=old!=row.encrypted_credentials
    for row in db.query(ProviderAuthorization).filter(ProviderAuthorization.business_id==tenant,ProviderAuthorization.consumed_at.is_(None),ProviderAuthorization.expires_at>now()).all():
        old=row.encrypted_verifier;row.encrypted_verifier=crypto.rotate(old,tenant,row.state_hash,"pkce");count+=old!=row.encrypted_verifier
    from apps.api.models.operations import ProviderCredential
    from apps.api.services.provider_staging import decrypt_stored_token,encrypt_token
    for row in db.query(ProviderCredential).filter_by(business_id=tenant).all():
        if not row.encrypted_token.startswith("v2:"+crypto.keyring()[0]+"."):
            try:value=decrypt_stored_token(row)
            except Exception:raise ValueError("Legacy credential cannot be decrypted") from None
            row.encrypted_token=encrypt_token(tenant,row.provider,row.scopes,row.expires_at,value);count+=1
    db.commit();return {"rotated":count,"active_key_id":crypto.keyring()[0]}

def disconnect(db,tenant,provider):
    _lock(db,tenant);row=connection(db,tenant,provider)
    remote=False
    if row.encrypted_credentials:
        try:
            value=crypto.unseal(row.encrypted_credentials,tenant,row.id,credential_purpose(row))
            adapter=adapter_for(provider)
            if adapter.fingerprint!=row.adapter_fingerprint:raise ValueError("Adapter identity changed")
            remote=adapter.revoke_all(value,row.remote_account)
        except (ValueError,ProviderFailure):remote=False
    row.generation+=1;row.state="disconnected";row.encrypted_credentials=None;row.expires_at=None;row.scopes=[]
    row.last_error=None if remote else "remote_revocation_unconfirmed";row.updated_at=now()
    invalidate_jobs(db,row)
    db.query(ProviderAuthorization).filter_by(business_id=tenant,connection_id=row.id).delete()
    db.commit()
    return {"local_disconnected":True,"remote_revocation_confirmed":remote,"provider":provider}

def sync_public(job):
    return {"id":job.id,"state":job.state,"pages":job.pages,"imported":job.imported,"duplicates":job.duplicates,"conflicts":job.conflicts,
            "attempts":job.attempts,"error_code":job.error_code,"next_attempt":job.next_attempt.isoformat()+"Z","created_at":job.created_at.isoformat()+"Z",
            "finished_at":job.finished_at.isoformat()+"Z" if job.finished_at else None}

def enqueue(db,tenant,provider,request_key,commit=True):
    key(request_key);_lock(db,tenant);row=connection(db,tenant,provider)
    old=db.query(ProviderSyncJob).filter_by(business_id=tenant,connection_id=row.id,request_key=request_key).first()
    if old:return old
    if row.state!="connected" or not any(s.endswith(".read") for s in row.scopes):raise ValueError("Connected read scope required")
    if db.query(ProviderSyncJob).filter_by(business_id=tenant).count()>=2000:raise ValueError("Sync history capacity reached")
    job=ProviderSyncJob(business_id=tenant,connection_id=row.id,generation=row.generation,request_key=request_key)
    db.add(job);db.flush()
    if commit:db.commit()
    return job

def normalize_page(page):
    if not isinstance(page,dict) or not isinstance(page.get("records"),list) or len(page["records"])>100 or type(page.get("has_more")) is not bool:raise ValueError("Invalid provider page")
    cursor=page.get("next_cursor")
    if cursor is not None:bounded_string(cursor,2048)
    if (page["has_more"] or page["records"]) and cursor is None:raise ValueError("Missing incremental checkpoint")
    out=[]
    for value in page["records"]:
        if not isinstance(value,dict):raise ValueError("Invalid provider record")
        ident=bounded_string(value.get("id"),255);revision=bounded_string(value.get("revision"),128)
        payload=json_payload(value.get("payload"));out.append((ident,revision,payload,digest([revision,payload])))
    return out,cursor,page["has_more"]

def ingest(db,row,records):
    imported=duplicates=conflicts=0
    for ident,revision,payload,checksum in records:
        old=db.query(ProviderRecord).filter_by(business_id=row.business_id,connection_id=row.id,remote_id=ident).first()
        if not old:
            if db.query(ProviderRecord).filter_by(business_id=row.business_id).count()>=20000:raise ValueError("Provider record capacity reached")
            db.add(ProviderRecord(business_id=row.business_id,connection_id=row.id,remote_id=ident,revision=revision,payload=payload,payload_hash=checksum));db.flush();imported+=1
        elif old.payload_hash==checksum:duplicates+=1
        else:
            existing=db.query(ProviderRecordConflict).filter_by(business_id=row.business_id,record_id=old.id,incoming_hash=checksum).first()
            if existing:duplicates+=1;continue
            if db.query(ProviderRecordConflict).filter_by(business_id=row.business_id).count()>=5000:raise ValueError("Provider conflict capacity reached")
            db.add(ProviderRecordConflict(business_id=row.business_id,connection_id=row.id,record_id=old.id,incoming_revision=revision,incoming_payload=payload,incoming_hash=checksum));db.flush();conflicts+=1
    return imported,duplicates,conflicts

def resolve_conflict(db,tenant,ident,choice):
    if choice not in ("keep_recorded","accept_incoming"):raise ValueError("Invalid conflict resolution")
    _lock(db,tenant)
    conflict=db.query(ProviderRecordConflict).filter_by(business_id=tenant,id=ident).first()
    if not conflict or conflict.state!="pending":raise ValueError("Pending conflict unavailable")
    record=db.query(ProviderRecord).filter_by(business_id=tenant,id=conflict.record_id,connection_id=conflict.connection_id).first()
    if not record:raise ValueError("Record unavailable")
    if choice=="accept_incoming":
        record.payload=conflict.incoming_payload;record.payload_hash=conflict.incoming_hash;record.revision=conflict.incoming_revision;record.updated_at=now()
    conflict.state=choice;db.commit();return {"id":ident,"state":choice}

def run_sync(db,tenant):
    # One page per tenant tick; transaction lock means checkpoint and rows
    # commit together. Crashes before commit safely repeat a read-only page.
    _lock(db,tenant)
    job=db.query(ProviderSyncJob).filter(ProviderSyncJob.business_id==tenant,ProviderSyncJob.state.in_(["queued","retry"]),ProviderSyncJob.next_attempt<=now()).order_by(ProviderSyncJob.created_at,ProviderSyncJob.id).first()
    if not job:db.rollback();return None
    row=by_id(db,tenant,job.connection_id)
    if row.generation!=job.generation or row.state!="connected":
        job.state="cancelled";job.finished_at=now();db.commit();return sync_public(job)
    job.attempts+=1
    try:
        adapter=adapter_for(row.provider);token=credentials(db,row,adapter)
        records,cursor,more=normalize_page(adapter.page(token,row.checkpoint,row.scopes))
        if more and cursor==row.checkpoint:raise ValueError("Provider checkpoint did not progress")
        if job.pages>=200:raise ValueError("Sync page capacity reached")
        with db.begin_nested():
            imported,duplicates,conflicts=ingest(db,row,records)
        row.checkpoint=cursor if cursor is not None else row.checkpoint
        job.pages+=1;job.imported+=imported;job.duplicates+=duplicates;job.conflicts+=conflicts
        job.attempts=0;job.error_code=None;row.last_error=None
        if more:job.state="queued";job.next_attempt=now()
        else:job.state="succeeded";job.finished_at=now();row.last_sync=now()
    except ProviderFailure as exc:
        job.error_code=exc.code;row.last_error=exc.code
        if exc.code in ("authorization_rejected","auth_required","refresh_required","refresh_uncertain_reauthorize","credential_decryption_failed","adapter_identity_changed"):
            row.state="auth_required";job.state="failed";job.finished_at=now()
        elif exc.retryable and job.attempts<6:
            job.state="retry";job.next_attempt=now()+timedelta(seconds=max(exc.retry_after,min(900,2**job.attempts*15)))
        else:job.state="failed";job.finished_at=now()
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        job.error_code="invalid_adapter_configuration_or_page";row.last_error=job.error_code;job.state="failed";job.finished_at=now()
    row.updated_at=now();db.commit();return sync_public(job)

def retry_sync(db,tenant,ident):
    _lock(db,tenant);job=db.query(ProviderSyncJob).filter_by(business_id=tenant,id=ident).first()
    if not job or job.state!="failed":raise ValueError("Failed sync unavailable")
    row=by_id(db,tenant,job.connection_id)
    if row.generation!=job.generation or row.state!="connected":raise ValueError("Reconnect and queue a new sync")
    job.state="queued";job.attempts=0;job.next_attempt=now();job.error_code=None;job.finished_at=None
    db.commit();return sync_public(job)


# Explicit founder-approved actions only. The provider must support idempotency
# and read-only lookup by request key; an ambiguous send is never replayed.
ACTION_FIELDS={"contact.upsert":({"name","email"},{"company"}),"email.send":({"recipient","subject","body"},set()),
    "event.create":({"title","start","end"},{"description"}),"issue.create":({"repository","title","body"},set()),
    "page.create":({"parent_id","title","body"},set()),"document.create":({"title","body"},set())}

def action_payload(action,payload):
    required,optional=ACTION_FIELDS[action];json_payload(payload)
    if not required<=set(payload)<=required|optional:raise ValueError("Invalid action fields")
    for name,value in payload.items():
        if name in ("body","description"):
            if not isinstance(value,str) or not 1<=len(value)<=12000 or any(ord(c)<32 and c not in "\n\r\t" for c in value):raise ValueError("Invalid action text")
        else:bounded_string(value,1000)
    if action=="email.send" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",payload["recipient"]):raise ValueError("Invalid recipient")
    if action=="event.create":
        try:
            start=datetime.fromisoformat(payload["start"].replace("Z","+00:00"))
            end=datetime.fromisoformat(payload["end"].replace("Z","+00:00"))
            if start.tzinfo is None or end.tzinfo is None or end<=start:raise ValueError()
        except ValueError:raise ValueError("Event requires ordered timezone-aware dates") from None
    return payload

def delivery_public(row):
    return {"id":row.id,"action":row.action,"state":row.state,"request_key":row.request_key,"remote_reference":row.remote_reference,
            "error_code":row.error_code,"created_at":row.created_at.isoformat()+"Z","updated_at":row.updated_at.isoformat()+"Z",
            "provider_confirmed":row.state=="confirmed"}

def approve_action(db,tenant,actor,provider,action,payload,request_key,confirmation):
    key(request_key)
    if provider not in CAPABILITIES or action not in CAPABILITIES[provider][1] or confirmation!="APPROVE "+action:raise ValueError("Explicit supported action confirmation required")
    payload=action_payload(action,payload)
    _lock(db,tenant);row=connection(db,tenant,provider)
    checksum=digest([action,payload])
    old=db.query(ProviderDelivery).filter_by(business_id=tenant,connection_id=row.id,request_key=request_key).first()
    if old:
        if old.request_hash!=checksum:raise ValueError("Request key already used for different action")
        return delivery_public(old)
    adapter=adapter_for(provider)
    if adapter.fingerprint!=row.adapter_fingerprint or action not in adapter.actions:raise ValueError("Action unavailable for selected adapter")
    if row.state!="connected" or CAPABILITIES[provider][1][action] not in row.scopes:raise ValueError("Connected write scope required")
    if db.query(ProviderDelivery).filter_by(business_id=tenant).count()>=2000:raise ValueError("Delivery capacity reached")
    action_row=ProviderDelivery(business_id=tenant,connection_id=row.id,generation=row.generation,request_key=request_key,
      request_hash=checksum,action=action,payload=payload,actor_id=actor)
    db.add(action_row);db.commit();return delivery_public(action_row)

def apply_delivery_status(action,result):
    if result.get("idempotency_key")!=action.request_key:raise ValueError("Delivery identity mismatch")
    state=result.get("status")
    if state=="confirmed":
        action.remote_reference=bounded_string(result.get("remote_reference"),255);action.state="confirmed";action.error_code=None
    elif state=="rejected":
        action.state="rejected";action.error_code="provider_rejected"
    elif state in ("pending","not_found","unknown"):
        action.state="uncertain";action.error_code="delivery_unconfirmed"
    else:raise ValueError("Invalid delivery status")

def dispatch_one(db,tenant):
    from apps.api.models.business import Business,User
    from apps.api.services.durable_jobs import execution_lock
    # Durable dispatching marker precedes network. A separate execution lock
    # prevents a reconciliation racing an active worker in PostgreSQL.
    _lock(db,tenant)
    action=db.query(ProviderDelivery).filter_by(business_id=tenant,state="approved").order_by(ProviderDelivery.created_at,ProviderDelivery.id).first()
    if not action:db.rollback();return None
    ident=action.id
    with execution_lock(db.get_bind(),"provider-delivery:"+tenant+":"+ident) as held:
        if not held:db.rollback();return None
        row=by_id(db,tenant,action.connection_id)
        owner=db.query(Business).filter_by(id=tenant,owner_id=action.actor_id).first()
        actor=db.query(User).filter_by(id=action.actor_id,business_id=tenant,is_active=True).first()
        if not owner or not actor or row.state!="connected" or row.generation!=action.generation or CAPABILITIES[row.provider][1].get(action.action) not in row.scopes:
            action.state="cancelled";action.updated_at=now();db.commit();return delivery_public(action)
        try:
            adapter=adapter_for(row.provider);token=credentials(db,row,adapter)
        except (ValueError,ProviderFailure):
            action.state="cancelled";action.error_code="authorization_unavailable";row.state="auth_required";db.commit();return delivery_public(action)
        action.state="dispatching";action.updated_at=now();db.commit()
        _lock(db,tenant)
        action=db.query(ProviderDelivery).filter_by(business_id=tenant,id=ident).one()
        row=by_id(db,tenant,action.connection_id)
        if row.generation!=action.generation or row.state!="connected":
            action.state="cancelled";action.updated_at=now();db.commit();return delivery_public(action)
        try:
            if adapter.fingerprint!=row.adapter_fingerprint or action.action not in adapter.actions:raise ValueError("Adapter identity changed")
            result=adapter.deliver(token,action.action,action.payload,action.request_key)
            apply_delivery_status(action,result)
        except (ProviderFailure,ValueError):
            # Even a timeout or 5xx may have occurred after side effect.
            action.state="uncertain";action.error_code="delivery_uncertain"
        action.updated_at=now();db.commit();return delivery_public(action)

def reconcile_delivery(db,tenant,ident):
    from apps.api.services.durable_jobs import execution_lock
    with execution_lock(db.get_bind(),"provider-delivery:"+tenant+":"+ident) as held:
        if not held:raise ValueError("Delivery worker is active")
        _lock(db,tenant)
        action=db.query(ProviderDelivery).filter_by(business_id=tenant,id=ident).first()
        if not action:raise ValueError("Delivery unavailable")
        if action.state in ("confirmed","rejected","cancelled"):return delivery_public(action)
        if action.state not in ("dispatching","uncertain"):raise ValueError("Delivery has not been dispatched")
        row=by_id(db,tenant,action.connection_id)
        try:
            adapter=adapter_for(row.provider);token=credentials(db,row,adapter)
            apply_delivery_status(action,adapter.delivery_status(token,action.request_key))
        except (ValueError,ProviderFailure):
            action.state="uncertain";action.error_code="status_unavailable"
        action.updated_at=now();db.commit();return delivery_public(action)

def cancel_action(db,tenant,ident):
    _lock(db,tenant);action=db.query(ProviderDelivery).filter_by(business_id=tenant,id=ident,state="approved").first()
    if not action:raise ValueError("Only undispatched approved actions may be cancelled")
    action.state="cancelled";action.updated_at=now();db.commit();return delivery_public(action)

def webhook_signature(provider,tenant,connection_id,timestamp,body,signature):
    from apps.api.services.integrations.provider_transport import configuration
    import time
    config=configuration(provider)
    secret=config.get("webhook_secret")
    if not isinstance(secret,str) or len(secret)<32 or len(secret)>512:raise ValueError("Webhook unavailable")
    if not re.fullmatch(r"[0-9]{1,12}",timestamp or "") or abs(time.time()-int(timestamp))>300:raise ValueError("Webhook timestamp outside window")
    if not re.fullmatch(r"[a-f0-9]{64}",signature or ""):raise ValueError("Invalid webhook signature")
    signed=b"\n".join([provider.encode(),tenant.encode(),connection_id.encode(),timestamp.encode(),body])
    expected=hmac.new(secret.encode(),signed,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature):raise ValueError("Invalid webhook signature")

def accept_webhook(db,tenant,provider,connection_id,body):
    # The router authenticates the exact raw bytes before applying tenant scope.
    try:
        data=json.loads(body)
        if not isinstance(data,dict) or set(data)!={"event_id","account_id","type"} or data["type"]!="records.changed":raise ValueError()
        event=key(data["event_id"]);account=bounded_string(data["account_id"],255)
    except (ValueError,TypeError,UnicodeError):raise ValueError("Invalid webhook event") from None
    _lock(db,tenant);row=by_id(db,tenant,connection_id)
    if row.provider!=provider or row.state!="connected" or row.remote_account!=account:raise ValueError("Webhook account unavailable")
    checksum=hashlib.sha256(body).hexdigest()
    old=db.query(ProviderWebhookReceipt).filter_by(business_id=tenant,connection_id=row.id,event_id=event).first()
    if old:
        if old.body_hash!=checksum:raise ValueError("Webhook event identity conflict")
        return {"accepted":True,"duplicate":True}
    if db.query(ProviderWebhookReceipt).filter_by(business_id=tenant).count()>=10000:raise ValueError("Webhook receipt capacity reached")
    db.add(ProviderWebhookReceipt(business_id=tenant,connection_id=row.id,event_id=event,body_hash=checksum))
    enqueue(db,tenant,provider,"webhook:"+hashlib.sha256(event.encode()).hexdigest(),commit=False)
    db.commit();return {"accepted":True,"duplicate":False}


def reset_checkpoint(db,tenant,provider,confirmation):
    if confirmation!="RESET CHECKPOINT "+provider:raise ValueError("Explicit checkpoint reset confirmation required")
    _lock(db,tenant);row=connection(db,tenant,provider)
    if row.state!="connected":raise ValueError("Connected provider required")
    db.query(ProviderSyncJob).filter(ProviderSyncJob.business_id==tenant,ProviderSyncJob.connection_id==row.id,ProviderSyncJob.state.in_(["queued","retry"])).update({"state":"cancelled","finished_at":now()},synchronize_session=False)
    row.checkpoint=None;row.last_sync=None;row.last_error="checkpoint_reset_full_resync_required";row.updated_at=now()
    db.commit()
    return {"checkpoint_reset":True,"previous_records_retained":True,"next_step":"Queue full sync; previous records may require review"}
