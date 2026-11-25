"""Launch same-origin HTTPS with a restricted PostgreSQL role and run browser tests."""
import base64, os, pathlib, secrets, subprocess, sys, tempfile, time
import httpx
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from scripts.operations.provision_runtime_role import provision
from scripts.verify_dynamic_security import verify as verify_security
def main():
    if os.environ.get("ONEBOARD_CI_PRODUCTION_BROWSER")!="1":raise RuntimeError("Disposable CI approval required")
    url=make_url(os.environ["DATABASE_URL"])
    if url.host!="127.0.0.1" or url.database!="oneboard_ci" or not url.drivername.startswith("postgresql"):raise RuntimeError("Disposable DB required")
    admin=create_engine(url)
    role="oneboard_browser_"+secrets.token_hex(6);password=secrets.token_hex(24)
    with admin.begin() as conn:
        existing=conn.execute(text("SELECT secret FROM oneboard_private.context_key WHERE singleton")).scalar_one_or_none()
    context=bytes(existing) if existing is not None else secrets.token_bytes(32)
    provision(admin,role,password,context)
    runtime=url.set(username=role,password=password).render_as_string(hide_password=False)
    base="https://127.0.0.1:8443"
    env=dict(os.environ,DATABASE_URL=runtime,TENANT_CONTEXT_KEY=base64.b64encode(context).decode(),ACCOUNT_SECURITY_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),ONEBOARD_PRODUCTION_MODE="true",ONEBOARD_DEMO_MODE="false",COOKIE_SECURE="true",PUBLIC_API_ORIGIN=base,CORS_ORIGINS=base,TRUSTED_PROXY_IPS="127.0.0.1",AUTH_SECRET_KEY=secrets.token_hex(32),OLLAMA_BASE_URL="http://127.0.0.1:1")
    with tempfile.TemporaryDirectory() as tmp:
        cert=pathlib.Path(tmp)/"cert.pem";key=pathlib.Path(tmp)/"key.pem"
        subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","1","-keyout",str(key),"-out",str(cert),"-subj","/CN=127.0.0.1","-addext","subjectAltName=IP:127.0.0.1"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        proc=subprocess.Popen([sys.executable,"-m","uvicorn","apps.api.main:app","--host","127.0.0.1","--port","8443","--ssl-certfile",str(cert),"--ssl-keyfile",str(key)],env=env)
        try:
            with httpx.Client(base_url=base,verify=str(cert),trust_env=False,timeout=2) as client:
                for _ in range(60):
                    if proc.poll() is not None:raise RuntimeError("Production API exited")
                    try:
                        if client.get("/health").status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(1)
                else:raise RuntimeError("Production API startup timed out")
            verify_security(base,str(cert),pathlib.Path('dynamic-security.json'))
            subprocess.run(["npx","--no-install","playwright","test","--config","playwright.production.config.ts","--reporter=line,json"],cwd="apps/web",env=dict(os.environ,PLAYWRIGHT_JSON_OUTPUT_NAME="production-browser.json"),check=True)
            subprocess.run([sys.executable,"scripts/require_browser_suite.py","apps/web/production-browser.json","1"],check=True)
        finally:
            proc.terminate()
            try:proc.wait(timeout=20)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
if __name__=="__main__":main()
