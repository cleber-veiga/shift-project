"""
Servico de checkpoints de execucao de workflows.

Quando um no tem ``checkpoint_enabled=true``, o seu resultado e persistido
em banco + o arquivo DuckDB e copiado para um diretorio persistente.
Uma execucao de retry pode reutilizar esses checkpoints sem re-executar nos
ja concluidos com sucesso.

Fluxo de escrita:
  1. No completa com sucesso e tem checkpoint_enabled=true.
  2. ``save_checkpoint()`` copia arquivos .duckdb de /tmp para SHIFT_CHECKPOINT_DIR.
  3. Atualiza os caminhos no result_json e persiste em workflow_checkpoints.

Fluxo de leitura (retry):
  1. ``load_checkpoints(source_execution_id)`` carrega todos os registros.
  2. Retorna dict {node_id: result_json} com caminhos DuckDB persistentes.
  3. O runner injeta esses resultados como pinnedOutput antes de executar.

Limpeza:
  - ``cleanup_expired()`` remove registros expirados e seus arquivos DuckDB.
  - Chamado via APScheduler (1x por dia).
  - Ao completar um retry com sucesso, checkpoints da execucao fonte sao
    marcados como usados (used_by_execution_id) mas nao deletados ainda —
    a limpeza normal cuida deles quando expires_at for atingido.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.workflow import WorkflowCheckpoint

logger = get_logger(__name__)

# Pattern para detectar caminhos DuckDB temporarios no result_json
_TMP_SHIFT_RE = re.compile(r'(/tmp(?:/[^/]+)*/shift/executions/[^/"\s]+)')


def _checkpoint_dir(execution_id: str) -> Path:
    return Path(settings.SHIFT_CHECKPOINT_DIR) / execution_id


def _persist_duckdb_files(
    result: dict[str, Any],
    execution_id: str,
) -> dict[str, Any]:
    """Copia arquivos .duckdb referenciados no result para diretorio persistente.

    Retorna um novo dict com os caminhos atualizados para o local persistente.
    Arquivos ausentes sao ignorados com warning (tolerante a falhas parciais).
    """
    checkpoint_dir = _checkpoint_dir(execution_id)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    tmp_prefix = str(Path(tempfile.gettempdir()) / "shift" / "executions" / execution_id)
    persistent_prefix = str(checkpoint_dir)

    result_str = _json_dumps_for_replace(result)
    if tmp_prefix not in result_str:
        return result  # nenhum arquivo para copiar

    # Copia cada arquivo DuckDB referenciado
    matches = set(_TMP_SHIFT_RE.findall(result_str))
    for src_path_str in matches:
        src = Path(src_path_str)
        if not src.exists() or not src_path_str.startswith(tmp_prefix):
            continue
        relative = src.relative_to(tmp_prefix)
        dst = checkpoint_dir / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(src), str(dst))
            logger.debug(
                "checkpoint.duckdb_copied",
                src=str(src),
                dst=str(dst),
            )
        except OSError as exc:
            logger.warning(
                "checkpoint.duckdb_copy_failed",
                src=str(src),
                error=str(exc),
            )

    # Substitui prefixo nos caminhos do result
    updated_str = result_str.replace(tmp_prefix, persistent_prefix)
    return _json_loads_from_replace(updated_str)


def _json_dumps_for_replace(obj: Any) -> str:
    import json
    return json.dumps(obj, default=str)


def _json_loads_from_replace(s: str) -> Any:
    import json
    return json.loads(s)


def _compute_expires_at() -> datetime:
    days = settings.SHIFT_CHECKPOINT_EXPIRE_DAYS
    if days <= 0:
        # Nunca expira: data 100 anos no futuro
        return datetime.now(timezone.utc) + timedelta(days=36500)
    return datetime.now(timezone.utc) + timedelta(days=days)


async def save_checkpoint(
    execution_id: str,
    node_id: str,
    result: dict[str, Any],
) -> None:
    """Persiste o resultado de um no como checkpoint.

    Copia arquivos DuckDB para local persistente e grava registro em DB.
    Erros sao logados mas nao propagados — o workflow nao deve falhar por
    causa de um checkpoint.
    """
    try:
        persistent_result = _persist_duckdb_files(result, execution_id)
        expires_at = _compute_expires_at()

        async with async_session_factory() as session:
            # Upsert: se ja existir checkpoint para essa execucao/no, atualiza.
            existing = await session.execute(
                select(WorkflowCheckpoint).where(
                    WorkflowCheckpoint.source_execution_id == UUID(execution_id),
                    WorkflowCheckpoint.node_id == node_id,
                )
            )
            record = existing.scalar_one_or_none()
            if record is not None:
                record.result_json = persistent_result
                record.expires_at = expires_at
            else:
                record = WorkflowCheckpoint(
                    source_execution_id=UUID(execution_id),
                    node_id=node_id,
                    result_json=persistent_result,
                    expires_at=expires_at,
                )
                session.add(record)
            await session.commit()
            logger.info(
                "checkpoint.saved",
                execution_id=execution_id,
                node_id=node_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "checkpoint.save_failed",
            execution_id=execution_id,
            node_id=node_id,
            error=str(exc),
        )


async def load_checkpoints(
    source_execution_id: UUID,
) -> dict[str, Any]:
    """Carrega todos os checkpoints validos de uma execucao.

    Retorna {node_id: result_json} com caminhos DuckDB persistentes.
    Checkpoints com arquivo DuckDB ausente sao ignorados.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(WorkflowCheckpoint).where(
                WorkflowCheckpoint.source_execution_id == source_execution_id,
                WorkflowCheckpoint.expires_at > datetime.now(timezone.utc),
            )
        )
        records = result.scalars().all()

    checkpoints: dict[str, Any] = {}
    for record in records:
        # Valida que arquivos DuckDB referenciados ainda existem
        result_json = record.result_json or {}
        result_str = _json_dumps_for_replace(result_json)
        checkpoint_prefix = str(_checkpoint_dir(str(source_execution_id)))

        all_valid = True
        if checkpoint_prefix in result_str:
            for path_str in _TMP_SHIFT_RE.findall(result_str):
                if checkpoint_prefix in path_str and not Path(path_str).exists():
                    all_valid = False
                    logger.warning(
                        "checkpoint.duckdb_missing",
                        execution_id=str(source_execution_id),
                        node_id=record.node_id,
                        path=path_str,
                    )
                    break

        if all_valid:
            checkpoints[record.node_id] = result_json

    logger.info(
        "checkpoint.loaded",
        source_execution_id=str(source_execution_id),
        count=len(checkpoints),
    )
    return checkpoints


async def mark_checkpoints_used(
    source_execution_id: UUID,
    used_by_execution_id: UUID,
) -> None:
    """Marca todos os checkpoints de uma execucao como utilizados."""
    async with async_session_factory() as session:
        await session.execute(
            update(WorkflowCheckpoint)
            .where(WorkflowCheckpoint.source_execution_id == source_execution_id)
            .values(used_by_execution_id=used_by_execution_id)
        )
        await session.commit()


async def cleanup_expired() -> int:
    """Remove checkpoints expirados e seus arquivos DuckDB.

    Retorna o numero de registros removidos.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(WorkflowCheckpoint).where(
                WorkflowCheckpoint.expires_at <= datetime.now(timezone.utc)
            )
        )
        expired = result.scalars().all()

        count = 0
        for record in expired:
            # Remove arquivos DuckDB persistentes
            chk_dir = _checkpoint_dir(str(record.source_execution_id))
            if chk_dir.exists():
                try:
                    shutil.rmtree(str(chk_dir))
                except OSError as exc:
                    logger.warning(
                        "checkpoint.cleanup_dir_failed",
                        path=str(chk_dir),
                        error=str(exc),
                    )
            await session.delete(record)
            count += 1

        if count:
            await session.commit()
            logger.info("checkpoint.cleanup_expired", count=count)

    return count
