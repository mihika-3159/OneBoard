"""initial auth and tenant isolation

Revision ID: 001_auth_isolation
Revises: 
Create Date: 2026-10-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = '001_auth_isolation'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    # 1. Create users table if not exists
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=50), server_default="founder"),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default="1"),
            sa.Column("api_key", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_index("ix_users_api_key", "users", ["api_key"], unique=True)
        op.create_index("ix_users_business_id", "users", ["business_id"])

    # 2. Create business_memberships table if not exists
    if "business_memberships" not in tables:
        op.create_table(
            "business_memberships",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=50), server_default="founder"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_memberships_user_id", "business_memberships", ["user_id"])
        op.create_index("ix_memberships_business_id", "business_memberships", ["business_id"])

    # 3. Create user_sessions table if not exists
    if "user_sessions" not in tables:
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("is_revoked", sa.Boolean(), server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_sessions_user_id", "user_sessions", ["user_id"])
        op.create_index("ix_sessions_is_revoked", "user_sessions", ["is_revoked"])

    # 4. Add owner_id to businesses if missing
    if "businesses" in tables:
        cols = [col["name"] for col in inspector.get_columns("businesses")]
        if "owner_id" not in cols:
            op.add_column("businesses", sa.Column("owner_id", sa.String(length=36), nullable=True))

    # 5. Add updated_at to users if missing
    if "users" in tables:
        u_cols = [col["name"] for col in inspector.get_columns("users")]
        if "updated_at" not in u_cols:
            op.add_column("users", sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_table("user_sessions")
    op.drop_table("business_memberships")
    op.drop_table("users")
