"""Bootstrap the complete application schema in a versioned, reviewable migration.

Revision ID: 003_app_schema
Revises: 002_shared_login_throttle

Earlier migrations created only authentication and throttle tables. On a new
PostgreSQL database that left the remaining application schema absent despite
Alembic reporting "head". This migration adds missing model tables and records
which ones it created so downgrade does not delete pre-existing developer data.

Important: this is an initial bootstrap for the current model snapshot. Future
schema changes must be explicit Alembic revisions, not runtime create_all.
"""
from alembic import op
import sqlalchemy as sa

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.goals_tasks
import apps.api.models.entities
import apps.api.models.decision_evidence
import apps.api.models.agent_council
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.integrations

revision = "003_app_schema"
down_revision = "002_shared_login_throttle"
branch_labels = None
depends_on = None

_REGISTRY = "_oneboard_003_created_tables"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if _REGISTRY in inspector.get_table_names():
        raise RuntimeError("Unexpected migration 003 registry exists before upgrade")

    before = set(inspector.get_table_names())
    op.create_table(
        _REGISTRY,
        sa.Column("table_name", sa.String(128), primary_key=True),
    )
    # This is executed by Alembic inside the transaction and advisory lock,
    # never during normal production startup.
    Base.metadata.create_all(bind=connection, checkfirst=True)
    after = set(sa.inspect(connection).get_table_names())
    created = (after - before) - {_REGISTRY}
    for name in sorted(created):
        connection.execute(
            sa.text("INSERT INTO _oneboard_003_created_tables (table_name) VALUES (:name)"),
            {"name": name},
        )

    missing = set(Base.metadata.tables) - after
    if missing:
        raise RuntimeError("Application schema bootstrap incomplete: " + ", ".join(sorted(missing)))


def downgrade() -> None:
    connection = op.get_bind()
    if _REGISTRY not in sa.inspect(connection).get_table_names():
        raise RuntimeError("Cannot safely downgrade: migration 003 table registry is missing")

    rows = connection.execute(
        sa.text("SELECT table_name FROM _oneboard_003_created_tables")
    )
    created = {row[0] for row in rows}
    known = set(Base.metadata.tables)
    unknown = created - known
    if unknown:
        raise RuntimeError("Cannot safely downgrade unknown created tables: " + ", ".join(sorted(unknown)))

    # Reverse dependency order; never delete tables that existed before 003.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in created:
            op.drop_table(table.name)
    op.drop_table(_REGISTRY)
