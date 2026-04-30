"""
Processador do nó de trigger manual.

O trigger manual é acionado pelo botão "Play" no frontend.
O payload (input_data) já foi recebido pela rota do FastAPI,
então este nó apenas repassa os dados para o restante do fluxo.

Quando o ``input_data`` externo está vazio — caso típico de execução
de teste pelo próprio editor sem declarar Variáveis — usamos o
``payload`` declarado na configuração do nó como fallback. Permite
testar o workflow inline sem precisar criar arquivos auxiliares ou
chamar a API.

Quando o payload é uma lista de objetos, materializamos como dataset
DuckDB (mesmo formato dos nós CSV/Excel/Inline Data), permitindo que
nós downstream de transformação (Mapper, Filter, Texto → Linhas, etc.)
consumam normalmente.
"""

from typing import Any
from uuid import uuid4

from app.data_pipelines.duckdb_storage import ensure_duckdb_reference
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
        input_data = context.get("input_data") or {}

        # Fallback: usa o payload declarado no config quando o input_data
        # externo nao foi fornecido. ``not input_data`` cobre dict vazio,
        # lista vazia, None — todas as formas "sem dados".
        if not input_data:
            config_payload = config.get("payload")
            if config_payload is not None:
                input_data = config_payload

        # Lista de dicts → materializa como dataset DuckDB pra ser
        # consumivel por nos de transformacao downstream (Mapper, Filter,
        # Texto → Linhas, etc.). Mesma abordagem do inline_data_node.
        if (
            isinstance(input_data, list)
            and len(input_data) > 0
            and all(isinstance(item, dict) for item in input_data)
        ):
            execution_id = str(
                context.get("execution_id")
                or context.get("workflow_id")
                or uuid4()
            )
            reference = ensure_duckdb_reference(input_data, execution_id, node_id)
            return {
                "node_id": node_id,
                "trigger_type": "manual",
                "status": "completed",
                "output_field": "data",
                "data": reference,
            }

        # Caso classico: dict, scalar, ou lista nao-tabular. Repassa como
        # esta — nos consumidores que esperam dict (template references)
        # continuam funcionando. Nos que esperam dataset terao que tratar
        # esse formato (ou o usuario deve formatar como lista de dicts).
        return {
            "node_id": node_id,
            "trigger_type": "manual",
            "status": "triggered",
            "data": input_data,
        }
