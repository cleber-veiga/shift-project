"""
Processador do no de dados estaticos (inline).

Permite inserir dados diretamente no JSON do workflow — util para:
  - Tabelas de dominio pequenas (listas de UFs, codigos de status, etc.)
  - Fixtures de teste dentro do proprio workflow
  - Valores de referencia para lookup/join

O no aceita:
  - Uma lista de dicionarios: [{"id": 1, "nome": "SP"}, ...]
  - Um dicionario unico:      {"id": 1, "nome": "SP"}  (encapsulado em lista)
  - Uma string JSON valida representando qualquer um dos acima

Os dados sao materializados via ``ensure_duckdb_reference``, produzindo uma
``DuckDbReference`` identica a de qualquer outro no de entrada.

Configuracao:
- data         : lista de dicts, dict unico ou string JSON (obrigatorio)
- output_field : nome do campo de saida (padrao: "data")
"""

import json
from typing import Any
from uuid import uuid4

from app.data_pipelines.duckdb_storage import ensure_duckdb_reference
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("inline_data")
class InlineDataNodeProcessor(BaseNodeProcessor):
    """Materializa dados estaticos embutidos no config do no em DuckDB."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Resolve templates no config, mas nao no campo `data` se for string JSON
        # para evitar que placeholders dentro de valores sejam resolvidos acidentalmente.
        output_field = str(
            self.resolve_data(config.get("output_field", "data"), context)
        )
        raw_data = config.get("data")

        if raw_data is None:
            raise NodeProcessingError(
                f"No inline_data '{node_id}': 'data' e obrigatorio."
            )

        # Se for string, tenta parsear como JSON
        if isinstance(raw_data, str):
            raw_data = raw_data.strip()
            if not raw_data:
                raise NodeProcessingError(
                    f"No inline_data '{node_id}': 'data' nao pode ser uma string vazia."
                )
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                raise NodeProcessingError(
                    f"No inline_data '{node_id}': 'data' e uma string mas nao e JSON valido — {exc}"
                ) from exc

        if not isinstance(raw_data, (list, dict)):
            raise NodeProcessingError(
                f"No inline_data '{node_id}': 'data' deve ser uma lista, dicionario "
                f"ou string JSON. Recebido: {type(raw_data).__name__}."
            )

        # Lista vazia e invalida
        if isinstance(raw_data, list) and len(raw_data) == 0:
            raise NodeProcessingError(
                f"No inline_data '{node_id}': 'data' nao pode ser uma lista vazia."
            )

        execution_id = str(
            context.get("execution_id") or context.get("workflow_id") or uuid4()
        )

        reference = ensure_duckdb_reference(raw_data, execution_id, node_id)

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: reference,
        }
