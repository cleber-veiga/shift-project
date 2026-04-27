"""
Processador do no de trigger polling.

Executa uma query em um banco de dados para verificar se ha novos dados.
Se a query nao retornar resultados, levanta NodeProcessingSkipped para
abortar o fluxo graciosamente. Se houver dados, repassa-os como output
para os nos seguintes.
"""

from typing import Any

import sqlalchemy as sa

from app.services.db.engine_cache import get_engine_from_url
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingSkipped


def _infer_conn_type(cs: str) -> str:
    cs_lower = cs.lower()
    if cs_lower.startswith("postgresql") or cs_lower.startswith("postgres"):
        return "postgresql"
    if cs_lower.startswith("mysql"):
        return "mysql"
    if cs_lower.startswith("oracle"):
        return "oracle"
    if cs_lower.startswith("firebird"):
        return "firebird"
    if cs_lower.startswith("mssql") or cs_lower.startswith("sqlserver"):
        return "sqlserver"
    if cs_lower.startswith("sqlite"):
        return "sqlite"
    return "unknown"


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
        connection_string = config.get("connection_string")
        query = config.get("query")

        if not connection_string or not query:
            raise ValueError(
                f"No polling '{node_id}': connection_string e query sao obrigatorios."
            )

        # Engine compartilhado pelo cache global — NAO chamar dispose() aqui;
        # o pool e reusado pelas proximas execucoes do mesmo workflow.
        engine = get_engine_from_url(
            context.get("workspace_id"),
            str(connection_string),
            _infer_conn_type(str(connection_string)),
        )
        with engine.connect() as conn:
            result = conn.execute(sa.text(query))
            rows: list[dict[str, Any]] = [
                dict(row) for row in result.mappings().all()
            ]

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
