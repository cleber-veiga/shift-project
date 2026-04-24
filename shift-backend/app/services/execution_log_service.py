"""
Servico de log estruturado para execucoes de workflows.

Objetivo: permitir troubleshooting remoto de consultores via endpoint
``GET /executions/{id}/logs`` sem exigir acesso ao servidor.

Arquitetura:
- Escrita bufferizada em memoria, flush em batch a cada N logs ou T segundos.
- Integra-se com o ``event_sink`` do ``dynamic_runner`` via wrapper: cada
  evento emitido pelo runner (``node_start``, ``node_complete``, ``node_error``,
  ``node_retry``, ``execution_start``, ``execution_end``, ``execution.cancelled``)
  gera uma linha em ``workflow_execution_logs``.
- Payloads de dados NAO sao persistidos — apenas metadados + amostras com
  PII mascarada em erros.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.workflow import WorkflowExecutionLog

logger = get_logger(__name__)

# --- Mascaramento de PII em samples de linha ------------------------------
# Regexes conservadores — matcham apenas padroes reconhecidos para evitar
# destruir dados de debug em campos comuns (codigos, ids numericos, etc.).
_EMAIL_RE = re.compile(r"[\w\.\-\+]+@[\w\.\-]+\.[A-Za-z]{2,}")
# CPF com mascara (000.000.000-00) ou 11 digitos seguidos.
_CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b")
# CNPJ com mascara (00.000.000/0000-00) ou 14 digitos seguidos.
_CNPJ_RE = re.compile(
    r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|\b\d{14}\b"
)
# Telefone BR (10 ou 11 digitos) com ou sem ponctuacao.
_PHONE_RE = re.compile(
    r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}"
)

# Chaves que, quando encontradas no contexto, disparam o mascaramento
# recursivo de PII nos seus valores. ``failed_row_sample`` e o contrato
# que bulk_insert/load_service usam para reportar linha problematica.
_PII_MASK_CONTAINER_KEYS = frozenset({
    "failed_row_sample",
    "row",
    "sample_row",
    "problematic_row",
})


def _mask_pii_in_string(value: str) -> str:
    """Substitui padroes de PII por tokens redacted.

    Ordem importa: CNPJ (14 digitos) precisa bater antes de CPF (11)
    para nao ser reduzido para "***" partialmente.
    """
    out = _EMAIL_RE.sub("<email_redacted>", value)
    out = _CNPJ_RE.sub("<cnpj_redacted>", out)
    out = _CPF_RE.sub("<cpf_redacted>", out)
    out = _PHONE_RE.sub("<phone_redacted>", out)
    return out


def _mask_pii(value: Any) -> Any:
    """Aplica ``_mask_pii_in_string`` recursivamente em dicts/listas/strings."""
    if isinstance(value, str):
        return _mask_pii_in_string(value)
    if isinstance(value, dict):
        return {k: _mask_pii(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_pii(v) for v in value]
    return value


# Chaves que nao devem aparecer no ``context`` do log (mesmo que o evento as
# traga). Manter lista restrita — a ideia e troubleshooting, nao auditoria
# completa. Payloads pesados (``output``, ``data``, ``rows``) sao dropados
# sempre, independentemente do nome da chave.
_LOG_CONTEXT_DROP_KEYS = frozenset({
    "output",
    "data",
    "rows",
    "upstream_results",
    "connection_string",
    "password",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
    "private_key",
})

# Mapeamento evento -> (level, message_template)
_EVENT_LEVEL_MAP: dict[str, str] = {
    "execution_start": "info",
    "execution_end": "info",
    "execution.cancelled": "warning",
    "node_start": "info",
    "node_complete": "info",
    "node_error": "error",
    "node_retry": "warning",
    "node_skip": "warning",
    "error": "error",
}

# Flush sempre que o buffer atingir este tamanho (evita crescer sem limite
# em workflows com milhares de nos). Valor conservador — a tabela aceita
# INSERT em batch com muita folga.
_FLUSH_BATCH_SIZE = 50

# Ou quando o batch mais antigo ficar mais velho que isso (segundos).
_FLUSH_INTERVAL_SECONDS = 5.0


def _sanitize_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extrai metadados limpos do payload do evento para o campo ``context``.

    Mantem tipos primitivos e pequenos dicts. Descarta qualquer chave que
    bata com ``_LOG_CONTEXT_DROP_KEYS`` e qualquer valor que, serializado,
    passe de 4KB (truncado para ``{"_truncated": true, "length": N}``).
    """
    if not isinstance(payload, dict):
        return None

    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _LOG_CONTEXT_DROP_KEYS:
            continue
        # Descarta chaves redundantes ja capturadas em colunas dedicadas.
        if key in ("type", "timestamp", "execution_id", "node_id", "message"):
            continue
        # Samples de linha problematica passam pelo mascarador de PII antes
        # de entrar no log — mantem utilidade para debug sem expor dados
        # sensiveis. Mantemos estrutura completa (dict aninhado), ignorando
        # o ``_PII_MASK_CONTAINER_KEYS`` do caminho generico abaixo.
        if key in _PII_MASK_CONTAINER_KEYS and isinstance(value, (dict, list)):
            out[key] = _mask_pii(value)
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, (list, tuple)):
            if len(value) > 10:
                out[key] = {"_truncated": True, "length": len(value)}
            else:
                out[key] = [v for v in value if isinstance(v, (str, int, float, bool, type(None)))]
        elif isinstance(value, dict):
            # 1 nivel de dict; drops pesados recursivamente.
            inner: dict[str, Any] = {}
            for k2, v2 in value.items():
                if k2 in _LOG_CONTEXT_DROP_KEYS:
                    continue
                if isinstance(v2, (str, int, float, bool)) or v2 is None:
                    inner[k2] = v2
            if inner:
                out[key] = inner
    return out or None


class ExecutionLogBuffer:
    """Buffer async de logs por execucao, com flush periodico em batch.

    Cada instancia e dedicada a uma execucao — criada no inicio do run,
    fechada (com flush) ao final. Thread-safe dentro do mesmo event loop
    (asyncio.Lock).
    """

    def __init__(self, execution_id: UUID | str) -> None:
        self.execution_id = UUID(str(execution_id))
        self._pending: list[WorkflowExecutionLog] = []
        self._lock = asyncio.Lock()
        self._last_flush = asyncio.get_event_loop().time()
        self._closed = False

    async def record(
        self,
        *,
        level: str,
        message: str,
        node_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Adiciona uma linha ao buffer, dispara flush se atingir o limite."""
        if self._closed:
            return

        entry = WorkflowExecutionLog(
            execution_id=self.execution_id,
            node_id=(node_id[:255] if isinstance(node_id, str) else None),
            timestamp=datetime.now(timezone.utc),
            level=(level if level in ("info", "warning", "error") else "info"),
            message=(message[:8000] if isinstance(message, str) else str(message)[:8000]),
            context=context,
        )

        async with self._lock:
            self._pending.append(entry)
            should_flush = (
                len(self._pending) >= _FLUSH_BATCH_SIZE
                or (asyncio.get_event_loop().time() - self._last_flush) >= _FLUSH_INTERVAL_SECONDS
            )

        if should_flush:
            await self.flush()

    async def flush(self) -> None:
        """Persiste o buffer em batch e limpa."""
        async with self._lock:
            if not self._pending:
                self._last_flush = asyncio.get_event_loop().time()
                return
            batch = self._pending
            self._pending = []
            self._last_flush = asyncio.get_event_loop().time()

        try:
            async with async_session_factory() as session:
                session.add_all(batch)
                await session.commit()
        except Exception as exc:  # noqa: BLE001 — log nunca derruba execucao
            logger.warning(
                "execution_log.flush_failed",
                execution_id=str(self.execution_id),
                batch_size=len(batch),
                error=f"{type(exc).__name__}: {exc}",
            )

    async def close(self) -> None:
        """Final flush + fecha o buffer (no-op apos close)."""
        await self.flush()
        self._closed = True

    def event_sink_wrapper(
        self,
        inner: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> Callable[[dict[str, Any]], Awaitable[None]]:
        """Embrulha um ``event_sink`` existente para tambem gravar em log.

        Cada evento relevante (ver ``_EVENT_LEVEL_MAP``) vira uma linha no log.
        Se ``inner`` e None, cria um sink novo que so escreve no log.
        """

        async def _sink(event: dict[str, Any]) -> None:
            # Grava no log mesmo que o inner falhe.
            try:
                evt_type = str(event.get("type") or "")
                level = _EVENT_LEVEL_MAP.get(evt_type, "info")
                message = self._build_message(evt_type, event)
                node_id = event.get("node_id")
                if not isinstance(node_id, str):
                    node_id = None
                await self.record(
                    level=level,
                    message=message,
                    node_id=node_id,
                    context=_sanitize_context(event),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "execution_log.sink_wrapper_failed",
                    error=f"{type(exc).__name__}: {exc}",
                )

            if inner is not None:
                await inner(event)

        return _sink

    @staticmethod
    def _build_message(evt_type: str, event: dict[str, Any]) -> str:
        """Monta uma mensagem curta, legivel, a partir do tipo do evento."""
        node_id = event.get("node_id")
        label = event.get("label")
        node_ref = f"[{label or node_id}]" if (label or node_id) else ""

        if evt_type == "execution_start":
            return "Execucao iniciada."
        if evt_type == "execution_end":
            return f"Execucao finalizada com status: {event.get('status', 'unknown')}."
        if evt_type == "execution.cancelled":
            return "Execucao cancelada."
        if evt_type == "node_start":
            return f"{node_ref} iniciou.".strip()
        if evt_type == "node_complete":
            duration = event.get("duration_ms")
            rows_out = event.get("row_count_out")
            parts = []
            if rows_out is not None:
                parts.append(f"{rows_out} linhas")
            if duration is not None:
                parts.append(f"{duration}ms")
            suffix = f" ({', '.join(parts)})" if parts else ""
            return f"{node_ref} concluido{suffix}.".strip()
        if evt_type == "node_error":
            err = event.get("error") or "erro desconhecido"
            return f"{node_ref} falhou: {str(err)[:500]}".strip()
        if evt_type == "node_retry":
            attempt = event.get("attempt")
            max_attempts = event.get("max_attempts")
            return f"{node_ref} retry {attempt}/{max_attempts}.".strip()
        if evt_type == "node_skip":
            reason = event.get("reason") or "dependencia falhou"
            return f"{node_ref} ignorado: {str(reason)[:500]}".strip()
        if evt_type == "error":
            return f"Erro: {str(event.get('error') or event.get('message') or '???')[:500]}"
        return f"Evento: {evt_type}"


async def record_execution_log(
    execution_id: UUID | str,
    level: str,
    message: str,
    *,
    node_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Escreve uma unica linha de log de forma autonoma (sem buffer).

    Util para pontos fora do event_sink (ex: erros de validacao no preflight
    do ``workflow_service``). Prefira o buffer quando possivel.
    """
    try:
        async with async_session_factory() as session:
            entry = WorkflowExecutionLog(
                execution_id=UUID(str(execution_id)),
                node_id=(node_id[:255] if isinstance(node_id, str) else None),
                timestamp=datetime.now(timezone.utc),
                level=(level if level in ("info", "warning", "error") else "info"),
                message=(message[:8000] if isinstance(message, str) else str(message)[:8000]),
                context=context,
            )
            session.add(entry)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "execution_log.record_failed",
            execution_id=str(execution_id),
            error=f"{type(exc).__name__}: {exc}",
        )
