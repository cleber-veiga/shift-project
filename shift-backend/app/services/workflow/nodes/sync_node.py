"""
Processador do nó de sincronização (Aguardar Todos).

Aguarda a conclusão de todos os ramos paralelos upstream e repassa
o controle para o próximo nó. Não transforma dados — apenas serve
como ponto de convergência visual e semântico no grafo.

O runner já garante ordenação topológica, ou seja, este nó só executa
quando todos os seus predecessores diretos tiverem concluído. O processador
simplesmente consolida os status dos upstreams e emite um único sinal
de saída.

Configuração do nó
------------------
    output_field : Nome do campo de saída (padrão ``"data"``).
                   Quando algum upstream possui dado DuckDB, o primeiro
                   encontrado é repassado, permitindo encadear transformações.
"""

from __future__ import annotations

from typing import Any

from app.data_pipelines.duckdb_storage import find_duckdb_reference
from app.services.workflow.nodes import BaseNodeProcessor, register_processor


@register_processor("sync")
class SyncNodeProcessor(BaseNodeProcessor):
    """Ponto de convergência: aguarda todos os ramos paralelos e passa adiante."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        output_field = str(resolved_config.get("output_field", "data"))

        upstream_results: dict[str, Any] = context.get("upstream_results") or {}

        # Coleta status de cada upstream para o relatório
        branch_statuses: dict[str, str] = {}
        for uid, uresult in upstream_results.items():
            if isinstance(uresult, dict):
                branch_statuses[uid] = str(uresult.get("status", "unknown"))
            else:
                branch_statuses[uid] = "unknown"

        output: dict[str, Any] = {
            "node_id": node_id,
            "status": "completed",
            "branches_synced": len(upstream_results),
            "branch_statuses": branch_statuses,
            "output_field": output_field,
        }

        # Repassa a primeira referência DuckDB encontrada nos upstreams,
        # permitindo que um nó downstream consuma os dados de um dos ramos.
        upstream_ref = _find_first_duckdb_reference(upstream_results)
        if upstream_ref is not None:
            output[output_field] = upstream_ref

        return output


def _find_first_duckdb_reference(
    upstream_results: dict[str, Any],
) -> dict[str, Any] | None:
    for upstream_value in upstream_results.values():
        ref = find_duckdb_reference(upstream_value)
        if ref is not None:
            return ref
    return None
