"""
Servico de cache persistente para nos de extracao (Sprint 4.4).

Armazena o resultado de nos de extracao (sql_database, csv_input, etc.)
em banco (tabela ``shift_extract_cache``) com os arquivos DuckDB copiados
para ``SHIFT_EXTRACT_CACHE_DIR``. Em cache hit, o arquivo e copiado de
volta para o diretorio temporario da execucao corrente e os caminhos no
result_json sao atualizados.

Integracao com o runner (dynamic_runner.py)
-------------------------------------------
O runner chama ``make_cache_key(node_data)`` para obter a chave determinista
do no. Antes de despachar o processador, chama ``get(cache_key, execution_id,
node_id)`` — em cache hit, usa o resultado sem executar o no. Apos execucao
bem-sucedida de um no com ``cache_enabled=True``, chama
``save(cache_key, result, node_type, ttl_seconds, execution_id)`` em background.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Campos excluidos do hash de cache (runtime-only ou controle de cache)
_HASH_EXCLUDE_KEYS = frozenset({
    "connection_string",   # resolvido em runtime, nao deve mudar a semantica
    "pinnedOutput",        # UI state
    "checkpoint_enabled",  # nao afeta o output
    "cache_enabled",       # nao afeta o output
    "cache_ttl_seconds",   # nao afeta o output
    "enabled",             # nao afeta o output quando True
    "label",               # UI label
    "description",         # UI
})

# Regex para encontrar caminhos de DuckDB no result_json (adaptado do checkpoint_service)
_CACHE_DIR_RE = re.compile(r'"([^"]+shift[/\\]extract_cache[/\\][^"]+\.duckdb[^"]*)"')


def _cache_dir() -> Path:
    p = Path(settings.SHIFT_EXTRACT_CACHE_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _entry_dir(cache_key: str) -> Path:
    return _cache_dir() / cache_key


class ExtractCacheService:
    """Servico de cache de extracoes."""

    # -----------------------------------------------------------------------
    # Chave de cache
    # -----------------------------------------------------------------------

    def make_cache_key(self, node_data: dict[str, Any]) -> str:
        """Computa SHA-256 dos campos deterministas do config do no.

        Exclui campos runtime-only (_HASH_EXCLUDE_KEYS) para que a mesma
        query com a mesma conexao sempre produza a mesma chave,
        independente de metadados de UI.
        """
        filtered = {
            k: v
            for k, v in node_data.items()
            if k not in _HASH_EXCLUDE_KEYS
        }
        key_bytes = json.dumps(filtered, sort_keys=True, default=str).encode()
        return hashlib.sha256(key_bytes).hexdigest()

    # -----------------------------------------------------------------------
    # Lookup (cache hit)
    # -----------------------------------------------------------------------

    async def get(
        self,
        cache_key: str,
        execution_id: str,
        node_id: str,
    ) -> dict[str, Any] | None:
        """Retorna o result_json do cache com caminhos DuckDB atualizados.

        Returns None quando:
        - Entrada nao existe ou expirou
        - Arquivo DuckDB foi removido
        - Qualquer erro inesperado (logado, nao levantado)
        """
        try:
            from app.db.session import async_session_factory
            from app.models.extract_cache import ExtractCache
            from sqlalchemy import select, update

            now = datetime.now(timezone.utc)
            async with async_session_factory() as session:
                row = (
                    await session.execute(
                        select(ExtractCache).where(
                            ExtractCache.cache_key == cache_key,
                            ExtractCache.expires_at > now,
                        )
                    )
                ).scalar_one_or_none()

                if row is None:
                    return None

                persistent_dir = _entry_dir(cache_key)
                result_str = json.dumps(row.result_json, default=str)

                # Verifica se ao menos um arquivo DuckDB existe
                if not any(persistent_dir.glob("*.duckdb")):
                    logger.info(
                        "extract_cache.miss.file_missing",
                        cache_key=cache_key,
                    )
                    return None

                # Copia arquivos DuckDB para o dir de execucao e atualiza caminhos
                exec_dir = Path(tempfile.gettempdir()) / "shift" / "executions" / execution_id
                exec_dir.mkdir(parents=True, exist_ok=True)

                persistent_prefix = str(persistent_dir)
                exec_prefix = str(exec_dir)

                for src in persistent_dir.glob("*.duckdb"):
                    dst = exec_dir / src.name
                    if not dst.exists():
                        shutil.copy2(src, dst)
                    for wal in persistent_dir.glob(f"{src.name}.wal"):
                        shutil.copy2(wal, exec_dir / wal.name)

                updated_str = result_str.replace(persistent_prefix, exec_prefix)
                result = json.loads(updated_str)
                result["_is_cache_hit"] = True

                # Incrementa hit_count em background (sem bloquear o caller)
                await session.execute(
                    update(ExtractCache)
                    .where(ExtractCache.cache_key == cache_key)
                    .values(hit_count=ExtractCache.hit_count + 1)
                )
                await session.commit()

            logger.info(
                "extract_cache.hit",
                cache_key=cache_key[:16],
                execution_id=execution_id,
                node_id=node_id,
            )
            return result

        except Exception:  # noqa: BLE001
            logger.exception("extract_cache.get_failed", cache_key=cache_key[:16])
            return None

    # -----------------------------------------------------------------------
    # Persistencia (cache miss → save)
    # -----------------------------------------------------------------------

    async def save(
        self,
        cache_key: str,
        result: dict[str, Any],
        node_type: str,
        ttl_seconds: int,
        execution_id: str,
    ) -> None:
        """Copia arquivos DuckDB para cache dir e persiste o result_json.

        Erros sao logados e nao levantados — cache e best-effort.
        Usa UPSERT (ON CONFLICT DO UPDATE) para atualizar entradas existentes.
        """
        try:
            exec_dir = Path(tempfile.gettempdir()) / "shift" / "executions" / execution_id
            persistent_dir = _entry_dir(cache_key)
            persistent_dir.mkdir(parents=True, exist_ok=True)

            exec_prefix = str(exec_dir)
            persistent_prefix = str(persistent_dir)

            result_str = json.dumps(result, default=str)

            # Copia DuckDB files do dir de execucao para o cache persistente
            for path_match in re.finditer(r'"([^"]+\.duckdb[^"]*)"', result_str):
                src_path = Path(path_match.group(1))
                if src_path.is_file() and exec_prefix in str(src_path):
                    dst_path = persistent_dir / src_path.name
                    shutil.copy2(src_path, dst_path)
                    for wal in exec_dir.glob(f"{src_path.name}.wal"):
                        shutil.copy2(wal, persistent_dir / wal.name)

            # Atualiza caminhos no result_json
            updated_str = result_str.replace(exec_prefix, persistent_prefix)
            # Remove flag de cache hit antes de persistir
            result_to_store = json.loads(updated_str)
            result_to_store.pop("_is_cache_hit", None)

            from app.db.session import async_session_factory
            from app.models.extract_cache import ExtractCache
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl_seconds)

            async with async_session_factory() as session:
                stmt = (
                    pg_insert(ExtractCache)
                    .values(
                        cache_key=cache_key,
                        node_type=node_type,
                        result_json=result_to_store,
                        expires_at=expires_at,
                        created_at=now,
                        hit_count=0,
                    )
                    .on_conflict_do_update(
                        index_elements=["cache_key"],
                        set_={
                            "result_json": result_to_store,
                            "expires_at": expires_at,
                            "created_at": now,
                            "hit_count": 0,
                        },
                    )
                )
                await session.execute(stmt)
                await session.commit()

            logger.info(
                "extract_cache.saved",
                cache_key=cache_key[:16],
                node_type=node_type,
                ttl_seconds=ttl_seconds,
            )

        except Exception:  # noqa: BLE001
            logger.exception("extract_cache.save_failed", cache_key=cache_key[:16])

    # -----------------------------------------------------------------------
    # Invalidacao manual
    # -----------------------------------------------------------------------

    async def invalidate(
        self,
        cache_key: str | None = None,
        node_type: str | None = None,
    ) -> int:
        """Remove entradas do cache e seus arquivos DuckDB.

        - cache_key: invalida entrada especifica
        - node_type: invalida todas as entradas deste tipo de no
        - sem filtros: invalida tudo

        Retorna o numero de entradas removidas.
        """
        from app.db.session import async_session_factory
        from app.models.extract_cache import ExtractCache
        from sqlalchemy import delete, select

        try:
            async with async_session_factory() as session:
                stmt = select(ExtractCache)
                if cache_key is not None:
                    stmt = stmt.where(ExtractCache.cache_key == cache_key)
                if node_type is not None:
                    stmt = stmt.where(ExtractCache.node_type == node_type)

                rows = list((await session.execute(stmt)).scalars().all())
                count = len(rows)

                for row in rows:
                    entry_dir = _entry_dir(row.cache_key)
                    if entry_dir.exists():
                        shutil.rmtree(entry_dir, ignore_errors=True)

                del_stmt = delete(ExtractCache)
                if cache_key is not None:
                    del_stmt = del_stmt.where(ExtractCache.cache_key == cache_key)
                if node_type is not None:
                    del_stmt = del_stmt.where(ExtractCache.node_type == node_type)
                await session.execute(del_stmt)
                await session.commit()

            if count:
                logger.info(
                    "extract_cache.invalidated",
                    count=count,
                    cache_key=cache_key[:16] if cache_key else None,
                    node_type=node_type,
                )
            return count

        except Exception:  # noqa: BLE001
            logger.exception("extract_cache.invalidate_failed")
            return 0

    # -----------------------------------------------------------------------
    # Limpeza periodica
    # -----------------------------------------------------------------------

    async def cleanup_expired(self) -> int:
        """Remove entradas expiradas do banco e seus arquivos DuckDB.

        Chamado pelo APScheduler (daily). Retorna o numero de entradas removidas.
        """
        from app.db.session import async_session_factory
        from app.models.extract_cache import ExtractCache
        from sqlalchemy import delete, select

        now = datetime.now(timezone.utc)
        try:
            async with async_session_factory() as session:
                rows = list(
                    (
                        await session.execute(
                            select(ExtractCache).where(ExtractCache.expires_at <= now)
                        )
                    ).scalars().all()
                )
                count = len(rows)

                for row in rows:
                    entry_dir = _entry_dir(row.cache_key)
                    if entry_dir.exists():
                        shutil.rmtree(entry_dir, ignore_errors=True)

                await session.execute(
                    delete(ExtractCache).where(ExtractCache.expires_at <= now)
                )
                await session.commit()

            return count

        except Exception:  # noqa: BLE001
            logger.exception("extract_cache.cleanup_failed")
            return 0


extract_cache_service = ExtractCacheService()
