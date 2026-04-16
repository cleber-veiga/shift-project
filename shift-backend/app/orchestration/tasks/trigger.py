"""
Execucao de nos de trigger via registry de processors.
"""

import asyncio
from typing import Any

from app.core.logging import bind_context, get_logger
from app.services.workflow.nodes import get_processor


def _resolve_processor_type(
    config: dict[str, Any],
    processor_type: str | None,
) -> str:
    """Resolve o tipo real do processor no schema novo ou legado."""
    if processor_type:
        return processor_type

    node_type = str(config.get("type", "manual"))
    if node_type == "triggerNode":
        legacy_type = str(config.get("trigger_type", "manual"))
        return "cron" if legacy_type == "schedule" else legacy_type

    return node_type


async def execute_trigger_node(
    node_id: str,
    config: dict[str, Any],
    context: dict[str, Any],
    processor_type: str | None = None,
) -> dict[str, Any]:
    """
    Executa um no de trigger atraves do registry de processors.

    Args:
        node_id: Identificador unico do no no workflow.
        config: Configuracao do no.
        context: Contexto global da execucao.
        processor_type: Tipo normalizado do trigger, quando resolvido pelo flow.

    Returns:
        Dicionario com o output do processor.
    """
    logger = get_logger(__name__)
    resolved_type = _resolve_processor_type(config, processor_type)

    with bind_context(
        node_id=node_id,
        execution_id=context.get("execution_id"),
        workflow_id=context.get("workflow_id"),
    ):
        logger.info("trigger.dispatch", processor_type=resolved_type)
        processor = get_processor(resolved_type)
        return await asyncio.to_thread(
            processor.process,
            node_id=node_id,
            config=config,
            context=context,
        )
