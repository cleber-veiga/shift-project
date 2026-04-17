"""Persistencia e reprocessamento de dead-letters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import duckdb
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_pipelines.duckdb_storage import (
    build_table_ref,
    ensure_duckdb_reference,
    find_duckdb_reference,
)
from app.db.session import async_session_factory
from app.models.project import Project
from app.models.workflow import DeadLetterEntry, Workflow, WorkflowExecution
from app.schemas.dead_letter import DeadLetterListItem
from app.services.connection_service import connection_service


@dataclass(slots=True)
class DeadLetterWrite:
    """Payload interno usado para gravar entradas de dead-letter."""

    node_id: str
    error_message: str
    payload: dict[str, Any]


class DeadLetterService:
    """Service de persistencia e retry de dead-letters."""

    async def create_entries(
        self,
        db: AsyncSession,
        *,
        execution_id: UUID,
        entries: list[DeadLetterWrite],
    ) -> list[DeadLetterEntry]:
        created: list[DeadLetterEntry] = []
        for entry in entries:
            obj = DeadLetterEntry(
                execution_id=execution_id,
                node_id=entry.node_id,
                error_message=entry.error_message,
                payload=entry.payload,
            )
            db.add(obj)
            created.append(obj)
        await db.flush()
        return created

    def create_entries_sync(
        self,
        *,
        execution_id: UUID,
        entries: list[DeadLetterWrite],
    ) -> list[UUID]:
        async def _run() -> list[UUID]:
            async with async_session_factory() as session:
                created = await self.create_entries(
                    session,
                    execution_id=execution_id,
                    entries=entries,
                )
                await session.commit()
                return [entry.id for entry in created]

        return asyncio.run(_run())

    async def list_entries(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID | None = None,
        execution_id: UUID | None = None,
        include_resolved: bool = False,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[DeadLetterListItem], int]:
        filters: list[Any] = []
        if workflow_id is not None:
            filters.append(WorkflowExecution.workflow_id == workflow_id)
        if execution_id is not None:
            filters.append(DeadLetterEntry.execution_id == execution_id)
        if not include_resolved:
            filters.append(DeadLetterEntry.resolved_at.is_(None))

        stmt = (
            select(DeadLetterEntry, WorkflowExecution.workflow_id)
            .join(WorkflowExecution, WorkflowExecution.id == DeadLetterEntry.execution_id)
            .where(*filters)
            .order_by(DeadLetterEntry.created_at.desc(), DeadLetterEntry.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        rows = (await db.execute(stmt)).all()

        count_stmt = (
            select(func.count())
            .select_from(DeadLetterEntry)
            .join(WorkflowExecution, WorkflowExecution.id == DeadLetterEntry.execution_id)
            .where(*filters)
        )
        total = int((await db.execute(count_stmt)).scalar_one() or 0)

        items = [
            DeadLetterListItem(
                id=entry.id,
                execution_id=entry.execution_id,
                workflow_id=wf_id,
                node_id=entry.node_id,
                error_message=entry.error_message,
                payload=entry.payload,
                retry_count=entry.retry_count,
                created_at=entry.created_at,
                resolved_at=entry.resolved_at,
            )
            for entry, wf_id in rows
        ]
        return items, total

    async def retry_entry(
        self,
        db: AsyncSession,
        *,
        dead_letter_id: UUID,
    ) -> dict[str, Any]:
        row = await db.execute(
            select(
                DeadLetterEntry,
                Workflow,
                func.coalesce(Workflow.workspace_id, Project.workspace_id).label(
                    "effective_workspace_id"
                ),
            )
            .join(WorkflowExecution, WorkflowExecution.id == DeadLetterEntry.execution_id)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .outerjoin(Project, Project.id == Workflow.project_id)
            .where(DeadLetterEntry.id == dead_letter_id)
        )
        loaded = row.one_or_none()
        if loaded is None:
            raise ValueError(f"Dead-letter '{dead_letter_id}' nao encontrado.")

        entry: DeadLetterEntry = loaded[0]
        workflow: Workflow = loaded[1]
        workspace_id: UUID | None = loaded[2]

        if entry.resolved_at is not None:
            return {
                "dead_letter_id": entry.id,
                "resolved": True,
                "retry_count": entry.retry_count,
                "status": "resolved",
                "message": "Dead-letter ja foi resolvido anteriormente.",
                "output": None,
            }

        node = _find_node_definition(workflow.definition, entry.node_id)
        if node is None:
            raise ValueError(
                f"No '{entry.node_id}' nao encontrado na definicao do workflow."
            )

        node_type = _resolve_processor_type(node)
        if node_type is None:
            raise ValueError(
                f"No '{entry.node_id}' nao suporta retry direto por dead-letter."
            )

        payload = _payload_for_retry(entry.payload)
        retry_execution_id = str(uuid4())
        reference = ensure_duckdb_reference(
            payload,
            retry_execution_id,
            f"{entry.node_id}_dead_letter_retry",
        )
        context = {
            "execution_id": retry_execution_id,
            "workflow_id": str(workflow.id),
            "input_data": payload,
            "upstream_results": {
                "__dead_letter_retry__": {
                    "node_id": "__dead_letter_retry__",
                    "status": "success",
                    "output_field": "data",
                    "data": reference,
                }
            },
        }

        try:
            from app.orchestration.tasks.node_processor import execute_registered_node

            resolved_connections = await connection_service.resolve_for_workflow(
                db,
                workflow.definition,
                project_id=workflow.project_id,
                workspace_id=workspace_id,
            )
            effective_config = _inject_connection_string(
                dict(node.get("data") or {}),
                resolved_connections,
            )
            output = await execute_registered_node(
                node_id=entry.node_id,
                node_type=node_type,
                config=effective_config,
                context=context,
            )
        except Exception as exc:
            entry.retry_count += 1
            entry.error_message = str(exc)
            entry.resolved_at = None
            await db.commit()
            return {
                "dead_letter_id": entry.id,
                "resolved": False,
                "retry_count": entry.retry_count,
                "status": "failed",
                "message": str(exc),
                "output": None,
            }

        entry.retry_count += 1
        remaining_payload = _extract_failed_payload(output)
        if remaining_payload is None:
            entry.resolved_at = datetime.now(timezone.utc)
            await db.commit()
            return {
                "dead_letter_id": entry.id,
                "resolved": True,
                "retry_count": entry.retry_count,
                "status": str(output.get("status") or "success"),
                "message": "Dead-letter reprocessado com sucesso.",
                "output": output,
            }

        entry.payload = remaining_payload
        entry.error_message = _extract_error_message(output, remaining_payload)
        entry.resolved_at = None
        await db.commit()
        return {
            "dead_letter_id": entry.id,
            "resolved": False,
            "retry_count": entry.retry_count,
            "status": str(output.get("status") or "partial"),
            "message": entry.error_message,
            "output": output,
        }


def _find_node_definition(
    workflow_definition: dict[str, Any],
    node_id: str,
) -> dict[str, Any] | None:
    nodes = workflow_definition.get("nodes") if isinstance(workflow_definition, dict) else None
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id")) == node_id:
            return node
    return None


def _resolve_processor_type(node: dict[str, Any]) -> str | None:
    from app.services.workflow.nodes import has_processor

    node_type = str(node.get("type") or node.get("data", {}).get("type") or "")
    if has_processor(node_type):
        return node_type
    return None


def _inject_connection_string(
    config: dict[str, Any],
    resolved_connections: dict[str, str],
) -> dict[str, Any]:
    conn_id = config.get("connection_id")
    if conn_id is None:
        return config
    conn_str = resolved_connections.get(str(conn_id))
    if conn_str is None:
        raise ValueError(
            f"connection_id '{conn_id}' nao encontrado nas conexoes resolvidas."
        )
    return {**config, "connection_string": conn_str}


def _payload_for_retry(payload: dict[str, Any]) -> Any:
    rows = payload.get("rows")
    if isinstance(rows, list):
        return rows
    return payload


def _extract_failed_payload(output: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(output, dict):
        return None

    branches = output.get("branches")
    if isinstance(branches, dict):
        ref = branches.get("on_error")
        if isinstance(ref, dict):
            rows = _read_rows_from_reference(ref)
            if not rows:
                return None
            if len(rows) == 1:
                return rows[0]
            return {"rows": rows}

    payload = output.get("failed_rows")
    if isinstance(payload, list) and payload:
        if len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        return {"rows": payload}
    if isinstance(payload, dict):
        return payload
    return None


def _extract_error_message(
    output: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    payload_error = payload.get("_dead_letter_error")
    if isinstance(payload_error, str) and payload_error.strip():
        return payload_error.strip()
    output_error = output.get("error") or output.get("error_message")
    if isinstance(output_error, str) and output_error.strip():
        return output_error.strip()
    return "Falha remanescente apos retry."


def _read_rows_from_reference(reference: dict[str, Any]) -> list[dict[str, Any]]:
    if find_duckdb_reference(reference) is None:
        return []

    conn = duckdb.connect(str(reference["database_path"]), read_only=True)
    try:
        cursor = conn.execute(f"SELECT * FROM {build_table_ref(reference)}")
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


dead_letter_service = DeadLetterService()
