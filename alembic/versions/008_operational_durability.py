"""Durable alert snapshots, idempotent local imports and indexed memory search.

Revision ID: 008_operational_durability
Revises: 007_workflow_idempotency

The original bootstrap migration uses current Base.metadata.create_all, so
fresh databases may already contain the new tables/indexes. Record *only*
objects created here to avoid destructive downgrades of preexisting schema.
"""
from alembic import op
import sqlalchemy as sa

revision = "008_operational_durability"
down_revision = "007_workflow_idempotency"
branch_labels = None
depends_on = None

REGISTRY = "_oneboard_008_created_schema"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if REGISTRY in inspector.get_table_names():
        raise RuntimeError("Migration 008 schema journal already exists")
    op.create_table(REGISTRY, sa.Column("name", sa.String(90), primary_key=True))

    def record(item):
        conn.execute(
            sa.text("INSERT INTO _oneboard_008_created_schema (name) VALUES (:name)"),
            {"name": item}
        )

    tables = set(sa.inspect(conn).get_table_names())
    if "alert_snapshots" not in tables:
        op.create_table(
            "alert_snapshots",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("business_id", sa.String(36), nullable=False),
            sa.Column("alert_key", sa.String(140), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("resolved_at", sa.DateTime()),
            sa.UniqueConstraint("business_id", "alert_key",
                                name="uq_alert_snapshot_tenant_key"),
        )
        record("alert_table")
    if "local_customer_imports" not in tables:
        op.create_table(
            "local_customer_imports",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("business_id", sa.String(36), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("source_name", sa.String(100), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("customer_ids", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("business_id", "idempotency_key",
                                name="uq_local_import_tenant_key"),
        )
        record("import_table")

    indexes = (
        ("alert_snapshots", "ix_alert_snapshot_tenant_active", ["business_id", "is_active"]),
        ("local_customer_imports", "ix_local_import_tenant_created", ["business_id", "created_at"]),
        ("memory_chunks", "ix_memory_chunks_business_created", ["business_id", "created_at"]),
    )
    for table, name, columns in indexes:
        if name not in {i["name"] for i in sa.inspect(conn).get_indexes(table)}:
            op.create_index(name, table, columns)
            record("index:" + name)
    if conn.dialect.name == "postgresql":
        name = "ix_memory_chunks_fts_simple"
        if name not in {i["name"] for i in sa.inspect(conn).get_indexes("memory_chunks")}:
            op.execute(
                "CREATE INDEX ix_memory_chunks_fts_simple ON memory_chunks "
                "USING GIN (to_tsvector('simple', content))"
            )
            record("index:" + name)


def downgrade():
    conn = op.get_bind()
    if REGISTRY not in sa.inspect(conn).get_table_names():
        raise RuntimeError("Missing migration 008 schema journal")
    records = {
        row[0] for row in conn.execute(
            sa.text("SELECT name FROM _oneboard_008_created_schema")
        ).all()
    }
    for index, table in (
        ("ix_memory_chunks_fts_simple", "memory_chunks"),
        ("ix_memory_chunks_business_created", "memory_chunks"),
        ("ix_local_import_tenant_created", "local_customer_imports"),
        ("ix_alert_snapshot_tenant_active", "alert_snapshots"),
    ):
        if "index:" + index in records:
            op.drop_index(index, table_name=table)
    if "import_table" in records:
        op.drop_table("local_customer_imports")
    if "alert_table" in records:
        op.drop_table("alert_snapshots")
    op.drop_table(REGISTRY)
