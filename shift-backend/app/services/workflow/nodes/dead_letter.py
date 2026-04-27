"""No terminal que persiste payloads em dead-letter."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import duckdb

from app.data_pipelines.duckdb_storage import build_table_ref, get_primary_input_reference
from app.services.dead_letter_service import DeadLetterWrite, dead_letter_service
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("dead_letter")
class DeadLetterProcessor(BaseNodeProcessor):
    """Persiste entradas de dead-letter a partir do ramo ``on_error``."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        _ = resolved_config
        raw_execution_id = context.get("execution_id")
        if raw_execution_id is None:
            raise NodeProcessingError(
                f"No dead_letter '{node_id}': execution_id ausente no contexto."
            )

        try:
            execution_id = UUID(str(raw_execution_id))
        except ValueError as exc:
            raise NodeProcessingError(
                f"No dead_letter '{node_id}': execution_id invalido."
            ) from exc

        upstream_results = context.get("upstream_results") or {}
        source_node_id, source_result = _get_latest_upstream(upstream_results)

        payload_rows = _extract_payload_rows(context, node_id)
        if not payload_rows:
            payload = (
                source_result if isinstance(source_result, dict) else {"value": source_result}
            )
            payload_rows = [payload]

        default_error = _extract_default_error(source_result)
        failed_node_id = (
            source_result.get("failed_node")
            if isinstance(source_result, dict)
            else None
        ) or (
            source_result.get("node_id") if isinstance(source_result, dict) else None
        ) or source_node_id

        entries = [
            DeadLetterWrite(
                node_id=str(failed_node_id or source_node_id or node_id),
                error_message=_extract_row_error(row, default_error),
                payload=row,
            )
            for row in payload_rows
        ]
        created_ids = dead_letter_service.create_entries_sync(
            execution_id=execution_id,
            entries=entries,
        )

        result = {
            "status": "success",
            "entries_written": len(created_ids),
            "dead_letter_ids": [str(entry_id) for entry_id in created_ids],
            "failed_node": str(failed_node_id or source_node_id or node_id),
        }
        output_field = "dead_letter_result"
        return {
            "node_id": node_id,
            **result,
            "output_field": output_field,
            output_field: result,
        }


def _get_latest_upstream(
    upstream_results: dict[str, Any],
) -> tuple[str | None, Any]:
    if not isinstance(upstream_results, dict) or not upstream_results:
        return None, None
    source_node_id = next(reversed(upstream_results))
    return source_node_id, upstream_results[source_node_id]


def _extract_payload_rows(
    context: dict[str, Any],
    node_id: str,
) -> list[dict[str, Any]]:
    try:
        reference = get_primary_input_reference(context, node_id)
    except Exception:
        return []

    # ``read_only=True`` removido — vide filter_node.
    conn = duckdb.connect(str(reference["database_path"]))
    try:
        cursor = conn.execute(f"SELECT * FROM {build_table_ref(reference)}")
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def _extract_default_error(source_result: Any) -> str:
    if isinstance(source_result, dict):
        for key in ("error", "error_message", "message"):
            value = source_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "Falha encaminhada para dead-letter."


def _extract_row_error(row: dict[str, Any], default_error: str) -> str:
    value = row.get("_dead_letter_error")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default_error
