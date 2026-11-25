"""Restore referential integrity omitted by the legacy authentication migration.

Revision ID: 005_auth_foreign_keys
Revises: 004_schema_indexes

Migration 001 created users, business_memberships, and user_sessions without
the foreign keys present in the SQLAlchemy models. A database can be stamped
at head while allowing orphan membership or session rows. This PostgreSQL
migration adds the missing constraints without rewriting customer data.
Dirty legacy data deliberately fails the migration rather than being deleted.

SQLite is development-only: SQLite ALTER TABLE cannot add these constraints
in place. New development databases use the ORM schema; production startup
requires PostgreSQL and validates actual constraints.
"""
from alembic import op
import sqlalchemy as sa

revision = "005_auth_foreign_keys"
down_revision = "004_schema_indexes"
branch_labels = None
depends_on = None

_REGISTRY = "_oneboard_005_created_fks"
_REQUIRED = (
    ("users", "business_id", "businesses", "id", "fk_oneboard_users_business"),
    ("business_memberships", "user_id", "users", "id", "fk_oneboard_memberships_user"),
    ("business_memberships", "business_id", "businesses", "id", "fk_oneboard_memberships_business"),
    ("user_sessions", "user_id", "users", "id", "fk_oneboard_sessions_user"),
)


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    if _REGISTRY in sa.inspect(connection).get_table_names():
        raise RuntimeError("Unexpected migration 005 constraint registry already exists")
    op.create_table(
        _REGISTRY,
        sa.Column("table_name", sa.String(128), nullable=False),
        sa.Column("constraint_name", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("table_name", "constraint_name"),
    )
    for table_name, local_column, parent, remote_column, constraint_name in _REQUIRED:
        reflected = sa.inspect(connection).get_foreign_keys(table_name)
        matching = [
            fk for fk in reflected
            if fk.get("constrained_columns") == [local_column]
            and fk.get("referred_table") == parent
            and fk.get("referred_columns") == [remote_column]
        ]
        if matching:
            if not any(
                (fk.get("options") or {}).get("ondelete", "").upper() == "CASCADE"
                for fk in matching
            ):
                raise RuntimeError(
                    f"Existing {table_name}.{local_column} FK lacks required ON DELETE CASCADE"
                )
            continue
        # PostgreSQL validates every existing row when ADD CONSTRAINT runs.
        # A missing parent is a deployment blocker, not permission to discard
        # tenant data or add an unvalidated NOT VALID constraint.
        op.create_foreign_key(
            constraint_name,
            table_name,
            parent,
            [local_column],
            [remote_column],
            ondelete="CASCADE",
        )
        connection.execute(
            sa.text(
                "INSERT INTO _oneboard_005_created_fks (table_name, constraint_name) "
                "VALUES (:table, :constraint)"
            ),
            {"table": table_name, "constraint": constraint_name},
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    if _REGISTRY not in sa.inspect(connection).get_table_names():
        raise RuntimeError("Cannot safely downgrade migration 005 without constraint registry")
    created = connection.execute(
        sa.text(
            "SELECT table_name, constraint_name FROM _oneboard_005_created_fks "
            "ORDER BY table_name, constraint_name"
        )
    ).all()
    for table_name, constraint_name in reversed(created):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
    op.drop_table(_REGISTRY)
