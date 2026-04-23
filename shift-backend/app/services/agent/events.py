"""
Tipos de eventos SSE e helpers de formatacao para a API do Platform Agent.

O frontend consome estes eventos para renderizar o progresso da conversa.
"""

from __future__ import annotations

import json
from typing import Any


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Formata um evento SSE no padrao 'event:\\ndata:\\n\\n'."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


# ---------------------------------------------------------------------------
# Constantes de tipos de eventos (evita strings magicas nos consumidores)
# ---------------------------------------------------------------------------

EVT_META = "meta"
EVT_THINKING = "thinking"
EVT_GUARDRAILS_REFUSE = "guardrails_refuse"
EVT_INTENT_DETECTED = "intent_detected"
EVT_PLAN_PROPOSED = "plan_proposed"
EVT_APPROVAL_REQUIRED = "approval_required"
EVT_TOOL_CALL_START = "tool_call_start"
EVT_TOOL_CALL_END = "tool_call_end"
EVT_DELTA = "delta"
EVT_DONE = "done"
EVT_ERROR = "error"
EVT_THREAD_CREATED = "thread_created"
EVT_CLARIFICATION = "clarification_required"
