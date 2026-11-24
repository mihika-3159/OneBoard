"""Hash legacy API keys without exposing raw credentials in PostgreSQL.

Revision ID: 006_api_key_hashing
Revises: 005_auth_foreign_keys

Previous deployments stored API bearer credentials as plaintext in users.
This migration atomically replaces canonical generated keys with SHA-256
verifiers. Noncanonical plaintext credentials fail the migration; they must be
rotated or explicitly disabled by an authorized operator before production
startup. It never silently drops a user or silently accepts a weak key.

The irreversible conversion is intentionally guarded during rollback:
downgrading while hashed credentials exist would make old application code
unable to authenticate them. PostgreSQL refuses this unsafe rollback rather
than pretending that the plaintext credentials can be restored.
SQLite remains development-only; dev data are not a production migration.
"""
import hashlib
from alembic import op
import sqlalchemy as sa

revision = "006_api_key_hashing"
down_revision = "005_auth_foreign_keys"
branch_labels = None
depends_on = None


def _valid_raw_key(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 60
        and value.startswith("obk_")
        and all(ch in "0123456789abcdef" for ch in value[4:])
    )


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    rows = conn.execute(sa.text("SELECT id, api_key FROM users WHERE api_key IS NOT NULL")).all()
    for user_id, key in rows:
        if key.startswith("sha256:"):
            if len(key) != 71 or any(c not in "0123456789abcdef" for c in key[7:]):
                raise RuntimeError("Invalid stored API verifier; aborting credential migration")
            continue
        if not _valid_raw_key(key):
            # Legacy demo/synthetic keys have known formats or low entropy.
            # Do not silently hash and bless them for public production use.
            raise RuntimeError(
                "Noncanonical legacy plaintext API key found; rotate or disable "
                "it before applying migration 006"
            )
        verifier = "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()
        conn.execute(
            sa.text("UPDATE users SET api_key = :verifier WHERE id = :uid AND api_key = :old"),
            {"verifier": verifier, "uid": user_id, "old": key},
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    present = conn.execute(sa.text(
        "SELECT 1 FROM users WHERE api_key LIKE 'sha256:%' LIMIT 1"
    )).first()
    if present:
        raise RuntimeError(
            "Cannot downgrade irreversible API key hashing while active "
            "hashed keys exist; restore a reviewed backup and rotate "
            "credentials instead"
        )
