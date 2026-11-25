"""Read-only deployment/rollback compatibility preflight.

The previous image may be reused only if its declared schema matches the
actual database. Otherwise require a separately approved restored clone,
migration and validation; never perform an automatic downgrade.
"""
import argparse,json,re
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
def assess(image,expected,actual):
    if not re.fullmatch(r"(?:[a-zA-Z0-9./:_-]+@)?sha256:[a-f0-9]{64}",image):raise ValueError("Immutable release image digest required")
    if not isinstance(expected,str) or not re.fullmatch("[a-zA-Z0-9_]{1,64}",expected):raise ValueError("Invalid expected Alembic revision")
    return {"image":image,"expected_schema":expected,"actual_schema":sorted(actual),"compatible":set(actual)=={expected},"automatic_downgrade":False,"action":"deploy_after_other_gates" if set(actual)=={expected} else "stop_restore_clone_and_validate"}
def main():
    import os
    p=argparse.ArgumentParser();p.add_argument("--release-manifest",type=Path,required=True);a=p.parse_args()
    if a.release_manifest.is_symlink() or a.release_manifest.stat().st_size>65536:raise ValueError("Invalid release manifest")
    manifest=json.loads(a.release_manifest.read_text())
    url=make_url(os.environ["DATABASE_URL"])
    if not url.drivername.startswith("postgresql") or (url.host not in ("127.0.0.1","localhost","::1") and url.query.get("sslmode")!="verify-full"):raise ValueError("Verified PostgreSQL connection required")
    engine=create_engine(url,connect_args={"connect_timeout":3})
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            actual=[x[0] for x in conn.execute(text("SELECT version_num FROM alembic_version"))]
        result=assess(manifest["image"],manifest["schema_head"],actual);print(json.dumps(result))
        raise SystemExit(0 if result["compatible"] else 1)
    finally:engine.dispose()
if __name__=="__main__":main()
