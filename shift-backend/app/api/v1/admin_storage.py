"""
Endpoint admin para monitoramento de uso de armazenamento temporario DuckDB.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from app.core.security import require_permission

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/storage/usage")
async def get_storage_usage(
    _=Depends(require_permission("workspace", "ADMIN")),
) -> dict[str, Any]:
    """Retorna uso de armazenamento temporario DuckDB por execucao.

    - ``total_mb``: soma de todos os diretorios de execucao.
    - ``top10``: as 10 execucoes com maior uso (decrescente).
    - ``execution_count``: numero total de diretorios de execucao presentes.
    """
    base = Path(tempfile.gettempdir()) / "shift" / "executions"
    if not base.exists():
        return {"total_mb": 0.0, "execution_count": 0, "top10": []}

    entries: list[dict[str, Any]] = []
    total_bytes = 0

    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        size_bytes = _dir_size(entry)
        total_bytes += size_bytes
        entries.append(
            {
                "execution_id": entry.name,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
            }
        )

    entries.sort(key=lambda e: e["size_mb"], reverse=True)

    return {
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "execution_count": len(entries),
        "top10": entries[:10],
    }


def _dir_size(path: Path) -> int:
    """Soma recursiva dos tamanhos de arquivos em ``path``."""
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


@router.post("/storage/cleanup")
async def trigger_storage_cleanup(
    _=Depends(require_permission("workspace", "ADMIN")),
) -> dict[str, Any]:
    """Forca a execucao imediata do job de limpeza de armazenamento.

    Util quando o tempdir cresceu inesperadamente (ex: dev com muitos
    restarts onde o job de hora em hora nunca disparou). Roda o mesmo
    cleanup que o scheduler executa, mas de forma sincrona, e retorna
    o tamanho total atual do ``<tempdir>/shift/``.
    """
    from app.services.scheduler_service import (  # noqa: PLC0415
        _run_duckdb_storage_cleanup,
    )

    base = Path(tempfile.gettempdir()) / "shift"
    size_before = _dir_size(base) if base.exists() else 0

    await _run_duckdb_storage_cleanup()

    size_after = _dir_size(base) if base.exists() else 0
    freed = size_before - size_after

    return {
        "before_mb": round(size_before / (1024 * 1024), 2),
        "after_mb": round(size_after / (1024 * 1024), 2),
        "freed_mb": round(freed / (1024 * 1024), 2),
    }
