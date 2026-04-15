"""
Task Prefect generica para nos processados via registry.
"""

from typing import Any

from prefect import get_run_logger, task

from app.services.workflow.nodes import get_processor


@task(name="registered_node", retries=0)
def execute_registered_node(
    node_id: str,
    node_type: str,
    config: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Despacha um no para o processador registrado correspondente."""
    logger = get_run_logger()
    logger.info(
        f"Executando no registrado '{node_id}' com processador '{node_type}'."
    )

    processor = get_processor(node_type)
    return processor.process(
        node_id=node_id,
        config=config,
        context=context,
    )
