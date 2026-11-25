"""Explicitly approved encrypted-backup restore drill to a disposable local DB.

Never connect to, overwrite, or restore INTO a production database. An operator
must separately authorize this script; it does not run from ordinary CI.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from scripts.operations.backup_encrypted import verify_manifest

SCRATCH_DB = "oneboard_restore_drill"


def require_disposable_restore(source: dict[str, str], identity: Path) -> tuple:
    if source.get("ONEBOARD_RESTORE_DRILL_APPROVED") != "YES":
        raise RuntimeError("Explicit disposable restore approval is required")
    url = make_url(source.get("ONEBOARD_RESTORE_SCRATCH_URL", ""))
    if (not url.drivername.startswith("postgresql") or
            url.host not in ("127.0.0.1", "localhost", "::1") or
            url.database != SCRATCH_DB or not url.username or not url.password):
        raise RuntimeError("Restore target must be the exact local disposable oneboard_restore_drill database")
    identity = Path(identity)
    if not identity.is_file() or identity.is_symlink() or identity.stat().st_mode & 0o077:
        raise RuntimeError("Decryption identity must be a private 0600 regular file")
    return url, identity


def drill(archive: Path, identity: Path, source: dict[str, str]) -> dict:
    url, identity = require_disposable_restore(source, identity)
    verify_manifest(archive, Path(str(archive) + ".json"))
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    destination = None
    created = False
    decrypt = restore = None
    env = dict(os.environ)
    env.update(PGHOST=url.host, PGUSER=url.username, PGPASSWORD=url.password,
               PGPORT=str(url.port or 5432), PGDATABASE=SCRATCH_DB)
    try:
        with admin.connect() as conn:
            if conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname=:name"),
                {"name": SCRATCH_DB},
            ).first():
                raise RuntimeError("Restore scratch database already exists; refusing overwrite")
            conn.execute(text("CREATE DATABASE oneboard_restore_drill"))
            created = True
        decrypt = subprocess.Popen(
            ["age", "--decrypt", "-i", str(identity), str(archive)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        restore = subprocess.Popen(
            ["pg_restore", "--no-owner", "--no-acl", "--exit-on-error",
             "--dbname", SCRATCH_DB],
            stdin=decrypt.stdout, env=env, stderr=subprocess.DEVNULL,
        )
        if decrypt.stdout is not None:
            decrypt.stdout.close()
        try:
            restore_rc = restore.wait(timeout=900)
            decrypt_rc = decrypt.wait(timeout=900)
        except subprocess.TimeoutExpired:
            decrypt.kill()
            restore.kill()
            decrypt.wait()
            restore.wait()
            raise RuntimeError("Restore drill timed out") from None
        if restore_rc or decrypt_rc:
            raise RuntimeError("Encrypted restore drill failed closed")
        destination = create_engine(url, pool_pre_ping=True)
        with destination.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != "011_batch_c_data":
                raise RuntimeError("Restored schema revision is not current")
            tables = conn.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )).scalar_one()
            if tables < 20:
                raise RuntimeError("Recovered schema is incomplete")
            return {"restore_verified": True, "schema_head": revision, "table_count": tables}
    finally:
        if decrypt is not None and decrypt.poll() is None:
            decrypt.kill()
            decrypt.wait()
        if restore is not None and restore.poll() is None:
            restore.kill()
            restore.wait()
        if destination is not None:
            destination.dispose()
        if created:
            with admin.connect() as conn:
                conn.execute(text("DROP DATABASE oneboard_restore_drill"))
        admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    args = parser.parse_args()
    print(drill(args.archive, args.identity, os.environ))


if __name__ == "__main__":
    main()
