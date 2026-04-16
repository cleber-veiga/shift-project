"""
Execucao de nos via registry de processors.

Os processors sao sincronos (podem fazer I/O de DB/HTTP) — rodamos em
thread separada via ``asyncio.to_thread`` para nao bloquear o event loop.
"""

import asyncio
from typing import Any

from app.core.logging import bind_context, get_logger
from app.services.workflow.nodes import get_processor


async def execute_registered_node(
    node_id: str,
    node_type: str,
    config: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Despacha um no para o processador registrado correspondente."""
    logger = get_logger(__name__)
    with bind_context(
        node_id=node_id,
        execution_id=context.get("execution_id"),
        workflow_id=context.get("workflow_id"),
    ):
        logger.info("node.processor.dispatch", processor_type=node_type)
        processor = get_processor(node_type)
        return await asyncio.to_thread(
            processor.process,
            node_id=node_id,
            config=config,
            context=context,
        )
