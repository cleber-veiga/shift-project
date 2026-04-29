"""add plan_snapshot to workflow_executions

Revision ID: e9f0a1b2c3d4
Revises: c5d6e7f8a0b1
Create Date: 2026-04-28

Adiciona coluna JSONB plan_snapshot em workflow_executions para persistir
o ExecutionPlanSnapshot (topological levels, node_count, edge_count,
predicted_strategies) logo após o topological sort, antes de qualquer
nó rodar.

Permite auditar o plano previsto vs comportamento real e validar heurísticas
do StrategyObserver (Fase 4) antes da Fase 5 ativá-las.

Nota: revision ID original (a1b2c3d4e5f6) colidia com migration existente
2026_04_13_a1b2c3d4e5f6_add_full_name_to_users; renomeado para e9f0a1b2c3d4.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e9f0a1b2c3d4"
down_revision = "c5d6e7f8a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column(
            "plan_snapshot",
            JSONB,
            nullable=True,
            comment=(
                "ExecutionPlanSnapshot: topological levels, node_count, edge_count, "
                "predicted_strategies. Capturado antes do primeiro nó rodar."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_executions", "plan_snapshot")
