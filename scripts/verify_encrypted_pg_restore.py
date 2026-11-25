"""Disposable CI-only age-encrypted PostgreSQL round-trip, including real decryption.

Refuse non-CI URLs, preexisting restore targets, customer data, or missing
explicit flag. This verifies the operator tooling; it is NOT offsite recovery.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from sqlalchemy.engine import make_url

from scripts.operations.backup_encrypted import backup, verify_manifest
from scripts.operations.test_encrypted_restore import drill


def verify_encrypted_roundtrip() -> dict:
    source = os.environ.get("ONEBOARD_TEST_POSTGRES_URL", "")
    if (os.environ.get("ONEBOARD_CI_ENCRYPTED_RESTORE") != "1"
            or os.environ.get("DATABASE_URL") != source):
        raise RuntimeError("Only explicit, matching disposable CI connections are permitted")
    parsed = make_url(source)
    if (parsed.drivername != "postgresql+psycopg"
            or parsed.host not in ("127.0.0.1", "localhost")
            or parsed.database != "oneboard_ci"
            or parsed.username != "oneboard_ci"):
        raise RuntimeError("Encrypted restore refuses non-disposable PostgreSQL")
    for executable in ("age", "age-keygen", "pg_dump", "pg_restore"):
        if not shutil.which(executable):
            raise RuntimeError("Missing required executable: " + executable)

    with tempfile.TemporaryDirectory(prefix="oneboard-synthetic-encrypted-") as name:
        folder = Path(name)
        folder.chmod(0o700)
        identity = folder / "synthetic-age-identity.txt"
        proc = subprocess.run(
            ["age-keygen", "-o", str(identity)], capture_output=True, timeout=20,
        )
        if proc.returncode:
            raise RuntimeError("Could not generate disposable encryption key")
        identity.chmod(0o600)
        recipient = subprocess.run(
            ["age-keygen", "-y", str(identity)], capture_output=True,
            text=True, timeout=20, check=True,
        ).stdout.strip()

        backup_env = dict(os.environ, ONEBOARD_PRODUCTION_MODE="true",
                          ONEBOARD_BACKUP_OPERATION_APPROVED="YES")
        archive, manifest = backup(folder, recipient, backup_env)
        verify_manifest(archive, manifest)
        scratch = parsed.set(database="oneboard_restore_drill").render_as_string(
            hide_password=False
        )
        restore_env = dict(os.environ, ONEBOARD_RESTORE_DRILL_APPROVED="YES",
                           ONEBOARD_RESTORE_SCRATCH_URL=scratch)
        report = drill(archive, identity, restore_env)
        if not report["restore_verified"] or report["schema_head"] != "013_batch_e_retention":
            raise RuntimeError("Encrypted decryption and restore failed")
        if report["table_count"] < 20:
            raise RuntimeError("Recovered schema incomplete")
        return report


if __name__ == "__main__":
    result = verify_encrypted_roundtrip()
    print("Disposable age-encrypted PostgreSQL backup/decryption/restore passed")
    print("Schema:", result["schema_head"], "tables:", result["table_count"])
    print("Offsite recovery, independent key custody and retention NOT VERIFIED")
