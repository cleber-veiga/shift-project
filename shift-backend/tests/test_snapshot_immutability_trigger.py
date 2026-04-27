"""
Teste de regressao do trigger de imutabilidade do snapshot.

Contexto
--------
A migration ``2026_04_25_a3b4c5d6e7f9_add_execution_template_snapshot`` cria
um trigger Postgres ``trg_workflow_executions_snapshot_immutable`` que
rejeita UPDATE em qualquer das tres colunas do snapshot
(``template_snapshot``, ``template_version``, ``rendered_at``).

Objetivo deste arquivo
----------------------
Garantir que o trigger CONTINUA disparando — uma migration futura que
remova o trigger por engano seria detectada por este teste, evitando
regressao silenciosa do contrato de imutabilidade.

Marker
------
``@pytest.mark.postgres``: requer Postgres real (o trigger e Postgres-only,
nao roda em SQLite). O teste faz skip automatico quando a ``DATABASE_URL``
nao aponta para Postgres ou quando o servidor nao esta acessivel.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    OperationalError,
    ProgrammingError,
)


# ---------------------------------------------------------------------------
# Skip helper
# ---------------------------------------------------------------------------


def _check_postgres_with_migrations() -> tuple[bool, str]:
    """Verifica que ``DATABASE_URL`` aponta para Postgres, o servidor responde
    E as migrations da Sprint estao aplicadas (coluna ``template_snapshot``
    existe + trigger ``trg_workflow_executions_snapshot_immutable`` ativo).

    Retorna ``(ok, motivo_skip)``. Se nao ok, ``motivo_skip`` explica o que
    falta — em CI, isso vira mensagem de skip clara em vez de erro silencioso.
    """
    try:
        from app.core.config import settings
        if "postgres" not in settings.DATABASE_URL.lower():
            return False, "DATABASE_URL nao aponta para Postgres"
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _check() -> tuple[bool, str]:
            engine = create_async_engine(settings.DATABASE_URL)
            try:
                async with engine.connect() as conn:
                    has_col = (
                        await conn.execute(
                            text(
                                "SELECT 1 FROM information_schema.columns "
                                "WHERE table_name = 'workflow_executions' "
                                "AND column_name = 'template_snapshot'"
                            )
                        )
                    ).scalar()
                    if not has_col:
                        return False, (
                            "coluna template_snapshot ausente — rode "
                            "``alembic upgrade head`` antes desta suite"
                        )
                    has_trig = (
                        await conn.execute(
                            text(
                                "SELECT 1 FROM pg_trigger "
                                "WHERE tgname = 'trg_workflow_executions_snapshot_immutable'"
                            )
                        )
                    ).scalar()
                    if not has_trig:
                        return False, (
                            "trigger trg_workflow_executions_snapshot_immutable "
                            "ausente — verifique a migration "
                            "2026_04_25_a3b4c5d6e7f9_add_execution_template_snapshot"
                        )
                    return True, ""
            finally:
                await engine.dispose()

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_check())
        finally:
            loop.close()
    except Exception as exc:  # noqa: BLE001
        return False, f"erro conectando ao Postgres: {exc}"


_PG_OK, _PG_SKIP_REASON = _check_postgres_with_migrations()
_REQUIRES_POSTGRES = pytest.mark.skipif(
    not _PG_OK, reason=f"Postgres + migrations indisponiveis: {_PG_SKIP_REASON}"
)


# ---------------------------------------------------------------------------
# Helpers de setup — minimo necessario para criar uma WorkflowExecution
# valida (FK a workflows -> projects -> workspaces -> organizations).
# ---------------------------------------------------------------------------


async def _seed_minimal_execution(session) -> uuid.UUID:
    """Insere via raw SQL um minimo de:
       organization -> workspace -> project -> workflow -> workflow_execution.

    Retorna o ``id`` da execucao criada.

    Usamos SQL puro para nao depender de defaults/cascades do ORM em
    modelos potencialmente alterados; o teste foca exclusivamente no
    comportamento do trigger.
    """
    org_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    exec_id = uuid.uuid4()

    await session.execute(
        text(
            """
            INSERT INTO organizations (id, name, created_at)
            VALUES (:id, :name, now())
            """
        ),
        {"id": org_id, "name": f"trig-{exec_id.hex[:6]}"},
    )
    await session.execute(
        text(
            """
            INSERT INTO workspaces (id, organization_id, name, created_at)
            VALUES (:id, :org_id, :name, now())
            """
        ),
        {
            "id": ws_id, "org_id": org_id,
            "name": f"ws-trig-{exec_id.hex[:6]}",
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO projects (id, workspace_id, name, created_at)
            VALUES (:id, :ws, :name, now())
            """
        ),
        {
            "id": proj_id, "ws": ws_id,
            "name": f"proj-trig-{exec_id.hex[:6]}",
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO workflows (
                id, name, project_id, definition, tags, status,
                is_template, is_published, created_at, updated_at
            )
            VALUES (
                :id, :name, :proj, '{}'::jsonb, '[]'::jsonb, 'draft',
                false, false, now(), now()
            )
            """
        ),
        {"id": wf_id, "name": f"wf-trig-{exec_id.hex[:6]}", "proj": proj_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO workflow_executions (
                id, workflow_id, status, triggered_by,
                template_snapshot, template_version, rendered_at,
                started_at, updated_at
            )
            VALUES (
                :id, :wf, 'COMPLETED', 'manual',
                :snap, :ver, :rendered,
                :rendered, :rendered
            )
            """
        ),
        {
            "id": exec_id,
            "wf": wf_id,
            "snap": '{"original": true}',
            "ver": "ORIGINAL_HASH_v1",
            "rendered": datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc),
        },
    )
    await session.commit()
    return exec_id


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.postgres
@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_snapshot_columns_are_immutable_via_db_trigger():
    """Trigger ``trg_workflow_executions_snapshot_immutable`` rejeita UPDATE
    em ``template_snapshot``, ``template_version`` e ``rendered_at``.

    Cobre os 3 campos isoladamente — uma migration futura que remova o
    trigger faria todas as 3 asserts falharem com `DID NOT RAISE`.
    """
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        exec_id = await _seed_minimal_execution(session)

    # Cada UPDATE roda em uma session limpa para nao herdar tx em estado
    # invalido apos o trigger abortar.

    # 1. UPDATE em template_snapshot deve falhar.
    async with async_session_factory() as session:
        with pytest.raises((IntegrityError, ProgrammingError, OperationalError, DBAPIError)):
            await session.execute(
                text(
                    "UPDATE workflow_executions "
                    "SET template_snapshot = :s "
                    "WHERE id = :id"
                ),
                {"s": '{"hacked": true}', "id": exec_id},
            )
            await session.commit()
        await session.rollback()

    # 2. UPDATE em template_version deve falhar.
    async with async_session_factory() as session:
        with pytest.raises((IntegrityError, ProgrammingError, OperationalError, DBAPIError)):
            await session.execute(
                text(
                    "UPDATE workflow_executions "
                    "SET template_version = :v "
                    "WHERE id = :id"
                ),
                {"v": "TAMPERED_HASH", "id": exec_id},
            )
            await session.commit()
        await session.rollback()

    # 3. UPDATE em rendered_at deve falhar.
    async with async_session_factory() as session:
        with pytest.raises((IntegrityError, ProgrammingError, OperationalError, DBAPIError)):
            await session.execute(
                text(
                    "UPDATE workflow_executions "
                    "SET rendered_at = :t "
                    "WHERE id = :id"
                ),
                {"t": datetime(2099, 1, 1, tzinfo=timezone.utc), "id": exec_id},
            )
            await session.commit()
        await session.rollback()

    # 4. Confirma que NENHUM dos valores mudou — leitura final.
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT template_snapshot, template_version, rendered_at "
                    "FROM workflow_executions WHERE id = :id"
                ),
                {"id": exec_id},
            )
        ).mappings().one()
        assert row["template_snapshot"] == {"original": True}
        assert row["template_version"] == "ORIGINAL_HASH_v1"
        assert row["rendered_at"].year == 2026

    # 5. UPDATE em colunas NAO protegidas (ex.: status) ainda funciona —
    # garante que o trigger nao bloqueia toda a tabela por engano.
    async with async_session_factory() as session:
        await session.execute(
            text(
                "UPDATE workflow_executions SET status = 'CANCELLED' "
                "WHERE id = :id"
            ),
            {"id": exec_id},
        )
        await session.commit()

    # Cleanup — apaga em ordem reversa de FK. workflow_executions cascateia
    # do workflow; workflow do project; project do workspace.
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM workflow_executions WHERE id = :id"),
            {"id": exec_id},
        )
        await session.execute(
            text("DELETE FROM workflows WHERE name LIKE 'wf-trig-%'"),
        )
        await session.execute(
            text("DELETE FROM projects WHERE name LIKE 'proj-trig-%'"),
        )
        await session.execute(
            text("DELETE FROM workspaces WHERE name LIKE 'ws-trig-%'"),
        )
        await session.execute(
            text("DELETE FROM organizations WHERE name LIKE 'trig-%'"),
        )
        await session.commit()
