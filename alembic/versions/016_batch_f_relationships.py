"""Enforce explicit record references without deleting legacy data."""
from alembic import op
import sqlalchemy as sa
revision="016_batch_f_relationships"
down_revision="015_batch_f_context"
branch_labels=None
depends_on=None
RELATIONS=(
    ("memory_chunks","semantic_vectors","chunk_id","vector_chunk","CASCADE"),
    ("invoices","settlement_evidence","invoice_id","settlement_invoice","NO ACTION"),
    ("customers","invoices","customer_id","invoice_customer","NO ACTION"),
    ("customers","support_tickets","customer_id","ticket_customer","NO ACTION"),
    ("goals","tasks","goal_id","task_goal","NO ACTION"),
    ("decisions","tasks","decision_id","task_decision","NO ACTION"),
    ("tasks","approval_requests","task_id","approval_task","NO ACTION"),
    ("workflow_runs","workflow_schedules","last_run_id","schedule_run","NO ACTION"),
    ("users","user_sessions","user_id","session_user","CASCADE"),
)
def upgrade():
    conn=op.get_bind()
    if conn.dialect.name!="postgresql": return
    for parent in sorted({item[0] for item in RELATIONS}-{"users","workflow_runs"}):
        op.execute(f"ALTER TABLE {parent} ADD CONSTRAINT uq_f16_{parent}_tenant_id UNIQUE (business_id,id)")
    for parent,child,column,key,delete in RELATIONS:
        name="fk_f16_"+key
        op.execute(f"ALTER TABLE {child} ADD CONSTRAINT {name} FOREIGN KEY (business_id,{column}) REFERENCES {parent}(business_id,id) ON DELETE {delete} NOT VALID")
        count=conn.execute(sa.text(f"SELECT count(*) FROM {child} c LEFT JOIN {parent} p ON p.id=c.{column} AND p.business_id=c.business_id WHERE c.{column} IS NOT NULL AND p.id IS NULL")).scalar_one()
        if not count:
            op.execute(f"ALTER TABLE {child} VALIDATE CONSTRAINT {name}")
    op.execute("ALTER TABLE sync_history ADD CONSTRAINT fk_f16_sync_parent FOREIGN KEY (integration_id) REFERENCES integration_accounts(id) ON DELETE CASCADE NOT VALID")
    if not conn.execute(sa.text("SELECT 1 FROM sync_history s LEFT JOIN integration_accounts i ON s.integration_id=i.id WHERE i.id IS NULL LIMIT 1")).first():
        op.execute("ALTER TABLE sync_history VALIDATE CONSTRAINT fk_f16_sync_parent")
def downgrade():
    if op.get_bind().dialect.name!="postgresql": return
    op.execute("ALTER TABLE sync_history DROP CONSTRAINT fk_f16_sync_parent")
    for parent,child,column,key,delete in reversed(RELATIONS):
        op.execute(f"ALTER TABLE {child} DROP CONSTRAINT fk_f16_{key}")
    for parent in sorted({item[0] for item in RELATIONS}-{"users","workflow_runs"}):
        op.execute(f"ALTER TABLE {parent} DROP CONSTRAINT uq_f16_{parent}_tenant_id")
