"""SSE plumbing para ``POST /workflows/{id}/test``.

Sem orquestracao nem persistencia — delega a
``workflow_service.run_with_events`` e so converte eventos do runner em
linhas SSE, aplicando ``_trim_for_sse`` em producao.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator
from uuid import UUID

from app.db.session import async_session_factory

_SSE_PREVIEW_ROWS = 100
_EVENT_POLL_TIMEOUT = 0.1


class WorkflowTestService:
    """Converte eventos do ``dynamic_runner`` em Server-Sent Events."""

    async def run_streaming(
        self,
        workflow_id: UUID,
        target_node_id: str | None = None,
        mode: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        # Import tardio evita ciclo em alguns setups de teste
        # (workflow_service importa modelos que podem puxar outras rotas).
        from app.services.workflow_service import workflow_service

        events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def sink(evt: dict[str, Any]) -> None:
            await events.put(evt)

        total_start = time.monotonic()

        async def _driver() -> None:
            async with async_session_factory() as db:
                try:
                    await workflow_service.run_with_events(
                        db=db,
                        workflow_id=workflow_id,
                        event_sink=sink,
                        mode=mode,
                        target_node_id=target_node_id,
                        input_data=input_data,
                    )
                except ValueError as exc:
                    # Workflow nao encontrado / projeto orfao — reporta via fila.
                    await events.put({"type": "error", "error": str(exc)})

        runner_task: asyncio.Task[None] = asyncio.create_task(
            _driver(), name=f"workflow-test-{workflow_id}"
        )

        try:
            while True:
                if runner_task.done() and events.empty():
                    break
                try:
                    evt = await asyncio.wait_for(
                        events.get(), timeout=_EVENT_POLL_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    continue

                sse_payload = _transform_for_sse(evt, mode or "test", total_start)
                if sse_payload is not None:
                    yield _sse(sse_payload)
        except asyncio.CancelledError:
            runner_task.cancel()
            try:
                await runner_task
            except BaseException:
                pass
            raise


# ─── Codificacao de linhas SSE ────────────────────────────────────────────────

def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ─── Transformacao runner -> SSE ──────────────────────────────────────────────

def _transform_for_sse(
    evt: dict[str, Any],
    mode: str,
    total_start: float,
) -> dict[str, Any] | None:
    """Mapeia evento do runner para o shape SSE esperado pelo frontend.

    Detalhe nao-obvio:
    - ``node_skipped`` vira ``node_complete`` com
      ``output={status:skipped,reason:...}`` — legado para nao quebrar
      clientes existentes.
    - ``node_error_handled`` tambem vira ``node_complete`` para que o
      frontend marque o no como concluido com metadados de erro tratado,
      sem depender de um novo tipo de evento SSE.
    """
    evt_type = evt.get("type")

    if evt_type == "execution_start":
        return {
            "type": "execution_start",
            "execution_id": evt.get("execution_id"),
            "node_count": evt.get("node_count", 0),
            "mode": evt.get("mode", mode),
            "timestamp": evt.get("timestamp"),
        }

    if evt_type == "node_start":
        return {
            "type": "node_start",
            "node_id": evt.get("node_id"),
            "node_type": evt.get("node_type"),
            "label": evt.get("label"),
            "timestamp": evt.get("timestamp"),
        }

    if evt_type == "node_complete":
        output = evt.get("output") or {}
        sse_output = _trim_for_sse(output) if mode == "production" else output
        payload: dict[str, Any] = {
            "type": "node_complete",
            "node_id": evt.get("node_id"),
            "label": evt.get("label"),
            "output": sse_output,
            "duration_ms": evt.get("duration_ms", 0),
            "timestamp": evt.get("timestamp"),
        }
        if evt.get("is_pinned"):
            payload["is_pinned"] = True
        return payload

    if evt_type == "node_error":
        return {
            "type": "node_error",
            "node_id": evt.get("node_id"),
            "label": evt.get("label"),
            "error": evt.get("error"),
            "duration_ms": evt.get("duration_ms", 0),
            "timestamp": evt.get("timestamp"),
        }

    if evt_type == "node_error_handled":
        return {
            "type": "node_complete",
            "node_id": evt.get("node_id"),
            "label": evt.get("label"),
            "output": {
                "status": "handled_error",
                "active_handle": "on_error",
                "error": evt.get("error"),
                "error_type": evt.get("error_type"),
            },
            "duration_ms": evt.get("duration_ms", 0),
            "timestamp": evt.get("timestamp"),
        }

    if evt_type == "node_skipped":
        reason = evt.get("reason") or "skipped"
        return {
            "type": "node_complete",
            "node_id": evt.get("node_id"),
            "label": evt.get("label"),
            "output": {"status": "skipped", "reason": reason},
            "duration_ms": evt.get("duration_ms", 0),
            "timestamp": evt.get("timestamp"),
        }

    if evt_type == "execution_end":
        status_map = {
            "completed": "SUCCESS",
            "failed": "FAILED",
            "aborted": "ABORTED",
            "cancelled": "CANCELLED",
        }
        runner_status = str(evt.get("status") or "completed")
        total_ms = int((time.monotonic() - total_start) * 1000)
        return {
            "type": "execution_complete",
            "execution_id": evt.get("execution_id"),
            "status": status_map.get(runner_status, runner_status.upper()),
            "duration_ms": total_ms,
            "timestamp": evt.get("timestamp"),
        }

    # Eventos desconhecidos / ``error`` de preflight — repasse cru.
    return evt


def _trim_for_sse(output: dict[str, Any]) -> dict[str, Any]:
    """Corta ``rows`` longos em producao (hoje so o caminho pinnedOutput
    carrega rows cruos; ``_summarize_result`` ja cuida dos demais)."""
    if not isinstance(output, dict):
        return output

    rows = output.get("rows")
    if not isinstance(rows, list) or len(rows) <= _SSE_PREVIEW_ROWS:
        return output

    trimmed = {**output}
    trimmed["rows"] = rows[:_SSE_PREVIEW_ROWS]
    trimmed["is_preview"] = True
    trimmed["total_rows"] = len(rows)
    return trimmed


workflow_test_service = WorkflowTestService()
