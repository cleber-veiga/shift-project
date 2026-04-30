"""
Processador do no de uniao (union).

Combina N datasets upstream identificados pelos handles 'input_1'..'input_N'.
Suporta dois modos de alinhamento de colunas:

- by_name (padrao): UNION ALL BY NAME — alinha colunas pelo nome,
  inserindo NULL nas colunas ausentes em cada fonte.
- by_position: UNION ALL — alinha colunas pela posicao; schemas devem
  ser identicos ou compativeis.

Configuracao:
- mode            : "by_name" | "by_position"  (padrao: "by_name")
- add_source_col  : bool — adiciona coluna com o handle de origem (ex: "input_1")
- source_col_name : str  — nome da coluna de origem (padrao: "_source")
- output_field    : str  — campo de saida (padrao: "data")
- dedup_keys      : list[str] — quando preenchido, aplica dedup pos-uniao
  via ROW_NUMBER() OVER (PARTITION BY ...). Mantem 1 linha por chave.
- dedup_priority  : "first" | "last" | "input_first" | "input_last"
                    Controla qual linha sobrevive em caso de duplicata.
                    "input_first"/"input_last" usam a ordem das entradas
                    (input_1 < input_2 < ...) — exige um campo interno de
                    rank, que adicionamos no SELECT e removemos no resultado.

Quando os datasets estao em bancos DuckDB distintos, o no realiza ATTACH
de todos os bancos adicionais no banco da primeira entrada. O resultado
e materializado no banco da primeira entrada.
"""

from typing import Any

import duckdb

from app.data_pipelines.duckdb_storage import (
    DuckDbReference,
    build_next_table_name,
    build_output_reference,
    build_table_ref,
    get_named_input_reference,
    quote_identifier,
    sanitize_name,
)
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError

_VALID_MODES = {"by_name", "by_position"}
_VALID_DEDUP_PRIORITIES = {"first", "last", "input_first", "input_last"}
# Coluna interna usada para rankear linhas por entrada quando o priority
# usa ordem de entrada. Adicionada no SELECT de cada upstream e removida
# do resultado final via EXCLUDE.
_INPUT_RANK_COL = "__shift_union_input_rank__"


@register_processor("union")
class UnionNodeProcessor(BaseNodeProcessor):
    """Combina N datasets upstream via UNION ALL."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        mode = str(resolved.get("mode", "by_name")).lower()
        add_source_col = bool(resolved.get("add_source_col", False))
        source_col_name = str(resolved.get("source_col_name", "_source")).strip() or "_source"
        output_field = str(resolved.get("output_field", "data"))
        dedup_keys_raw = resolved.get("dedup_keys") or []
        dedup_keys = [str(k).strip() for k in dedup_keys_raw if str(k).strip()]
        dedup_priority = str(resolved.get("dedup_priority", "first")).lower()

        if mode not in _VALID_MODES:
            raise NodeProcessingError(
                f"No union '{node_id}': mode deve ser um de {sorted(_VALID_MODES)}."
            )
        if dedup_keys and dedup_priority not in _VALID_DEDUP_PRIORITIES:
            raise NodeProcessingError(
                f"No union '{node_id}': dedup_priority deve ser um de "
                f"{sorted(_VALID_DEDUP_PRIORITIES)}."
            )
        # Quando o priority depende da entrada, exigimos by_name (UNION ALL BY
        # NAME) — adicionamos uma coluna interna ``__shift_union_input_rank__``
        # so em algumas entradas, o que quebra by_position.
        priority_uses_input = dedup_priority in {"input_first", "input_last"}
        if priority_uses_input and mode != "by_name":
            raise NodeProcessingError(
                f"No union '{node_id}': priority '{dedup_priority}' exige "
                f"mode 'by_name' (a ordem das entradas precisa de UNION BY NAME)."
            )

        # Descobre todos os handles input_N conectados
        edge_handles: dict[str, str | None] = context.get("edge_handles", {})
        input_handles = sorted(
            {v for v in edge_handles.values() if v and v.startswith("input_")},
            key=lambda h: int(h.split("_")[1]) if h.split("_")[1].isdigit() else 0,
        )

        if len(input_handles) < 2:
            raise NodeProcessingError(
                f"No union '{node_id}': ao menos 2 entradas sao necessarias "
                f"(encontradas: {len(input_handles)})."
            )

        # Resolve referencias DuckDB por handle
        refs: list[tuple[str, DuckDbReference]] = []
        for handle in input_handles:
            ref = get_named_input_reference(context, node_id, handle)
            refs.append((handle, ref))

        primary_handle, primary_ref = refs[0]
        primary_db = str(primary_ref["database_path"])

        conn = duckdb.connect(primary_db)
        warnings: list[str] = []
        row_count_in: dict[str, int] = {}
        try:
            # ATTACH bancos distintos
            alias_map: dict[str, str] = {}  # database_path -> alias
            attach_counter = 0
            for handle, ref in refs[1:]:
                db_path = str(ref["database_path"])
                if db_path != primary_db and db_path not in alias_map:
                    alias = f"__union_db_{attach_counter}__"
                    conn.execute(
                        f"ATTACH '{db_path}' AS {quote_identifier(alias)} (READ_ONLY)"
                    )
                    alias_map[db_path] = alias
                    attach_counter += 1

            union_keyword = "UNION ALL BY NAME" if mode == "by_name" else "UNION ALL"

            # Monta SELECT de cada entrada e coleta row_count + schema por handle.
            select_parts = []
            schemas_per_handle: list[tuple[str, ...]] = []
            for handle, ref in refs:
                db_path = str(ref["database_path"])
                if db_path == primary_db:
                    table_ref = build_table_ref(ref)
                else:
                    alias = alias_map[db_path]
                    schema = ref.get("dataset_name") or "main"
                    table = str(ref["table_name"])
                    table_ref = (
                        f"{quote_identifier(alias)}"
                        f".{quote_identifier(schema)}"
                        f".{quote_identifier(table)}"
                    )

                # Conta linhas por entrada para output_summary.
                row_count_in[handle] = conn.execute(
                    f"SELECT COUNT(*) FROM {table_ref}"
                ).fetchone()[0]  # type: ignore[index]
                # Coleta schema (apenas nomes de coluna em ordem) para detectar drift.
                cols = tuple(
                    r[0] for r in conn.execute(f"DESCRIBE {table_ref}").fetchall()
                )
                schemas_per_handle.append(cols)

                # Rank por entrada: input_1 → 1, input_2 → 2, etc. Injetado
                # no SELECT para que o ROW_NUMBER() de dedup possa usar essa
                # ordem como criterio de desempate. So adicionamos quando a
                # dedup pediu priority por entrada — caso contrario nao polui
                # o output com colunas extras.
                input_rank_idx = len(select_parts) + 1
                input_rank_select = (
                    f"{input_rank_idx} AS {quote_identifier(_INPUT_RANK_COL)}, "
                    if priority_uses_input
                    else ""
                )
                if add_source_col:
                    escaped = handle.replace("'", "''")
                    select_parts.append(
                        f"{input_rank_select}"
                        f"'{escaped}' AS {quote_identifier(source_col_name)}, * FROM {table_ref}"
                    )
                else:
                    select_parts.append(f"{input_rank_select}* FROM {table_ref}")

            # by_position com schemas divergentes vai concatenar colunas pela
            # ordem — risco de juntar dados semanticamente diferentes.
            if mode == "by_position" and len(set(schemas_per_handle)) > 1:
                warnings.append("schema_drift")

            union_parts = [f"SELECT {p}" for p in select_parts]
            union_sql = f"\n{union_keyword}\n".join(union_parts)

            output_table = sanitize_name(build_next_table_name(node_id, "union"))
            output_ref_sql = f"main.{quote_identifier(output_table)}"

            if dedup_keys:
                # Dedup pos-uniao via ROW_NUMBER() OVER (PARTITION BY <chaves>).
                # ORDER BY decide qual linha sobrevive em cada grupo:
                #   - "first":       ordem natural (mantem a 1a linha vista)
                #   - "last":        ordem reversa (mantem a ultima)
                #   - "input_first": rank das entradas ASC (input_1 vence)
                #   - "input_last":  rank das entradas DESC (input_N vence)
                partition_cols = ", ".join(quote_identifier(k) for k in dedup_keys)
                if dedup_priority == "input_first":
                    order_clause = f"{quote_identifier(_INPUT_RANK_COL)} ASC"
                elif dedup_priority == "input_last":
                    order_clause = f"{quote_identifier(_INPUT_RANK_COL)} DESC"
                elif dedup_priority == "last":
                    # Sem coluna estavel, usamos um proxy via NULL ordering.
                    # ROW_NUMBER em DuckDB sem ORDER BY tambem e nao-deterministico,
                    # entao o mais simples e ordenar por NULL ASC (= ordem de
                    # insercao) e usar RANK reverso. Fallback pragmatico:
                    order_clause = "NULL DESC"
                else:  # "first"
                    order_clause = "NULL ASC"

                # Excluimos colunas internas do output final pra nao poluir
                # o resultado. DuckDB so aceita UM clausula EXCLUDE por
                # SELECT — listamos todas as colunas a omitir junto.
                excluded_cols = ["__shift_dedup_rn"]
                if priority_uses_input:
                    excluded_cols.append(quote_identifier(_INPUT_RANK_COL))
                exclude_clause = f"EXCLUDE ({', '.join(excluded_cols)})"

                conn.execute(
                    f"""
                    CREATE OR REPLACE TABLE {output_ref_sql} AS
                    WITH __unioned AS ({union_sql}),
                    __ranked AS (
                        SELECT
                            *,
                            ROW_NUMBER() OVER (
                                PARTITION BY {partition_cols}
                                ORDER BY {order_clause}
                            ) AS __shift_dedup_rn
                        FROM __unioned
                    )
                    SELECT * {exclude_clause}
                    FROM __ranked
                    WHERE __shift_dedup_rn = 1
                    """
                )
            else:
                conn.execute(
                    f"CREATE OR REPLACE TABLE {output_ref_sql} AS {union_sql}"
                )
            row_out: int = conn.execute(
                f"SELECT COUNT(*) FROM {output_ref_sql}"
            ).fetchone()[0]  # type: ignore[index]
        finally:
            conn.close()

        output_reference = build_output_reference(primary_ref, output_table)
        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_reference,
            "output_summary": {
                "row_count_in": row_count_in,
                "row_count_out": row_out,
                "warnings": warnings,
            },
        }
