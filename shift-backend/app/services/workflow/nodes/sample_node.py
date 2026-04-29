"""
Processador do no de amostragem (sample).

Suporta tres modos de amostragem via DuckDB:
- first_n  : SELECT * FROM source LIMIT n
- random   : USING SAMPLE reservoir(n ROWS) REPEATABLE(seed)
- percent  : USING SAMPLE p PERCENT

O modo 'random' com seed fixo e determinístico — ideal para datasets
publicados onde reprodutibilidade importa.
"""

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

_VALID_MODES = {"first_n", "random", "percent"}


@register_processor("sample")
class SampleNodeProcessor(BaseNodeProcessor):
    """Amostra o dataset upstream usando DuckDB SAMPLE ou LIMIT."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = self.resolve_data(config, context)
        mode = str(resolved.get("mode", "first_n")).lower()
        output_field = str(resolved.get("output_field", "data"))

        if mode not in _VALID_MODES:
            raise NodeProcessingError(
                f"No sample '{node_id}': mode deve ser um de {sorted(_VALID_MODES)}."
            )

        input_ref = get_primary_input_reference(context, node_id)
        source_ref = build_table_ref(input_ref)

        warnings: list[str] = []

        if mode == "first_n":
            n = resolved.get("n")
            if n is None:
                raise NodeProcessingError(
                    f"No sample '{node_id}': 'n' e obrigatorio no modo first_n."
                )
            try:
                n = int(n)
                if n < 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise NodeProcessingError(
                    f"No sample '{node_id}': 'n' deve ser um inteiro nao-negativo."
                )
            sample_sql = f"SELECT * FROM {source_ref} LIMIT {n}"

        elif mode == "random":
            n = resolved.get("n")
            if n is None:
                raise NodeProcessingError(
                    f"No sample '{node_id}': 'n' e obrigatorio no modo random."
                )
            try:
                n = int(n)
                if n < 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise NodeProcessingError(
                    f"No sample '{node_id}': 'n' deve ser um inteiro nao-negativo."
                )
            seed_raw = resolved.get("seed")
            if seed_raw is None:
                # Reservoir sem seed explícito = amostra não reproduzível entre runs.
                warnings.append("non_reproducible_sample")
                seed = 42
            else:
                try:
                    seed = int(seed_raw)
                except (TypeError, ValueError):
                    seed = 42
            sample_sql = (
                f"SELECT * FROM {source_ref} "
                f"USING SAMPLE reservoir({n} ROWS) REPEATABLE({seed})"
            )

        else:  # percent
            pct = resolved.get("percent")
            if pct is None:
                raise NodeProcessingError(
                    f"No sample '{node_id}': 'percent' e obrigatorio no modo percent."
                )
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                raise NodeProcessingError(
                    f"No sample '{node_id}': 'percent' deve ser um numero."
                )
            if not (0 < pct <= 100):
                raise NodeProcessingError(
                    f"No sample '{node_id}': 'percent' deve estar entre 0 (exclusivo) e 100."
                )
            sample_sql = f"SELECT * FROM {source_ref} USING SAMPLE {pct} PERCENT (BERNOULLI)"

        output_table = sanitize_name(build_next_table_name(node_id, "sampled"))
        output_ref_sql = f"main.{quote_identifier(output_table)}"

        conn = duckdb.connect(str(input_ref["database_path"]))
        try:
            row_in: int = conn.execute(
                f"SELECT COUNT(*) FROM {source_ref}"
            ).fetchone()[0]  # type: ignore[index]
            conn.execute(
                f"CREATE OR REPLACE TABLE {output_ref_sql} AS {sample_sql}"
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
            "output_summary": {
                "row_count_in": row_in,
                "row_count_out": row_out,
                "warnings": warnings,
            },
        }
