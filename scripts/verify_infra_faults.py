"""Real disposable PostgreSQL outage, critical transaction rollback and pool exhaustion.

Never run against a deployed database. CI supplies the exact service-container
ID; the script validates its identity and local DSN before stopping it.
"""
import concurrent.futures,hashlib,json,os,pathlib,re,subprocess,sys,time,random
from uuid import uuid4
import httpx
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

def docker(command,container):
    p=subprocess.run(["docker",command,container],capture_output=True,timeout=60)
    if p.returncode:raise RuntimeError("Disposable Docker operation failed")
def validated():
    url=make_url(os.environ.get("DATABASE_URL",""))
    ident=os.environ.get("ONEBOARD_FAULT_POSTGRES_CONTAINER","")
    if os.environ.get("ONEBOARD_CI_INFRA_FAULTS")!="1" or url.drivername!="postgresql+psycopg" or url.host!="127.0.0.1" or url.database!="oneboard_ci" or url.username!="oneboard_ci" or not re.fullmatch("[a-f0-9]{64}",ident):
        raise RuntimeError("Explicit disposable service container required")
    meta=json.loads(subprocess.check_output(["docker","inspect",ident],timeout=10))[0]
    if not meta["Config"]["Image"].startswith("postgres:16") or "POSTGRES_DB=oneboard_ci" not in meta["Config"]["Env"] or "POSTGRES_USER=oneboard_ci" not in meta["Config"]["Env"]:
        raise RuntimeError("Container identity mismatch")
    ports=meta["NetworkSettings"]["Ports"].get("5432/tcp",[])
    if not any(x["HostPort"]==str(url.port or 5432) for x in ports):raise RuntimeError("Service port mismatch")
    return url,ident
def main():
    url,ident=validated()
    admin=create_engine(url,pool_pre_ping=True,connect_args={"connect_timeout":2})
    env={**os.environ,"ONEBOARD_PRODUCTION_MODE":"false","ONEBOARD_DEMO_MODE":"false","DB_POOL_SIZE":"4","DB_MAX_OVERFLOW":"0","DB_POOL_TIMEOUT_SECONDS":"1","OPERATOR_DB_CONNECT_TIMEOUT":"2","SCHEDULER_INTERVAL_SECONDS":"3600","CORS_ORIGINS":"http://127.0.0.1:8765"}
    proc=subprocess.Popen([sys.executable,"-m","uvicorn","apps.api.main:app","--host","127.0.0.1","--port","8765","--no-access-log"],env=env)
    report={}
    try:
        with httpx.Client(base_url="http://127.0.0.1:8765",timeout=15,trust_env=False) as c:
            for _ in range(60):
                try:
                    if c.get("/ready").status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise RuntimeError("API did not become ready")
            resp=c.post("/api/auth/register",json={"name":"Synthetic","business_name":"Fault fixture","email":uuid4().hex+"@example.test","password":"Synthetic-fixture-password123!"})
            assert resp.status_code==201,resp.status_code
            payload=resp.json();tenant=payload["business"]["id"]
            headers={"Authorization":"Bearer "+payload["token"]}
            from apps.api.models.business import Business
            from apps.api.models.operations import JournalEntry
            from apps.api.services import finance_ledger as ledger
            reference="fault-"+uuid4().hex
            args={"reference":reference,"kind":"capital","amount":"10.00","currency":"USD","fx_rate":"1","fx_source":"same_currency","booked_on":"2026-01-01","evidence_text":"synthetic outage fixture"}
            actor=__import__("apps.api.models.business",fromlist=["User"]).User
            with Session(admin) as session:
                user_id=session.query(actor.id).filter_by(business_id=tenant).scalar()
                assert user_id
                ledger.post(session,tenant,user_id,commit=False,**args)
                # A real database service stop while the transaction is open.
                started=time.monotonic()
                docker("stop",ident)
                try:
                    try:session.commit()
                    except DBAPIError:session.rollback()
                    else:raise AssertionError("Commit unexpectedly succeeded during outage")
                    assert c.get("/health").status_code==200
                    assert c.get("/ready").status_code==503
                    failed=c.post("/api/business/financial/journal",headers=headers,json=args)
                    assert failed.status_code==503,failed.status_code
                finally:docker("start",ident)
            for _ in range(60):
                try:
                    if c.get("/ready").status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise RuntimeError("API failed to recover after actual DB restart")
            with Session(admin) as session:
                assert session.query(JournalEntry).filter_by(business_id=tenant,reference=reference).count()==0
            first=c.post("/api/business/financial/journal",headers=headers,json=args)
            second=c.post("/api/business/financial/journal",headers=headers,json=args)
            assert first.status_code==second.status_code==200,(first.status_code,second.status_code)
            assert first.json()["id"]==second.json()["id"]
            with Session(admin) as session:
                assert session.query(JournalEntry).filter_by(business_id=tenant,reference=reference).count()==1
            report.update(database_restart_verified=True,critical_transaction_rollback_verified=True,idempotent_recovery_verified=True,service_recovery_seconds=round(time.monotonic()-started,3))
            # Seeded fault timing is reproducible; interrupt the actual disposable
            # database service, verify fail-closed health and recovered tenant reads.
            rng=random.Random(int(os.getenv("ONEBOARD_FAULT_SEED","70129")))
            cycles=[]
            for _ in range(3):
                delay=rng.uniform(.1,.8);time.sleep(delay)
                docker("stop",ident)
                try:
                    assert c.get("/ready").status_code==503
                finally:docker("start",ident)
                for attempt in range(60):
                    try:
                        if c.get("/ready").status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(1)
                else:raise RuntimeError("Randomized restart failed to recover")
                assert c.get("/api/auth/me",headers=headers).json()["business"]["id"]==tenant
                cycles.append({"delay_seconds":round(delay,3),"recovered":True})
            report["seeded_restart_cycles"]=cycles
            # Saturate all four actual API DB connections on the same advisory
            # lock. Extra requests must get a bounded 503 and recover later.
            lock=int.from_bytes(hashlib.sha256(("oneboard:storage:"+tenant).encode()).digest()[:8],"big",signed=True)
            with admin.connect() as conn:
                conn.execute(text("SELECT pg_advisory_lock(:k)"),{"k":lock});conn.commit()
                def get():
                    with httpx.Client(base_url="http://127.0.0.1:8765",headers=headers,timeout=15,trust_env=False) as client:
                        return client.get("/api/business/metrics").status_code
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                    futures=[pool.submit(get) for _ in range(10)]
                    time.sleep(3)
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"),{"k":lock});conn.commit()
                    codes=[f.result() for f in futures]
                assert 503 in codes and set(codes)<={200,503},codes
            assert c.get("/api/business/metrics",headers=headers).status_code==200
            report.update(pool_exhaustion_verified=True,pool_rejections=codes.count(503),pool_recovered=True)
            pathlib.Path("infra-fault-report.json").write_text(json.dumps(report,indent=2))
            print("INFRA_FAULT_RESULT "+json.dumps(report))
    finally:
        proc.terminate()
        try:proc.wait(timeout=45)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        admin.dispose()
if __name__=="__main__":main()
