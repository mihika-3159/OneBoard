"""Bounded process-local telemetry and dependency probes. No tenant identifiers or secrets."""
import hmac,math,re,time,logging,shutil,threading,os
from contextvars import ContextVar
from sqlalchemy import text
from apps.api.core.config import settings
from apps.api.core.database import engine
from apps.api.models.operations import ScheduledJobLease
from sqlalchemy.orm import Session
from uuid import uuid4
from starlette.responses import JSONResponse
logger=logging.getLogger("oneboard.operations")
BUCKETS=(.01,.05,.1,.25,.5,1,2.5,5,10,30,60)
_lock=threading.Lock()
_counts={}
_active=0
_started=time.monotonic()
_draining=False
_trace=ContextVar('oneboard_trace',default=None)
_events={}
def event(name):
    if name not in ('scheduler_failed','db_unavailable','db_pool_exhausted','scheduler_succeeded'):return
    with _lock:_events[name]=_events.get(name,0)+1
async def propagate(request):
    parent=_trace.get()
    if parent:request.headers['traceparent']=f'00-{parent[0]}-{parent[1]}-00'
TRACE=re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})")
def trace_context(header):
    match=TRACE.fullmatch(header or "")
    trace=match[1] if match and int(match[1],16) and int(match[2],16) else uuid4().hex
    return trace,uuid4().hex[:16]
def draining(value=True):
    global _draining
    _draining=value
def authorized(value):
    key=settings.OPERATOR_METRICS_KEY
    return isinstance(key,str) and len(key)>=32 and isinstance(value,str) and hmac.compare_digest(value,key)
class Telemetry:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        global _active
        if scope["type"]!="http":return await self.app(scope,receive,send)
        started=time.monotonic();status=500;method=scope.get("method","OTHER")
        if method not in ("GET","POST","PUT","DELETE","PATCH","HEAD","OPTIONS"):method="OTHER"
        headers=[v.decode("latin1") for k,v in scope.get("headers",[]) if k==b"traceparent"]
        trace,span=trace_context(headers[0] if len(headers)==1 else None)
        scope.setdefault("state",{})["trace_id"]=trace
        scope["state"]["span_id"]=span
        token=_trace.set((trace,span))
        with _lock:_active+=1
        async def wrapped(message):
            nonlocal status
            if message["type"]=="http.response.start":
                status=message["status"]
                message={**message,"headers":[*message.get("headers",[]),(b"traceparent",f"00-{trace}-{span}-00".encode())]}
            await send(message)
        try:
            if _draining and scope.get("path") not in ("/health","/ready","/ops/health"):
                await JSONResponse({"detail":"Service draining; retry"},503,headers={"Retry-After":"5"})(scope,receive,wrapped)
            else:await self.app(scope,receive,wrapped)
        finally:
            _trace.reset(token)
            elapsed=time.monotonic()-started
            route=getattr(scope.get("route"),"path","unmatched")
            # Route templates only, never raw URL or arbitrary client labels.
            with _lock:
                _active-=1
                key=(method,route,status//100)
                if key not in _counts and len(_counts)>=2048:key=("OTHER","overflow",0)
                row=_counts.setdefault(key,{"count":0,"sum_seconds":0.0,"buckets":[0]*len(BUCKETS)})
                row["count"]+=1;row["sum_seconds"]+=elapsed
                for i,b in enumerate(BUCKETS):
                    if elapsed<=b:row["buckets"][i]+=1
            logger.info("request_trace trace_id=%s span_id=%s method=%s route=%s status=%d seconds=%.4f",trace,span,method,route,status,elapsed)
def snapshot():
    pool=engine.pool
    pool_stats={name:getattr(pool,name)() for name in ("size","checkedout","overflow") if callable(getattr(pool,name,None))}
    if engine.dialect.name=="postgresql":pool_stats["configured_max"]=settings.DB_POOL_SIZE+settings.DB_MAX_OVERFLOW
    resources={}
    try:
        import resource
        resources["peak_rss_kib"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:pass
    with _lock:
        rows=[{"method":k[0],"route":k[1],"status_class":k[2],**v,"buckets":list(v["buckets"])} for k,v in sorted(_counts.items())]
        return {"scope":"process_local","pid":os.getpid(),"pool":pool_stats,"resources":resources,"uptime_seconds":time.monotonic()-_started,
                "inflight":_active,"events":dict(_events),"bucket_bounds_seconds":list(BUCKETS),"http":rows}
def dependencies(bind=None,check_inference=False):
    bind=engine if bind is None else bind
    result={"database":"unavailable","schema":"unknown","scheduler":"unknown","disk":"unknown","inference":"not_checked"}
    try:
        with bind.connect() as conn:
            if conn.dialect.name=="postgresql":conn.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            conn.execute(text("SELECT 1")).scalar_one()
            result["database"]="ready"
            if settings.ONEBOARD_PRODUCTION_MODE:
                from alembic.migration import MigrationContext
                from alembic.script import ScriptDirectory
                from alembic.config import Config
                expected=set(ScriptDirectory.from_config(Config(str(settings.BASE_DIR/"alembic.ini"))).get_heads())
                result["schema"]="ready" if set(MigrationContext.configure(conn).get_current_heads())==expected else "mismatch"
            else:result["schema"]="local"
            row=conn.execute(text("SELECT last_success_at, attempts FROM scheduled_job_leases WHERE job_key='proactive_health_check'")).first()
            result["scheduler"]="pending" if not row or row[0] is None else "stale" if time.time()-row[0]>max(180,settings.SCHEDULER_INTERVAL_SECONDS*4) else "ready"
            if row and row[1] and result["scheduler"]!="ready":result["scheduler"]="failed_or_stale"
    except Exception as exc:logger.warning("dependency_probe_failed type=%s",type(exc).__name__)
    try:
        free=shutil.disk_usage(settings.DATA_DIR).free//1048576
        result["disk"]="ready" if free>=settings.OPERATOR_DISK_MIN_FREE_MIB else "exhausted"
    except OSError:pass
    if check_inference:
        try:
            import asyncio
            from apps.api.services.ollama_gateway import ollama_gateway
            health=asyncio.run(asyncio.wait_for(ollama_gateway.check_health(),timeout=5))
            result["inference"]="ready" if health.get("inference_available") is True else "unavailable"
        except Exception:result["inference"]="unavailable"
    result["ready"]=not _draining and result["database"]=="ready" and result["schema"] in ("ready","local") and result["disk"]=="ready"
    return result
