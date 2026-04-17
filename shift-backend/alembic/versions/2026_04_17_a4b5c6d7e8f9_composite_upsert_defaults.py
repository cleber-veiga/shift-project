"""normalize composite blueprints with conflict_mode defaults

Adiciona explicitamente ``conflict_mode='insert'``, ``conflict_keys=[]`` e
``update_columns=None`` em cada passo de blueprints ja cadastrados em
``custom_node_definitions.blueprint``. Nao e estritamente necessario
(Pydantic aplica os mesmos defaults ao ler), mas deixa a representacao
armazenada coerente com a Fase 2 e simplifica inspecao/diagnostico.

Idempotente: so mexe em passos que ainda nao possuem ``conflict_mode``.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-04-17 15:00:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, blueprint FROM custom_node_definitions")
    ).fetchall()

    for row_id, blueprint in rows:
        if not isinstance(blueprint, dict):
            continue
        tables = blueprint.get("tables")
        if not isinstance(tables, list) or not tables:
            continue

        changed = False
        for step in tables:
            if not isinstance(step, dict):
                continue
            if "conflict_mode" not in step:
                step["conflict_mode"] = "insert"
                changed = True
            if "conflict_keys" not in step:
                step["conflict_keys"] = []
                changed = True
            if "update_columns" not in step:
                step["update_columns"] = None
                changed = True

        if changed:
            conn.execute(
                text(
                    "UPDATE custom_node_definitions "
                    "SET blueprint = CAST(:bp AS jsonb) WHERE id = :id"
                ),
                {"bp": _to_json(blueprint), "id": row_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, blueprint FROM custom_node_definitions")
    ).fetchall()

    for row_id, blueprint in rows:
        if not isinstance(blueprint, dict):
            continue
        tables = blueprint.get("tables")
        if not isinstance(tables, list) or not tables:
            continue

        changed = False
        for step in tables:
            if not isinstance(step, dict):
                continue
            for k in ("conflict_mode", "conflict_keys", "update_columns"):
                if k in step:
                    step.pop(k, None)
                    changed = True

        if changed:
            conn.execute(
                text(
                    "UPDATE custom_node_definitions "
                    "SET blueprint = CAST(:bp AS jsonb) WHERE id = :id"
                ),
                {"bp": _to_json(blueprint), "id": row_id},
            )


def _to_json(obj: object) -> str:
    import json
    return json.dumps(obj)
