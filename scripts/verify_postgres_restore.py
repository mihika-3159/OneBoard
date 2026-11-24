"""Disposable PostgreSQL 16 logical backup/restore drill for GitHub CI.

WARNING: This is intentionally NOT a production backup or restore program.
It refuses remote hosts, other database names, and runs without a separate
disposable-CI confirmation flag. A real customer's backup must never be
created, downloaded or restored by this tool.

The drill takes a consistent pg_dump -Fc backup, verifies its SHA-256,
restores it into a fresh oneboard_restore_ci database, compares full per-table
row digests, checks Alembic heads, and drops only the database it created.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

SOURCE_DB = "oneboard_ci"
RESTORE_DB = "oneboard_restore_ci"


def checked_disposable_url():
    source = os.environ.get("ONEBOARD_TEST_POSTGRES_URL", "")
    if os.environ.get("ONEBOARD_CI_DISPOSABLE_RESTORE") != "1":
        raise RuntimeError("Disposable restore confirmation was not provided")
    if not source or os.environ.get("DATABASE_URL") != source:
        raise RuntimeError("Source and migration URLs must match the disposable CI database")
    url = make_url(source)
    if (url.drivername != "postgresql+psycopg"
            or url.host not in ("localhost", "127.0.0.1", "::1")
            or url.database != SOURCE_DB
            or not url.username
            or not url.password):
        raise RuntimeError("Refusing backup/restore outside localhost oneboard_ci")
    return url


def _environment(url):
    env = dict(os.environ)
    env["PGPASSWORD"] = url.password
    env["PGCONNECT_TIMEOUT"] = "10"
    return env


def _run_command(args, env):
    completed = subprocess.run(
        args, env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )
    if completed.returncode:
        # Never print command arguments or potentially credential-bearing
        # subprocess logs. No real provider or customer data are involved.
        raise RuntimeError(
            "Disposable PostgreSQL backup/restore command failed: "
            + str(args[0])
            + " exited " + str(completed.returncode)
        )


def verify_backup_manifest(archive: Path, manifest: Path) -> None:
    """Fail closed before restore if the archive differs from its manifest."""
    try:
        metadata = json.loads(manifest.read_text())
        expected = metadata["archive_sha256"]
        if (metadata.get("source_database") != SOURCE_DB or
                not isinstance(expected, str) or len(expected) != 64 or
                any(ch not in "0123456789abcdef" for ch in expected)):
            raise ValueError("Unsafe backup manifest")
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("Corrupted backup archive")
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise RuntimeError("Backup integrity verification failed") from exc


def _table_hashes(connection):
    """Hash every row of every public application table without exposing data."""
    metadata = MetaData()
    metadata.reflect(bind=connection, schema="public")
    output = {}
    for table in sorted(metadata.tables.values(), key=lambda item: item.name):
        if table.name.startswith("pg_") or table.name == "alembic_version":
            continue
        pks = list(table.primary_key.columns)
        query = select(table)
        if pks:
            query = query.order_by(*pks)
        rows = connection.execute(query).mappings().all()
        digest = hashlib.sha256()
        for row in rows:
            record = json.dumps(dict(row), default=str, sort_keys=True, separators=(",", ":"))
            digest.update(record.encode("utf-8"))
            digest.update(b"\n")
        output[table.name] = {"count": len(rows), "sha256": digest.hexdigest()}
    return output


def verify_disposable_restore():
    url = checked_disposable_url()
    for executable in ("pg_dump", "pg_restore"):
        if not shutil.which(executable):
            raise RuntimeError(f"Missing PostgreSQL client executable: {executable}")
    env = _environment(url)
    src = create_engine(url, pool_pre_ping=True)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    dest = None
    created_restore = False
    try:
        with admin.connect() as conn:
            present = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": RESTORE_DB},
            ).first()
            if present:
                raise RuntimeError(
                    "Restore destination already exists; refusing to modify it"
                )
        with src.connect() as conn:
            from alembic.migration import MigrationContext
            revision = MigrationContext.configure(conn).get_current_heads()
            if revision != ("007_workflow_idempotency",):
                raise RuntimeError("Disposable source must be fully migrated")
        with tempfile.TemporaryDirectory(prefix="oneboard-ci-recovery-") as temp:
            directory = Path(temp)
            archive = directory / "database.dump"
            manifest = directory / "manifest.json"
            args = [
                "pg_dump", "--format=custom", "--no-owner", "--no-acl",
                "--host", url.host, "--port", str(url.port or 5432),
                "--username", url.username, "--dbname", SOURCE_DB,
                "--file", str(archive),
            ]
            _run_command(args, env)
            archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps({"archive_sha256": archive_digest, "source_database": SOURCE_DB})
            )
            verify_backup_manifest(archive, manifest)
            with admin.connect() as conn:
                conn.execute(text("CREATE DATABASE oneboard_restore_ci"))
                created_restore = True
            dest_url = url.set(database=RESTORE_DB)
            _run_command([
                "pg_restore", "--no-owner", "--no-acl",
                "--host", url.host, "--port", str(url.port or 5432),
                "--username", url.username, "--dbname", RESTORE_DB,
                str(archive),
            ], env)
            dest = create_engine(dest_url, pool_pre_ping=True)
            with src.connect() as source_conn, dest.connect() as dest_conn:
                original = _table_hashes(source_conn)
                restored = _table_hashes(dest_conn)
                if original != restored:
                    raise RuntimeError("Restored table rows differ from the source snapshot")
                from alembic.migration import MigrationContext
                restore_revision = MigrationContext.configure(
                    dest_conn
                ).get_current_heads()
                if restore_revision != ("007_workflow_idempotency",):
                    raise RuntimeError("Restore lost the Alembic revision")
                # Integrity constraints and lookup indexes must be present.
                from apps.api.core.database import Base
                import apps.api.models.business
                import apps.api.models.entities
                import apps.api.models.workflow
                import apps.api.models.goals_tasks
                import apps.api.models.decision_evidence
                import apps.api.models.agent_council
                import apps.api.models.memory
                import apps.api.models.integrations
                inspector = inspect(dest_conn)
                for table_name, model in Base.metadata.tables.items():
                    if table_name not in restored:
                        raise RuntimeError("Restore missing model table " + table_name)
                    existing_indexes = inspector.get_indexes(table_name)
                    existing_uniques = inspector.get_unique_constraints(table_name)
                    for constraint in model.constraints:
                        from sqlalchemy import UniqueConstraint
                        if isinstance(constraint, UniqueConstraint):
                            cols = sorted(col.name for col in constraint.columns)
                            if not any(
                                sorted(item["column_names"]) == cols
                                for item in existing_uniques + [
                                    idx for idx in existing_indexes if idx.get("unique")
                                ]
                            ):
                                raise RuntimeError("Restore missing unique constraint")
            print(
                "Disposable PostgreSQL backup/restore verified: "
                + str(len(restored)) + " application tables, "
                + str(sum(row["count"] for row in restored.values()))
                + " records, SHA-256 validated, schema head 007"
            )
    finally:
        if dest is not None:
            dest.dispose()
        if created_restore:
            with admin.connect() as conn:
                # Only a database created by this process may be deleted.
                conn.execute(text("DROP DATABASE oneboard_restore_ci"))
        src.dispose()
        admin.dispose()


if __name__ == "__main__":
    verify_disposable_restore()
