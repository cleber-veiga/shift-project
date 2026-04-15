"""
Processador do no de trigger polling.

Executa uma query em um banco de dados para verificar se ha novos dados.
Se a query nao retornar resultados, levanta NodeProcessingSkipped para
abortar o fluxo graciosamente. Se houver dados, repassa-os como output
para os nos seguintes.
"""

from typing import Any

import sqlalchemy as sa

from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingSkipped


@register_processor("polling")
class PollingTriggerProcessor(BaseNodeProcessor):
    """
    Verifica novos dados via query SQL.
    Aborta o fluxo se nao encontrar registros.
    """

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        _ = context
        connection_string = config.get("connection_string")
        query = config.get("query")

        if not connection_string or not query:
            raise ValueError(
                f"No polling '{node_id}': connection_string e query sao obrigatorios."
            )

        # O processor roda em uma task do Prefect; por isso, um engine
        # sincrono simples ja atende bem para a verificacao de polling.
        engine = sa.create_engine(connection_string)
        try:
            with engine.connect() as conn:
                result = conn.execute(sa.text(query))
                rows: list[dict[str, Any]] = [
                    dict(row) for row in result.mappings().all()
                ]
        finally:
            engine.dispose()

        if not rows:
            raise NodeProcessingSkipped(
                f"No polling '{node_id}': query retornou 0 registros. "
                "Fluxo abortado sem erro."
            )

        return {
            "node_id": node_id,
            "trigger_type": "polling",
            "status": "triggered",
            "row_count": len(rows),
            "data": rows,
        }
