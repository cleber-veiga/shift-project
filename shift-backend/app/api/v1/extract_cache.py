"""
Endpoints de gerenciamento do cache de extracoes (Sprint 4.4).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import require_permission
from app.services.extract_cache_service import extract_cache_service

router = APIRouter(prefix="/extract-cache", tags=["extract-cache"])


@router.delete("")
async def invalidate_extract_cache(
    cache_key: Optional[str] = Query(
        default=None,
        description="SHA-256 de uma entrada especifica. Se omitido com node_type, invalida esse tipo. Se ambos omitidos, limpa todo o cache.",
    ),
    node_type: Optional[str] = Query(
        default=None,
        description="Tipo de no (sql_database, csv_input, excel_input, api_input). Invalida todas as entradas deste tipo.",
    ),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict:
    """Invalida entradas do cache de extracoes manualmente.

    Filtros aceitos (combinaveis):
    - ``cache_key``: remove uma entrada especifica pelo hash SHA-256.
    - ``node_type``: remove todas as entradas do tipo de no informado.
    - Sem filtros: remove todo o cache (use com cautela).

    Retorna ``{"removed": N}`` com o numero de entradas removidas.
    """
    removed = await extract_cache_service.invalidate(
        cache_key=cache_key,
        node_type=node_type,
    )
    return {"removed": removed}
