"""
No executor — roda as tools aprovadas e grava o audit log.

Re-valida o UserContext antes de cada chamada (instanciando a dataclass
imutavel a partir do dict serializado no estado) e sempre grava em
agent_audit_log, mesmo em caso de erro.

Fase 6: sanitiza o resultado bruto antes de devolver ao grafo/LLM. O
audit log continua recebendo o preview RAW (observabilidade humana);
apenas o estado carrega o payload envelopado em <tool_result>. Avisos
do sanitizer viram log_metadata para inspecao.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.agent.context import UserContext
from app.services.agent.persistence import write_audit_log
from app.services.agent.graph.state import PlatformAgentState
from app.services.agent.safety.sanitizer import sanitize_tool_result, wrap_tool_result
from app.services.agent.tools.registry import execute_tool

logger = get_logger(__name__)

_PREVIEW_LIMIT = 500


def _rebuild_user_context(raw: dict[str, Any]) -> UserContext:
    """Reconstroi UserContext a partir do dict persistido no estado."""
    return UserContext(
        user_id=UUID(str(raw["user_id"])),
        workspace_id=UUID(str(raw["workspace_id"])),
        project_id=UUID(str(raw["project_id"])) if raw.get("project_id") else None,
        workspace_role=str(raw["workspace_role"]),
        project_role=raw.get("project_role"),
        organization_id=UUID(str(raw["organization_id"])),
        organization_role=raw.get("organization_role"),
    )


async def execute_node(state: PlatformAgentState) -> dict[str, Any]:
    """Executa cada approved_action sequencialmente."""
    actions = state.get("approved_actions") or []
    if not actions:
        return {"executed_actions": []}

    thread_id_str = state.get("thread_id")
    if not thread_id_str:
        return {"executed_actions": [], "error": "thread_id ausente em execute_node"}
    thread_uuid = UUID(thread_id_str)

    ctx_raw = state.get("user_context") or {}
    try:
        ctx = _rebuild_user_context(ctx_raw)
    except (KeyError, ValueError) as exc:
        logger.exception("agent.execute.bad_context", thread_id=thread_id_str)
        return {
            "executed_actions": [],
            "error": f"UserContext invalido: {exc}",
        }

    approval_id = state.get("approval_id")
    approval_uuid = UUID(approval_id) if approval_id else None

    results: list[dict[str, Any]] = []
    for action in actions:
        tool_name = str(action.get("tool", ""))
        arguments = dict(action.get("arguments") or {})

        started = time.perf_counter()
        error_message: str | None = None
        status = "success"
        raw_result = ""

        async with async_session_factory() as session:
            try:
                raw_result = await execute_tool(
                    tool_name,
                    arguments,
                    db=session,
                    user_context=ctx,
                )
            except Exception as exc:  # noqa: BLE001
                status = "error"
                error_message = str(exc)
                logger.exception(
                    "agent.execute.tool_crashed",
                    thread_id=thread_id_str,
                    tool=tool_name,
                )

        duration_ms = int((time.perf_counter() - started) * 1000)
        raw_preview = raw_result[:_PREVIEW_LIMIT] if raw_result else None

        sanitized, warnings = sanitize_tool_result(
            raw_result or "", tool_name=tool_name
        )
        safe_payload = wrap_tool_result(sanitized, tool_name=tool_name) if raw_result else ""
        safe_preview = safe_payload[:_PREVIEW_LIMIT] if safe_payload else None

        log_metadata: dict[str, Any] | None = None
        if warnings:
            log_metadata = {"sanitizer_warnings": warnings}
            logger.warning(
                "agent.execute.sanitizer_flagged",
                thread_id=thread_id_str,
                tool=tool_name,
                warnings=warnings,
            )

        try:
            async with async_session_factory() as audit_session:
                await write_audit_log(
                    audit_session,
                    thread_id=thread_uuid,
                    user_id=ctx.user_id,
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    status=status,
                    approval_id=approval_uuid,
                    tool_result_preview=raw_preview,
                    error_message=error_message,
                    duration_ms=duration_ms,
                    log_metadata=log_metadata,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "agent.execute.audit_failed",
                thread_id=thread_id_str,
                tool=tool_name,
            )

        results.append(
            {
                "tool": tool_name,
                "arguments": arguments,
                "status": status,
                "preview": safe_preview,
                "error": error_message,
                "duration_ms": duration_ms,
            }
        )

    return {"executed_actions": results}
