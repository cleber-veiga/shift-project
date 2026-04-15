"""
Processador do no de validacao de dados (assert).

Aplica regras de qualidade ao dataset upstream reutilizando ``_build_sql_clause``
do ``filter_node`` — mesma sintaxe de operadores (eq, gt, in, is_null, etc.).

Comportamento por ``action_on_fail``:

- "abort" : conta as linhas que violam as regras; se > 0, lanca NodeProcessingError
            e interrompe o workflow.
- "warn"  : mesmo calculo, mas apenas registra um aviso no log; dados passam intactos.
- "drop"  : filtra as linhas invalidas; o resultado contem somente as linhas validas.

Nos modos "abort" e "warn" a referencia de saida e a mesma de entrada (pass-through).
No modo "drop" uma nova tabela DuckDB e materializada.

Configuracao:
- rules          : lista de {field, operator, value} — mesmo formato do filter_node
- logic          : "and" | "or"  (como combinar multiplas regras; padrao: "and")
- action_on_fail : "abort" | "warn" | "drop"  (padrao: "abort")
- output_field   : nome do campo de saida (padrao: "data")
"""

import logging
from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    build_next_table_name,
    build_output_reference,
    build_table_ref,
    get_primary_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError

# Reusa o construtor de clausulas SQL do filter_node — sem duplicar logica de operadores.
from app.services.workflow.nodes.filter_node import _build_sql_clause

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {"abort", "warn", "drop"}


@register_processor("assert")
class AssertNodeProcessor(BaseNodeProcessor):
    """Valida regras de qualidade de dados no dataset upstream."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        rules: list[dict] = resolved_config.get("rules") or []
        logic = str(resolved_config.get("logic", "and")).upper()
        action_on_fail = str(resolved_config.get("action_on_fail", "abort")).lower()
        output_field = str(resolved_config.get("output_field", "data"))

        if not rules:
            raise NodeProcessingError(
                f"No assert '{node_id}': informe ao menos uma regra em 'rules'."
            )
        if logic not in {"AND", "OR"}:
            raise NodeProcessingError(
                f"No assert '{node_id}': logic deve ser 'and' ou 'or'."
            )
        if action_on_fail not in _VALID_ACTIONS:
            raise NodeProcessingError(
                f"No assert '{node_id}': action_on_fail deve ser um de {_VALID_ACTIONS}."
            )

        input_reference = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_reference)

        # Reutiliza _build_sql_clause do filter_node — mesma sintaxe de operadores.
        valid_clauses = [_build_sql_clause(rule, node_id) for rule in rules]
        valid_where = f" {logic} ".join(valid_clauses)

        conn = duckdb.connect(str(input_reference["database_path"]))
        try:
            if action_on_fail == "drop":
                output_table = sanitize_name(build_next_table_name(node_id, "validated"))
                output_ref_sql = f"main.{quote_identifier(output_table)}"
                conn.execute(f"""
                    CREATE OR REPLACE TABLE {output_ref_sql} AS
                    SELECT * FROM {source_ref}
                    WHERE {valid_where}
                """)
                output_reference = build_output_reference(input_reference, output_table)
            else:
                # Conta linhas que violam (negacao da clausula valida).
                violation_where = f"NOT ({valid_where})"
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {source_ref} WHERE {violation_where}"
                ).fetchone()
                violation_count = int(row[0]) if row else 0

                if violation_count > 0:
                    msg = (
                        f"No assert '{node_id}': {violation_count} linha(s) violam as regras."
                    )
                    if action_on_fail == "abort":
                        raise NodeProcessingError(msg)
                    else:  # warn
                        logger.warning(msg)

                # Pass-through: referencia de saida e a mesma de entrada.
                output_reference = input_reference
        finally:
            conn.close()

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
        }
