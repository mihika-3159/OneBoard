"""Exercise authenticated tenant isolation with genuine local inference under concurrent clients."""
import argparse, concurrent.futures, json, os, statistics, time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import httpx

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    base=os.environ["ONEBOARD_LIVE_API_URL"]
    if os.environ.get("ONEBOARD_LIVE_API_DISPOSABLE")!="1" or urlsplit(base).hostname not in ("127.0.0.1","localhost"):
        raise RuntimeError("Disposable loopback only")
    tenants=[]
    with httpx.Client(base_url=base,timeout=60,trust_env=False) as client:
        for i in range(4):
            tag=uuid4().hex
            res=client.post("/api/auth/register",json={"name":"Synthetic inference "+str(i),"email":tag+"@example.test","password":"Synthetic-test-password123!","business_name":"Synthetic tenant "+tag})
            res.raise_for_status();row=res.json();tenants.append((row["business"]["id"],row["token"]))
    def work(row):
        tenant,token=row
        times=[]
        with httpx.Client(base_url=base,headers={"Authorization":"Bearer "+token},timeout=90,trust_env=False) as client:
            for i in range(3):
                assert client.get("/api/auth/me").json()["business"]["id"]==tenant
                for attempt in range(3):
                    start=time.monotonic()
                    res=client.post("/api/ai/command",json={"command":"Give one short sentence about organizing a synthetic office."})
                    res.raise_for_status();v=res.json()
                    if v.get("simulated") is False and v.get("response"):
                        times.append(round((time.monotonic()-start)*1000,2));break
                    if attempt==2:raise RuntimeError("Real inference unavailable to a tenant")
                    time.sleep(2)
            assert len(times)==3
        return times
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(work,tenants))
    samples=sorted(t for result in results for t in result)
    assert len(samples)==12 and samples[-1]<90000
    a.output.write_text(json.dumps({"tenants":4,"concurrent_clients":2,"genuine_requests":len(samples),"median_ms":statistics.median(samples),"max_ms":samples[-1],"scope":"disposable authenticated API, small real local model"},indent=2))
if __name__=="__main__":main()
