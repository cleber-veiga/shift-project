"""
Processador do nó de trigger manual.

O trigger manual é acionado pelo botão "Play" no frontend.
O payload (input_data) já foi recebido pela rota do FastAPI,
então este nó apenas repassa os dados para o restante do fluxo.
"""

from typing import Any

from app.services.workflow.nodes import BaseNodeProcessor, register_processor


@register_processor("manual")
class ManualTriggerProcessor(BaseNodeProcessor):
    """Repassa o input_data recebido do contexto de execução."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        input_data = context.get("input_data", {})

        return {
            "node_id": node_id,
            "trigger_type": "manual",
            "status": "triggered",
            "data": input_data,
        }
