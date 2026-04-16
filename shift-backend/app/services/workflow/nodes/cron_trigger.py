"""
Processador do nó de trigger cron.

O agendamento e gerenciado pelo APScheduler interno (ver scheduler_service).
Este no nao faz processamento de dados — apenas sinaliza o inicio de um
fluxo temporal e retorna a data/hora atual como output.
"""

from datetime import datetime, timezone
from typing import Any

from app.services.workflow.nodes import BaseNodeProcessor, register_processor


@register_processor("cron")
class CronTriggerProcessor(BaseNodeProcessor):
    """Sinaliza o início de um fluxo agendado, retornando o timestamp atual."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        cron_expression = config.get("cron_expression", "não definido")

        return {
            "node_id": node_id,
            "trigger_type": "cron",
            "status": "triggered",
            "cron_expression": cron_expression,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "data": {},
        }
