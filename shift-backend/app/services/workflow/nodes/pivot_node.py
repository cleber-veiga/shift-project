"""
Processador do no de pivot (wide, eager).

Transforma linhas em colunas dinamicamente, descobrindo os valores unicos da
coluna pivot em uma query separada antes de gerar o SQL final. O resultado e
sempre materializado — pivot nao pode ser lazy porque o schema de saida so e
conhecido apos a query de descoberta.

Configuracao:
- index_columns   : colunas que formam a chave do agrupamento (GROUP BY)
- pivot_column    : coluna cujos valores viram nomes de coluna
- value_column    : coluna cujos valores sao agregados
- aggregations    : lista de funcoes de agregacao ["sum", "count", "avg", "max", "min"]
- max_pivot_values: limite de valores unicos (default 200); falha acima disso
- output_field    : campo de saida (default "data")

O mapping {valor_original: nome_coluna_gerada} e retornado em "pivot_col_mapping"
para que o frontend e nos downstream possam consultar as colunas geradas.
"""

import re
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

_VALID_AGGREGATIONS = {"sum", "count", "avg", "max", "min"}
_MAX_PIVOT_VALUES_HARD_LIMIT = 1000


def _sanitize_pivot_col_name(val_str: str, agg: str) -> str:
    """Converte um valor pivot em nome de coluna SQL valido."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", str(val_str))
    safe = re.sub(r"_+", "_", safe).strip("_") or "val"
    return f"{safe}_{agg}"


def _make_unique_col_name(base: str, used: set[str]) -> str:
    """Garante unicidade do nome de coluna adicionando sufixo numerico."""
    name = base
    counter = 2
    while name in used:
        name = f"{base}_{counter}"
        counter += 1
    return name


def _sql_literal(value: Any) -> str:
    """Converte valor Python para literal SQL seguro."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


@register_processor("pivot")
class PivotNodeProcessor(BaseNodeProcessor):
    """Pivot dinamico via CASE WHEN gerado por valores unicos descobertos em runtime."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        index_columns: list[str] = [str(c) for c in (resolved.get("index_columns") or [])]
        pivot_column = str(resolved.get("pivot_column", "")).strip()
        value_column = str(resolved.get("value_column", "")).strip()
        aggregations: list[str] = [
            str(a).lower() for a in (resolved.get("aggregations") or ["sum"])
        ]
        max_pivot_values = int(resolved.get("max_pivot_values", 200))
        output_field = str(resolved.get("output_field", "data"))

        # Validacoes
        if not index_columns:
            raise NodeProcessingError(
                f"No pivot '{node_id}': informe ao menos uma coluna em 'index_columns'."
            )
        if not pivot_column:
            raise NodeProcessingError(
                f"No pivot '{node_id}': 'pivot_column' e obrigatorio."
            )
        if not value_column:
            raise NodeProcessingError(
                f"No pivot '{node_id}': 'value_column' e obrigatorio."
            )
        for agg in aggregations:
            if agg not in _VALID_AGGREGATIONS:
                raise NodeProcessingError(
                    f"No pivot '{node_id}': agregacao '{agg}' invalida. "
                    f"Use: {sorted(_VALID_AGGREGATIONS)}."
                )
        if max_pivot_values < 1 or max_pivot_values > _MAX_PIVOT_VALUES_HARD_LIMIT:
            raise NodeProcessingError(
                f"No pivot '{node_id}': max_pivot_values deve ser entre 1 e "
                f"{_MAX_PIVOT_VALUES_HARD_LIMIT}."
            )

        input_ref = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_ref)

        conn = duckdb.connect(str(input_ref["database_path"]))
        warnings: list[str] = []
        try:
            row_in: int = conn.execute(
                f"SELECT COUNT(*) FROM {source_ref}"
            ).fetchone()[0]  # type: ignore[index]

            # ── Passo 1: descobrir valores unicos da coluna pivot ───────────────
            discovery_rows = conn.execute(
                f"""
                SELECT DISTINCT {quote_identifier(pivot_column)}
                FROM {source_ref}
                WHERE {quote_identifier(pivot_column)} IS NOT NULL
                ORDER BY {quote_identifier(pivot_column)}
                LIMIT {max_pivot_values + 1}
                """
            ).fetchall()

            if len(discovery_rows) > max_pivot_values:
                raise NodeProcessingError(
                    f"No pivot '{node_id}': a coluna '{pivot_column}' tem mais de "
                    f"{max_pivot_values} valores unicos. Aumente 'max_pivot_values' "
                    f"ou reduza a cardinalidade da coluna pivot."
                )

            pivot_values = [r[0] for r in discovery_rows]

            if not pivot_values:
                raise NodeProcessingError(
                    f"No pivot '{node_id}': a coluna '{pivot_column}' nao tem "
                    "valores nao-nulos para pivotar."
                )

            # 80% do limite vira sinal de risco — próximo passo de cardinalidade
            # quebra o pivot e o usuário não tem visibilidade fácil até aqui.
            if len(pivot_values) >= int(max_pivot_values * 0.8):
                warnings.append("near_max_pivot_values")

            # ── Passo 2: gerar expressoes CASE WHEN para cada valor × agregacao ─
            agg_exprs: list[str] = []
            col_mapping: dict[str, dict[str, str]] = {}  # val -> {agg -> col_name}
            used_names: set[str] = set()

            for val in pivot_values:
                val_str = str(val)
                val_mapping: dict[str, str] = {}

                if val is None:
                    condition = f"{quote_identifier(pivot_column)} IS NULL"
                else:
                    condition = (
                        f"{quote_identifier(pivot_column)} = {_sql_literal(val)}"
                    )

                for agg in aggregations:
                    base_name = _sanitize_pivot_col_name(val_str, agg)
                    col_name = _make_unique_col_name(base_name, used_names)
                    used_names.add(col_name)
                    val_mapping[agg] = col_name

                    vc = quote_identifier(value_column)
                    if agg == "sum":
                        expr = f"SUM(CASE WHEN {condition} THEN {vc} ELSE 0 END)"
                    elif agg == "count":
                        expr = f"COUNT(CASE WHEN {condition} THEN 1 END)"
                    elif agg == "avg":
                        expr = f"AVG(CASE WHEN {condition} THEN {vc} END)"
                    elif agg == "max":
                        expr = f"MAX(CASE WHEN {condition} THEN {vc} END)"
                    else:  # min
                        expr = f"MIN(CASE WHEN {condition} THEN {vc} END)"

                    agg_exprs.append(f"{expr} AS {quote_identifier(col_name)}")

                col_mapping[val_str] = val_mapping

            # ── Passo 3: executar query final ──────────────────────────────────
            idx_select = ", ".join(quote_identifier(c) for c in index_columns)
            group_by = ", ".join(str(i + 1) for i in range(len(index_columns)))
            agg_select = ", ".join(agg_exprs)

            output_table = sanitize_name(build_next_table_name(node_id, "pivoted"))
            output_ref_sql = f"main.{quote_identifier(output_table)}"

            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {output_ref_sql} AS
                SELECT {idx_select}, {agg_select}
                FROM {source_ref}
                GROUP BY {group_by}
                ORDER BY {idx_select}
                """
            )
            row_out: int = conn.execute(
                f"SELECT COUNT(*) FROM {output_ref_sql}"
            ).fetchone()[0]  # type: ignore[index]
        finally:
            conn.close()

        output_reference = build_output_reference(input_ref, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
            "pivot_col_mapping": col_mapping,
            "pivot_values_count": len(pivot_values),
            "output_summary": {
                "row_count_in": row_in,
                "row_count_out": row_out,
                "warnings": warnings,
            },
        }
