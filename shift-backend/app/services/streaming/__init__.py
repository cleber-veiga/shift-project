"""Utilitarios de streaming entre nodes (queue bounded + spill em disco).

Modulo central: ``BoundedChunkQueue``. Substitui ``queue.Queue`` cru no
pipeline de extracao para garantir backpressure end-to-end com fallback
opcional de spillover em disco quando o consumidor (load_node) e mais
lento que o produtor (sql_database).
"""

from app.services.streaming.bounded_chunk_queue import (
    BoundedChunkQueue,
    cleanup_execution_spill,
)

__all__ = ["BoundedChunkQueue", "cleanup_execution_spill"]
