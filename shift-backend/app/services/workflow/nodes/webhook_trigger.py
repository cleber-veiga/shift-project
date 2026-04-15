"""
Processador do nó de trigger webhook.

O payload já foi recebido pela rota POST /api/v1/webhooks/{workflow_id}
e injetado no contexto como input_data. Este nó apenas lê e repassa
os dados para os nós seguintes do fluxo.
"""

from typing import Any

from app.services.workflow.nodes import BaseNodeProcessor, register_processor


@register_processor("webhook")
class WebhookTriggerProcessor(BaseNodeProcessor):
    """Lê o payload do webhook recebido via contexto e repassa ao fluxo."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        input_data = context.get("input_data", {})

        return {
            "node_id": node_id,
            "trigger_type": "webhook",
            "status": "triggered",
            "data": input_data,
        }
