"""
Processador do no de trigger webhook.

O payload ja foi recebido pelas rotas ``/api/v1/webhook/{path}`` e
injetado no contexto como ``input_data`` com a estrutura:

    {
      "method": "POST",
      "headers": {...},
      "query_params": {...},
      "body": <json>,
      "raw": "<base64>" | None,
    }

Este no simplesmente repassa esses campos aos nos seguintes, usando
``output_field`` (default ``data``) como chave para o body/raw.
"""

from typing import Any

from app.services.workflow.nodes import BaseNodeProcessor, register_processor


@register_processor("webhook")
class WebhookTriggerProcessor(BaseNodeProcessor):
    """Repassa o payload capturado pela rota de webhook aos nos downstream."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        output_field = str(resolved.get("output_field") or "data") if isinstance(resolved, dict) else "data"

        input_data = context.get("input_data") or {}
        if not isinstance(input_data, dict):
            input_data = {"body": input_data}

        body = input_data.get("body")
        raw = input_data.get("raw")

        out: dict[str, Any] = {
            "node_id": node_id,
            "trigger_type": "webhook",
            "status": "triggered",
            "http_method": input_data.get("method"),
            "headers": input_data.get("headers") or {},
            "query_params": input_data.get("query_params") or {},
        }
        out[output_field] = body if body is not None else raw
        return out
