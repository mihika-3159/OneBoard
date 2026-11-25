"""Poll the private operator endpoint and emit durable local alert transitions.

No external destinations, credentials or tenant content in output. Exit 1 for
active alerts, 2 for invalid configuration. An external service supervisor
can monitor the exit code independently of the API.
"""
import argparse,json,os,time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from scripts.operations.backup_manager import atomic_json,private_dir,timestamp,utcnow

def evaluate(health,metrics,backup_status=None,backup_max_age_hours=26):
    alerts=set()
    if not health.get("ready"):alerts.add("service_not_ready")
    for key,good in (("database",{"ready"}),("schema",{"ready","local"}),("scheduler",{"ready"}),("disk",{"ready"}),("inference",{"ready"})):
        if health.get(key) not in good:alerts.add(key+"_unavailable")
    if metrics.get("inflight",0)>100:alerts.add("request_concurrency_high")
    pool=metrics.get("pool",{})
    if pool.get("size",0)>0 and pool.get("checkedout",0)>=pool["size"]+max(0,pool.get("overflow",0)):alerts.add("database_pool_saturated")
    events=metrics.get("events",{})
    if events.get("scheduler_failed",0)>0 and health.get("scheduler")!="ready":alerts.add("background_job_failure")
    if backup_status is not None:
        try:
            if backup_status.get("status")!="ok":alerts.add("backup_failed")
            if (utcnow()-timestamp(backup_status["latest_backup_utc"])).total_seconds()>backup_max_age_hours*3600:alerts.add("backup_stale")
            if (utcnow()-timestamp(backup_status["checked_at"])).total_seconds()>7200:alerts.add("backup_verification_stale")
        except (ValueError,KeyError,TypeError):alerts.add("backup_status_invalid")
    return sorted(alerts)
def transitions(path,alerts,now=None):
    now=time.time() if now is None else now
    path=Path(path)
    previous={}
    if path.exists():
        if path.is_symlink() or path.stat().st_size>1024*1024:raise ValueError("Invalid operator state")
        previous=json.loads(path.read_text())
    old=previous.get("active",{})
    active={a:old.get(a,now) for a in alerts}
    result={"checked_epoch":now,"active":active,"opened":sorted(set(active)-set(old)),"resolved":sorted(set(old)-set(active))}
    atomic_json(path,result);return result
def probe(origin,key,ca=None):
    u=urlsplit(origin)
    if u.scheme!="https" and not (u.scheme=="http" and u.hostname in ("127.0.0.1","localhost","::1")):raise ValueError("HTTPS required for remote operator checks")
    if u.username or u.password or u.path or u.query or u.fragment or len(key)<32:raise ValueError("Invalid operator origin or key")
    with httpx.Client(timeout=5,verify=ca or True,trust_env=False,follow_redirects=False,headers={"X-Operator-Key":key}) as c:
        health=c.get(origin+"/ops/health")
        metrics=c.get(origin+"/ops/metrics")
        if health.status_code not in (200,503) or metrics.status_code!=200:raise ValueError("Operator probe rejected")
        return health.json(),metrics.json()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--origin",required=True)
    p.add_argument("--directory",type=Path,required=True);p.add_argument("--ca");p.add_argument("--backup-status",type=Path)
    a=p.parse_args();directory=private_dir(a.directory);key=os.environ.get("OPERATOR_METRICS_KEY","")
    if len(key)<32:p.error("Operator key must be configured")
    try:
        health,metrics=probe(a.origin,key,a.ca)
    except (httpx.HTTPError,ValueError):health,metrics={},{}
    backup=None
    if a.backup_status:
        try:
            if a.backup_status.is_symlink() or a.backup_status.stat().st_size>1024*1024:raise ValueError()
            backup=json.loads(a.backup_status.read_text())
        except (ValueError,OSError):backup={}
    result=transitions(directory/"operator-alerts.json",evaluate(health,metrics,backup))
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(1 if result["active"] else 0)
if __name__=="__main__":main()
