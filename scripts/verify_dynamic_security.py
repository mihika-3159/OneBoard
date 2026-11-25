"""Authenticated, bounded DAST against an explicitly disposable loopback HTTPS app."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import httpx

READS=("/api/auth/me","/api/auth/security","/api/business/metrics","/api/workflows","/api/workflows/runs","/api/agents","/api/agents/runs","/api/accountability/decisions","/api/data/export-snapshot","/api/ai/status","/api/integrations/providers/live")
def verify(base,cert,out):
    url=urlsplit(base)
    if os.environ.get("ONEBOARD_CI_PRODUCTION_BROWSER")!="1" or url.scheme!="https" or url.hostname!="127.0.0.1" or url.port!=8443:
        raise RuntimeError("DAST requires approved disposable HTTPS target")
    checks=[]
    def record(label,response,expected):
        assert response.status_code in expected,(label,response.status_code,expected)
        assert response.headers.get("X-Content-Type-Options")=="nosniff",label
        assert response.headers.get("X-Frame-Options")=="DENY",label
        assert response.headers.get("Strict-Transport-Security"),label
        checks.append({"check":label,"status":response.status_code})
        return response
    def client():return httpx.Client(base_url=base,verify=cert,timeout=30,trust_env=False)
    with client() as anon,client() as a,client() as b:
        for path in READS:record("anonymous "+path,anon.get(path),{401})
        for token in ("invalid", "A"*4096):
            record("malformed bearer rejected",anon.get("/api/auth/me",headers={"Authorization":"Bearer "+token}),{401})
        cors=anon.options("/api/workflows",headers={"Origin":"https://untrusted.example","Access-Control-Request-Method":"POST"})
        assert "access-control-allow-origin" not in cors.headers
        checks.append({"check":"foreign CORS preflight denied","status":cors.status_code})
        def register(c):
            res=record("register synthetic tenant",c.post("/api/auth/register",json={"name":"DAST fixture","email":uuid4().hex+"@example.test","password":"Synthetic-test-password123!","business_name":"Disposable security fixture"},headers={"Origin":base}),{201})
            value=res.json()
            cookies=res.headers.get_list("set-cookie")
            assert any("oneboard_session=" in item and "httponly" in item.lower() and "secure" in item.lower() for item in cookies)
            return value
        owner,other=register(a),register(b)
        assert owner["business"]["id"]!=other["business"]["id"]
        headers=lambda row:{"Origin":base,"X-CSRF-Token":row["csrf_token"]}
        payload={"name":"DAST private workflow","nodes":[{"id":"start","type":"trigger","data":{}}],"edges":[]}
        record("missing CSRF rejected",a.post("/api/workflows",json=payload,headers={"Origin":base}),{403})
        record("foreign origin rejected",a.post("/api/workflows",json=payload,headers={**headers(owner),"Origin":"https://untrusted.example"}),{403})
        created=record("valid tenant creation",a.post("/api/workflows",json=payload,headers=headers(owner)),{200}).json()
        wid=created["id"]
        record("cross-tenant revision access denied",b.get("/api/workflows/"+wid+"/versions"),{403,404})
        record("cross-tenant execution denied",b.post("/api/workflows/"+wid+"/execute?dry_run=true",headers={**headers(other),"Idempotency-Key":uuid4().hex}),{403,404})
        assert all(x["id"]!=wid for x in b.get("/api/workflows").json())
        record("malformed workflow refused",a.post("/api/workflows",headers=headers(owner),json={"name":"Bad","nodes":[{"id":"a","type":"trigger"},{"id":"b","type":"condition"}],"edges":[{"source":"a","target":"b"},{"source":"b","target":"a"}]}),{400,422})
        snapshot=record("owner snapshot",a.get("/api/data/export-snapshot"),{200}).json()
        assert len(snapshot["tables"]["businesses"])==1 and snapshot["tables"]["businesses"][0]["id"]==owner["business"]["id"]
        assert all("hashed_password" not in x and "api_key" not in x for x in snapshot["tables"]["users"])
        record("logout",a.post("/api/auth/logout",headers=headers(owner)),{200,204})
        record("revoked bearer refused",anon.get("/api/auth/me",headers={"Authorization":"Bearer "+owner["token"]}),{401})
    Path(out).write_text(json.dumps({"scope":"disposable restricted-role HTTPS","checks":checks,"passed":len(checks),"failed":0},indent=2))
