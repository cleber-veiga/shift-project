"""fix workflow_executions cascade delete

Revision ID: f1a2b3c4d5e6
Revises: eb2f82754acd
Create Date: 2026-04-16 00:00:00.000000

"""

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Re-cria o FK com ON DELETE CASCADE para que exclusões de workflows
    # removam automaticamente os registros de workflow_executions no banco.
    op.drop_constraint(
        "workflow_executions_workflow_id_fkey",
        "workflow_executions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "workflow_executions_workflow_id_fkey",
        "workflow_executions",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "workflow_executions_workflow_id_fkey",
        "workflow_executions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "workflow_executions_workflow_id_fkey",
        "workflow_executions",
        "workflows",
        ["workflow_id"],
        ["id"],
    )
