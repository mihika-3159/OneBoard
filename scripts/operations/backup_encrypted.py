"""Explicitly approved, age-encrypted PostgreSQL backup, never an automatic job.

Imports and --verify are offline. --backup needs owner approval and a production
PostgreSQL DSN; plaintext is piped directly from pg_dump into age encryption.
This does not provide offsite retention, a restore drill or an SLA.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from sqlalchemy.engine import make_url


def _pg_environment(source: dict[str, str]) -> dict[str, str]:
    if (source.get("ONEBOARD_BACKUP_OPERATION_APPROVED") != "YES"
            or source.get("ONEBOARD_PRODUCTION_MODE", "").lower() not in ("true", "1")):
        raise RuntimeError("Explicit production backup approval is required")
    url = make_url(source.get("DATABASE_URL", ""))
    if (not url.drivername.startswith("postgresql") or not url.database
            or not url.host or not url.username or not url.password):
        raise RuntimeError("A complete PostgreSQL DATABASE_URL is required")
    if (url.host not in ("localhost", "127.0.0.1", "::1")
            and url.query.get("sslmode") != "verify-full"):
        raise RuntimeError("Remote PostgreSQL backup requires sslmode=verify-full")
    env = dict(os.environ)
    env.update(PGHOST=url.host, PGPORT=str(url.port or 5432),
               PGDATABASE=url.database, PGUSER=url.username,
               PGPASSWORD=url.password, PGSSLMODE=url.query.get("sslmode", "prefer"))
    for field in ("sslrootcert", "sslcert", "sslkey"):
        if field in url.query:
            env["PG" + field.upper()] = str(url.query[field])
    return env


def verify_manifest(archive: Path, manifest: Path) -> dict:
    if any(path.is_symlink() or not path.is_file() for path in (archive, manifest)):
        raise RuntimeError("Backup archive and manifest must be regular non-symlink files")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    expected = record.get("sha256")
    if (record.get("format") != "age-encrypted-pg-custom-v1"
            or record.get("filename") != archive.name
            or not isinstance(expected, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected)):
        raise RuntimeError("Invalid encrypted backup manifest")
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(piece)
    if archive.stat().st_size == 0 or digest.hexdigest() != expected:
        raise RuntimeError("Encrypted archive integrity mismatch")
    return record


def backup(directory: Path, recipient: str, source: dict[str, str]) -> tuple[Path, Path]:
    env = _pg_environment(source)  # Fail closed before changing files.
    if not re.fullmatch(r"age1[a-z0-9]{50,90}", recipient):
        raise RuntimeError("Expected an age public recipient, not a private key")
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise RuntimeError("Use a pre-existing private (0700), non-symlink backup directory")
    name = ("oneboard-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-" + os.urandom(4).hex() + ".dump.age")
    archive, manifest = directory / name, directory / (name + ".json")
    old_mask = os.umask(0o077)
    temporary = None
    dump = encrypt = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".oneboard-cipher-", dir=directory)
        temporary = Path(temp_name)
        with os.fdopen(fd, "wb") as output:
            dump = subprocess.Popen(
                ["pg_dump", "--format=custom", "--no-owner", "--no-acl"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
            )
            encrypt = subprocess.Popen(
                ["age", "--encrypt", "--recipient", recipient],
                stdin=dump.stdout, stdout=output, stderr=subprocess.DEVNULL
            )
            if dump.stdout is not None:
                dump.stdout.close()
            try:
                dumped = dump.wait(timeout=900)
                encrypted = encrypt.wait(timeout=900)
            except subprocess.TimeoutExpired:
                dump.kill()
                encrypt.kill()
                dump.wait()
                encrypt.wait()
                raise RuntimeError("Encrypted backup timed out") from None
            if dumped or encrypted:
                raise RuntimeError("PostgreSQL backup or age encryption failed")
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size < 32:
            raise RuntimeError("Encrypted backup is incomplete")
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            for piece in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(piece)
        # Never overwrite an existing backup, even under a concurrent run.
        os.link(temporary, archive, follow_symlinks=False)
        manifest_created = False
        try:
            metadata = dict(
                format="age-encrypted-pg-custom-v1", filename=name,
                sha256=digest.hexdigest(),
                created_utc=datetime.now(timezone.utc).isoformat(),
                verified_restore=False, offsite_replicated=False
            )
            with manifest.open("x", encoding="utf-8") as handle:
                manifest_created = True
                os.chmod(manifest, 0o600)
                json.dump(metadata, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            verify_manifest(archive, manifest)
        except Exception:
            archive.unlink(missing_ok=True)
            if manifest_created:
                manifest.unlink(missing_ok=True)
            raise
        return archive, manifest
    finally:
        if dump is not None and dump.poll() is None:
            dump.kill()
            dump.wait()
        if encrypt is not None and encrypt.poll() is None:
            encrypt.kill()
            encrypt.wait()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.umask(old_mask)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--backup", action="store_true")
    operation.add_argument("--verify", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--recipient", help="age PUBLIC encryption key")
    args = parser.parse_args()
    if args.verify is not None:
        verify_manifest(args.verify, Path(str(args.verify) + ".json"))
        print("Ciphertext hash verified; decryption and restore NOT tested")
        return
    if args.directory is None or not args.recipient:
        parser.error("--backup requires --directory and --recipient")
    archive, manifest = backup(args.directory, args.recipient, os.environ)
    print("Encrypted backup written; offsite copy/restore UNVERIFIED:", archive.name, manifest.name)


if __name__ == "__main__":
    main()
