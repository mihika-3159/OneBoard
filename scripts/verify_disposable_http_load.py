"""Bounded real HTTPS, two-worker PostgreSQL workload and restart drill.

Only runs on a local disposable oneboard_ci database with an explicit flag.
No real customer data, paid provider, or outbound action.
"""
import concurrent.futures
import json
import os
import pathlib
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url

BASE="https://127.0.0.1:8443"
def main():
    if os.environ.get("ONEBOARD_CI_HTTP_LOAD")!="1":
        raise SystemExit("Explicit disposable HTTP load approval required")
    url=make_url(os.environ["DATABASE_URL"])
    if url.host not in ("127.0.0.1","localhost","::1") or url.database!="oneboard_ci" or not url.drivername.startswith("postgresql"):
        raise SystemExit("Refusing non-disposable database")
    from sqlalchemy import create_engine,text
    from scripts.operations.provision_runtime_role import provision
    admin=create_engine(url)
    role='oneboard_runtime_ci_'+uuid4().hex[:10]
    password=secrets.token_hex(24)
    import base64
    context=secrets.token_bytes(32)
    with admin.begin() as conn:
        existing=conn.execute(text('SELECT secret FROM oneboard_private.context_key WHERE singleton')).scalar_one_or_none()
        if existing is not None: context=bytes(existing)
    provision(admin,role,password,context)
    runtime_url=url.set(username=role,password=password).render_as_string(hide_password=False)
    env=dict(os.environ,DATABASE_URL=runtime_url,TENANT_CONTEXT_KEY=base64.b64encode(context).decode(),ACCOUNT_SECURITY_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),ONEBOARD_PRODUCTION_MODE="true",ONEBOARD_DEMO_MODE="false",
             COOKIE_SECURE="true",PUBLIC_API_ORIGIN=BASE,CORS_ORIGINS=BASE,
             TRUSTED_PROXY_IPS="127.0.0.1",AUTH_SECRET_KEY=secrets.token_hex(32),
             OLLAMA_BASE_URL="http://127.0.0.1:1",SCHEDULER_INTERVAL_SECONDS="10")
    with tempfile.TemporaryDirectory() as tmp:
        cert=pathlib.Path(tmp)/"cert.pem"
        key=pathlib.Path(tmp)/"key.pem"
        subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","1",
                        "-keyout",str(key),"-out",str(cert),"-subj","/CN=127.0.0.1",
                        "-addext","subjectAltName=IP:127.0.0.1"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def client(headers=None):
            return httpx.Client(base_url=BASE,verify=str(cert),headers=headers,timeout=15,trust_env=False)
        def start():
            proc=subprocess.Popen([sys.executable,"-m","uvicorn","apps.api.main:app",
                "--host","127.0.0.1","--port","8443","--workers","2","--no-access-log",
                "--ssl-certfile",str(cert),"--ssl-keyfile",str(key)],env=env)
            try:
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    if proc.poll() is not None:
                        raise RuntimeError("Application exited before readiness")
                    try:
                        with client() as c:
                            if c.get("/health").status_code==200:
                                return proc
                    except httpx.HTTPError:
                        pass
                    time.sleep(.5)
                raise RuntimeError("Application readiness timed out")
            except BaseException:
                stop(proc)
                raise
        def stop(proc):
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        proc=start()
        tenants=[]
        try:
            for i in range(12):
                with client() as c:
                    reg=c.post("/api/auth/register",json={"name":"Synthetic load founder","business_name":"Disposable load tenant","email":uuid4().hex+"@example.test","password":"Synthetic-test-password123!"})
                    assert reg.status_code==201,reg.status_code
                    reg=reg.json()
                    headers={"Authorization":"Bearer "+reg["token"]}
                    with client(headers) as auth:
                        wf=auth.post("/api/workflows",json={"name":"Synthetic replay","nodes":[{"id":"start","type":"trigger","data":{}}],"edges":[]})
                        assert wf.status_code==200,wf.status_code
                        tenants.append((reg["business"]["id"],headers,wf.json()["id"],uuid4().hex))
            # Separate synthetic workspace exercises real scheduled dispatch
            # by the restricted-role background workers during sustained load.
            with client() as c:
                reg=c.post("/api/auth/register",json={"name":"Schedule CI founder","business_name":"Schedule CI tenant","email":uuid4().hex+"@example.test","password":"Synthetic-test-password123!"})
                assert reg.status_code==201,reg.status_code
                reg=reg.json()
            schedule_headers={"Authorization":"Bearer "+reg["token"]}
            with client(schedule_headers) as c:
                wf=c.post("/api/workflows",json={"name":"Synthetic scheduled trigger","nodes":[{"id":"start","type":"trigger","data":{}}],"edges":[]})
                assert wf.status_code==200,wf.status_code
                scheduled_id=wf.json()["id"]
                configured=c.put(f"/api/workflows/{scheduled_id}/schedule",json={"cron":"0 9 * * *","timezone":"UTC","enabled":True})
                assert configured.status_code==200,configured.status_code
                slot=configured.json()["next_due_at"]-3*86400
            # Explicit CI-only fault setup simulates several missed days,
            # without modifying the server's wall clock or any real data.
            with admin.begin() as conn:
                conn.execute(text("UPDATE workflow_schedules SET next_due_at=:slot WHERE workflow_id=:wid"),{"slot":slot,"wid":scheduled_id})
            deadline=time.monotonic()+120
            def worker(record):
                tenant,headers,wid,idem=record
                durations=[]
                runs=set()
                quota=0
                with client(headers) as c:
                    while time.monotonic()<deadline:
                        for route in ("/api/business/metrics","/api/workflows","/api/diagnostics/operations"):
                            t=time.monotonic()
                            res=c.get(route)
                            durations.append(time.monotonic()-t)
                            assert res.status_code==200,(route,res.status_code)
                            assert res.headers.get("X-Request-ID")
                            data=res.json()
                            if route.endswith("metrics"):
                                assert data["tenant_id"]==tenant
                            if route.endswith("workflows"):
                                assert {x["id"] for x in data}=={wid}
                            if route.endswith("operations"):
                                assert data["memory_chunks"]==0 and data["external_delivery_verified"] is False
                        t=time.monotonic()
                        res=c.post(f"/api/workflows/{wid}/execute",headers={"Idempotency-Key":idem})
                        durations.append(time.monotonic()-t)
                        if res.status_code==429:
                            assert int(res.headers["Retry-After"])>0
                            quota+=1
                        else:
                            assert res.status_code==200,res.status_code
                            runs.add(res.json()["id"])
                        time.sleep(.15)
                    assert len(runs)==1
                    assert len(c.get("/api/workflows/runs").json())==1
                    return durations,quota,next(iter(runs))
            t0=time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                results=list(pool.map(worker,tenants))
            elapsed=time.monotonic()-t0
            durations=[x for result in results for x in result[0]]
            ordered=sorted(durations)
            p95=ordered[min(len(ordered)-1,int(.95*len(ordered)))]
            assert elapsed>=115 and len(durations)>=1000
            assert p95<5,(len(durations),p95)
            assert sum(row[1] for row in results)>0,"Expected quota saturation"
            def verify_schedule():
                with client(schedule_headers) as c:
                    res=c.get("/api/workflows/schedules")
                    assert res.status_code==200,res.status_code
                    schedules=res.json()
                    assert len(schedules)==1
                    row=schedules[0]
                    if row["last_status"]!="completed":
                        return None
                    assert row["enabled"] and row["coalesced"]
                    assert row["next_due_at"]>time.time()
                    runs=c.get("/api/workflows/runs").json()
                    assert len(runs)==1 and runs[0]["trigger_source"]=="schedule"
                    assert runs[0]["id"]==row["last_run_id"]
                    return runs[0]["id"]
            due_deadline=time.monotonic()+35
            while True:
                scheduled_run=verify_schedule()
                if scheduled_run:
                    break
                assert time.monotonic()<due_deadline,"Actual background scheduler never executed missed slot"
                time.sleep(1)
            # A fresh process must preserve auth, durable runs and tenant boundaries.
            stop(proc)
            proc=start()
            for (tenant,headers,wid,idem),(_,_,run_id) in zip(tenants,results):
                with client(headers) as c:
                    assert c.get("/api/business/metrics").json()["tenant_id"]==tenant
                    rows=c.get("/api/workflows/runs")
                    assert rows.status_code==200 and [row["id"] for row in rows.json()]==[run_id]
            assert verify_schedule()==scheduled_run
            with client(tenants[0][1]) as c:
                denied=c.post(f"/api/workflows/{tenants[1][2]}/execute",headers={"Idempotency-Key":uuid4().hex})
                assert denied.status_code in (403,404)
            report={"tenants":len(tenants),"workers":2,"seconds":round(elapsed,2),
                    "requests":len(durations),"p95_ms":round(p95*1000,1),
                    "median_ms":round(statistics.median(durations)*1000,1),
                    "expected_quota_rejections":sum(row[1] for row in results),
                    "unexpected_errors":0,"restart_verified":True,"restricted_runtime_role":True,"scheduled_run_restart_verified":True,"environment":"disposable_loopback_https_postgresql"}
            print("LOAD_RESULT "+json.dumps(report,sort_keys=True),flush=True)
            pathlib.Path("http-load-result.json").write_text(json.dumps(report,indent=2))
        finally:
            stop(proc)

if __name__=="__main__":
    main()
