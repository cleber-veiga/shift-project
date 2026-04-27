"""Servico de despacho de webhooks de saida (Prompt 6.3).

Arquitetura
-----------
A entrega usa a tabela ``webhook_deliveries`` como FILA PERSISTENTE — em vez
de Celery + broker (Redis/RabbitMQ). Justificativa:

- O codebase ja roda APScheduler com SQLAlchemyJobStore (persistencia
  sobrevive a restart). Adicionar Celery aqui exigiria broker novo,
  worker dedicado e uma camada extra de monitoramento.
- O volume esperado e modesto (uma entrega por execucao terminal,
  multiplicado por subscriptions ativas — tipicamente <100/min).
- ``FOR UPDATE SKIP LOCKED`` no Postgres da semantica de fila concorrente
  segura sem broker.

Quando o volume justificar, basta substituir o `dispatch_due_loop` por
um worker Celery lendo a mesma tabela — schema e payload nao mudam.

Backoff exponencial
-------------------
Sequencia: 1s, 5s, 30s, 5min, 30min, 2h. ``max_attempts`` default 6.
Esta sequencia foi pedida no spec e e exatamente o que `_BACKOFF_SECONDS`
abaixo codifica.

NOTA sobre freshness: o worker poll a fila a cada 5s (default
``WEBHOOK_DISPATCH_INTERVAL_SECONDS``). O backoff de 1s apos a 1a falha
e portanto arredondado para ate 5s no pior caso. Aceitavel — nenhum
cliente real exige sub-segundo de freshness em webhook async.

Politica de retry
-----------------
- 2xx       → marca delivered, atualiza last_status_code na subscription.
- 4xx       → MOVE PARA DEAD-LETTER imediatamente. Cliente reportou erro
              sintaticamente (mau body, auth invalida, URL errada). Tentar
              de novo nao ajuda.
- 5xx       → retry com backoff. Cliente esta indisponivel mas pode voltar.
- timeout / network error → retry com backoff (mesma classe de 5xx).
- Apos esgotar ``max_attempts`` → dead-letter.

HMAC
----
Header ``X-Shift-Signature`` no formato ``sha256=<hex>``. O hex e
HMAC-SHA256 do body bruto serializado (bytes UTF-8) com o ``secret`` da
subscription. Cliente verifica:

```python
import hmac, hashlib
expected = "sha256=" + hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
hmac.compare_digest(expected, request.headers["X-Shift-Signature"])
```

Tambem incluimos ``X-Shift-Event``, ``X-Shift-Delivery-Id`` e
``X-Shift-Timestamp`` (UNIX seconds) — o timestamp ajuda a detectar replay
attacks (cliente pode rejeitar timestamps antigos > 5min).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from prometheus_client import Counter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.observability.metrics import (
    SPAWNER_ACTIVE,
    SPAWNER_ERRORS_TOTAL,
    SPAWNER_SPAWNED_TOTAL,
)
from app.db.session import async_session_factory
from app.models.webhook_subscription import (
    WebhookDeadLetter,
    WebhookDelivery,
    WebhookSubscription,
)
from app.core.observability.tracing import (
    extract_trace_context,
    inject_trace_context,
    tracer,
)
from app.services.webhooks.url_validator import _ip_is_dangerous as _ip_dangerous


logger = logging.getLogger(__name__)


# Sequencia oficial pedida no spec.
_BACKOFF_SECONDS: tuple[int, ...] = (
    1,        # apos a 1a falha
    5,        # apos a 2a
    30,       # apos a 3a
    5 * 60,   # apos a 4a
    30 * 60,  # apos a 5a
    2 * 3600, # apos a 6a (so cabe se max_attempts > 6)
)

# Total de tentativas que faremos antes de dead-letter. Inclui a 1a:
# 1 (imediata) + 5 retries = 6.
DEFAULT_MAX_ATTEMPTS = 6

# Timeout por POST individual. 10s e o numero pedido no spec — gera retry
# em qualquer cliente lento alem disso. Em testes, monkeypatch para valores
# menores para nao esperar 10s reais.
DEFAULT_HTTP_TIMEOUT_S = 10.0


# Numero maximo de deliveries processadas em paralelo num unico tick do
# worker. Acima disso, sobram para o proximo tick — evita estourar o pool
# de conexoes do banco e sockets do httpx.
_MAX_PARALLEL_DELIVERIES_PER_TICK = 8


# Status terminais da entrega.
STATUS_PENDING = "pending"
STATUS_IN_FLIGHT = "in_flight"
STATUS_DELIVERED = "delivered"
STATUS_FAILED = "failed"


# Status HTTP de redirect que tratamos como TERMINAL — vao para dead-letter
# imediato, sem retry. Permitir follow_redirects abre vetor de SSRF (cliente
# externo redireciona para 127.0.0.1/admin, 169.254.169.254, etc).
_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})


# ---------------------------------------------------------------------------
# Erros e metricas de seguranca (Tarefa 2 do hardening 6.2/6.3)
# ---------------------------------------------------------------------------


class WebhookSecurityError(Exception):
    """Marca falha de policy de seguranca no dispatch (vs erro HTTP normal).

    Usado para distinguir bloqueios dos quais NAO devemos tentar recuperar
    (DNS rebind, redirect para rede interna) dos retryables tradicionais
    (timeout, 5xx). Um ``WebhookSecurityError`` sempre vira outcome
    ``terminal`` → dead-letter imediato.
    """


WEBHOOK_SECURITY_BLOCKED = Counter(
    "webhook_security_blocked_total",
    "Webhook bloqueado por politica de seguranca no dispatch.",
    ("reason",),  # ssrf_dns_rebind | redirect_blocked | dns_unresolvable
)


def _resolve_and_check(host: str, port: int) -> None:
    """Re-resolve o ``host`` no momento do dispatch e levanta
    ``WebhookSecurityError`` se cair em rede interna.

    Defesa contra DNS rebinding: o atacante cadastra ``evil.com`` (DNS
    legitimo no momento do CREATE), depois muda o DNS pra responder
    ``169.254.169.254`` quando o dispatcher resolver de novo.

    NAO substitui a Tarefa 1 (validacao no schema) — ambas sao defesa
    em camadas. Aqui pega o caso especifico de TOCTOU entre cadastro e
    primeiro POST (ou entre POSTs sucessivos).

    Quando ``WEBHOOK_ALLOW_INSECURE_HOSTS`` esta ativo, esta checagem e
    pulada — mesmo bypass que o validator do schema.
    """
    import os
    if (os.getenv("WEBHOOK_ALLOW_INSECURE_HOSTS") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        WEBHOOK_SECURITY_BLOCKED.labels("dns_unresolvable").inc()
        raise WebhookSecurityError(
            "URL nao resolvivel pela politica de seguranca."
        )

    for _family, _stype, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _ip_dangerous(ip):
            WEBHOOK_SECURITY_BLOCKED.labels("ssrf_dns_rebind").inc()
            # Log: somente hostname (nao IP — evita confirmar pro
            # atacante que DNS rebinding foi detectado).
            logger.warning(
                "webhook.dispatch.dns_rebind_blocked",
                extra={"host": host},
            )
            raise WebhookSecurityError(
                "URL bloqueada por politica de seguranca."
            )


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------


def generate_secret() -> str:
    """Gera um secret HMAC novo — 32 bytes URL-safe (~43 chars).

    Usado tanto na criacao de subscription quanto em rotate_secret.
    """
    return secrets.token_urlsafe(32)


def compute_signature(secret: str, body_bytes: bytes) -> str:
    """Calcula o valor do header ``X-Shift-Signature``.

    Formato: ``sha256=<hex>``. ``hmac.compare_digest`` na verificacao do
    cliente garante comparacao em tempo constante.
    """
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body_bytes: bytes, signature_header: str) -> bool:
    """Verifica o header ``X-Shift-Signature``. Util em testes / SDK do cliente."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = compute_signature(secret, body_bytes)
    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------


def compute_next_attempt_delay(attempt_count: int) -> int:
    """Devolve o delay em segundos APOS a ``attempt_count``-esima falha.

    ``attempt_count`` aqui e quantas tentativas JA falharam. Para o primeiro
    retry (apos a primeira falha), ``attempt_count == 1`` -> 1s.

    Quando ``attempt_count`` excede ``len(_BACKOFF_SECONDS)``, repete o
    ultimo (defensivo — se max_attempts for aumentado depois).
    """
    if attempt_count < 1:
        return 0
    idx = min(attempt_count - 1, len(_BACKOFF_SECONDS) - 1)
    return _BACKOFF_SECONDS[idx]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WebhookDispatchService:
    """Encapsula enqueue, dispatch (POST) e retry/dead-letter de webhooks.

    NAO mantem estado de instancia — todo state vive em DB. Isso permite
    multiplas replicas do backend executando o worker periodico
    simultaneamente; o ``FOR UPDATE SKIP LOCKED`` evita corrida.
    """

    # ------------------------------------------------------------------
    # ENQUEUE — chamado pelo workflow_service ao final de uma execucao
    # ------------------------------------------------------------------

    async def enqueue_for_event(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        event: str,
        payload: dict[str, Any],
        execution_id: UUID | None = None,
    ) -> int:
        """Cria uma WebhookDelivery por subscription ATIVA do workspace
        que assinou ``event``. Retorna o numero de deliveries criadas.

        Nao despacha imediatamente — o worker periodico picka. Mesmo quando
        chamamos ``trigger_dispatch_now`` em seguida, a serializacao via
        DB garante exactly-once-or-more com idempotencia natural (cada
        delivery tem ID unico e o cliente verifica o ``X-Shift-Delivery-Id``).
        """
        result = await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.workspace_id == workspace_id,
                WebhookSubscription.active.is_(True),
                # Postgres ARRAY contains operator: ``@>``.
                WebhookSubscription.events.contains([event]),
            )
        )
        subscriptions = result.scalars().all()
        if not subscriptions:
            return 0

        # Captura W3C Trace Context AGORA — quem chama enqueue_for_event
        # esta dentro do span de execucao. Quando o worker pegar a delivery
        # (possivelmente em outro processo), reativa este contexto antes do
        # POST, garantindo que ``webhook.dispatch`` vire child do span de
        # execucao mesmo cruzando boundary Celery / event loop.
        trace_carrier: dict[str, str] = {}
        try:
            inject_trace_context(trace_carrier)
        except Exception:  # noqa: BLE001 — tracing nao pode quebrar enqueue
            trace_carrier = {}

        for sub in subscriptions:
            db.add(
                WebhookDelivery(
                    subscription_id=sub.id,
                    event=event,
                    payload=payload,
                    execution_id=execution_id,
                    next_attempt_at=datetime.now(timezone.utc),
                    max_attempts=DEFAULT_MAX_ATTEMPTS,
                    trace_context=trace_carrier or None,
                )
            )
        await db.flush()
        return len(subscriptions)

    # ------------------------------------------------------------------
    # DISPATCH — escolhe deliveries due e processa em paralelo
    # ------------------------------------------------------------------

    async def dispatch_due(
        self,
        *,
        now: datetime | None = None,
        max_parallel: int = _MAX_PARALLEL_DELIVERIES_PER_TICK,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> int:
        """Picka deliveries due e processa em paralelo. Retorna a contagem.

        Ciclo do worker:
        1. SELECT FOR UPDATE SKIP LOCKED — pega ate ``max_parallel`` deliveries
           com ``status='pending'`` e ``next_attempt_at <= now()``.
        2. UPDATE → ``status='in_flight'`` para prevenir double-pick.
        3. Sai do lock, dispara em paralelo via httpx.AsyncClient.
        4. Cada resultado atualiza a propria delivery (sucesso, retry, ou
           dead-letter).
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Etapa 1+2: pickar e marcar in_flight numa transacao curta.
        async with async_session_factory() as session:
            result = await session.execute(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.status == STATUS_PENDING,
                    WebhookDelivery.next_attempt_at <= now,
                )
                .order_by(WebhookDelivery.next_attempt_at.asc())
                .limit(max_parallel)
                .with_for_update(skip_locked=True)
            )
            picked = list(result.scalars().all())
            if not picked:
                return 0

            ids = [d.id for d in picked]
            await session.execute(
                update(WebhookDelivery)
                .where(WebhookDelivery.id.in_(ids))
                .values(status=STATUS_IN_FLIGHT)
            )
            await session.commit()

            # Recarrega com a subscription para evitar lazy load no async client.
            result = await session.execute(
                select(WebhookDelivery, WebhookSubscription)
                .join(
                    WebhookSubscription,
                    WebhookSubscription.id == WebhookDelivery.subscription_id,
                )
                .where(WebhookDelivery.id.in_(ids))
            )
            pairs = list(result.all())

        # Etapa 3: HTTP em paralelo (fora da transacao do banco).
        SPAWNER_ACTIVE.labels("webhook_dispatch").set(len(pairs))
        SPAWNER_SPAWNED_TOTAL.labels("webhook_dispatch").inc(len(pairs))
        try:
            # ``follow_redirects=False`` e CRITICO: redirect 3xx para
            # ``127.0.0.1`` (ou outro internal) seria SSRF ressuscitado
            # apos a Tarefa 1. Tratamos 3xx como falha terminal abaixo.
            client_kwargs: dict[str, Any] = {
                "timeout": http_timeout,
                "follow_redirects": False,
            }
            if transport is not None:
                client_kwargs["transport"] = transport
            async with httpx.AsyncClient(**client_kwargs) as client:
                outcomes = await asyncio.gather(
                    *(self._post_one(client, d, s) for d, s in pairs),
                    return_exceptions=True,
                )
        finally:
            SPAWNER_ACTIVE.labels("webhook_dispatch").set(0)

        # Etapa 4: persistir resultado de cada delivery.
        for (delivery, subscription), outcome in zip(pairs, outcomes):
            try:
                await self._persist_outcome(delivery, subscription, outcome)
            except Exception:  # noqa: BLE001 — log mas nao quebra outras
                logger.exception(
                    "webhook.persist_outcome_failed",
                    extra={"delivery_id": str(delivery.id)},
                )
        return len(pairs)

    # ------------------------------------------------------------------
    # POST + classificacao do outcome
    # ------------------------------------------------------------------

    async def _post_one(
        self,
        client: httpx.AsyncClient,
        delivery: WebhookDelivery,
        subscription: WebhookSubscription,
    ) -> "_DeliveryOutcome":
        # --- Trace propagation (Tarefa 3) ---
        # Reconstroi o contexto do span de execucao upstream a partir do
        # trace_context salvo em enqueue. Permite que o ``webhook.dispatch``
        # span vire child mesmo num worker que rodou minutos depois.
        otel_ctx = None
        # ``getattr`` defensivo — durante o periodo de migration a coluna
        # pode estar ausente em testes que constroem stubs minimos. Caller
        # com modelo real sempre tem o atributo.
        trace_ctx_raw = getattr(delivery, "trace_context", None)
        if trace_ctx_raw:
            try:
                otel_ctx = extract_trace_context(trace_ctx_raw)
            except Exception:  # noqa: BLE001
                otel_ctx = None

        # Abre o span filho — atributos abaixo populam apos o response.
        span_kwargs: dict[str, Any] = {}
        if otel_ctx is not None:
            span_kwargs["context"] = otel_ctx
        with tracer().start_as_current_span(
            "webhook.dispatch", **span_kwargs,
        ) as span:
            outcome = await self._post_one_inner(
                client, delivery, subscription, span,
            )
            # Marca atributos de outcome no span — uma chamada por
            # request, importa pra dashboards de tracing.
            try:
                span.set_attribute("webhook.outcome", outcome.kind)
                if outcome.status_code is not None:
                    span.set_attribute("http.status_code", outcome.status_code)
            except Exception:  # noqa: BLE001
                pass
            return outcome

    async def _post_one_inner(
        self,
        client: httpx.AsyncClient,
        delivery: WebhookDelivery,
        subscription: WebhookSubscription,
        span: Any,
    ) -> "_DeliveryOutcome":
        # Atributos basicos do span — uteis para correlacionar no Jaeger/Tempo.
        try:
            span.set_attribute("webhook.subscription_id", str(subscription.id))
            span.set_attribute("webhook.delivery_id", str(delivery.id))
            span.set_attribute("webhook.event", delivery.event)
            span.set_attribute(
                "webhook.attempt_count",
                int(getattr(delivery, "attempt_count", 0) or 0),
            )
            span.set_attribute(
                "http.url", _scrub_url_for_span(str(subscription.url)),
            )
            span.set_attribute("http.method", "POST")
        except Exception:  # noqa: BLE001
            pass

        body_bytes = _serialize_payload(delivery.payload)
        signature = compute_signature(subscription.secret, body_bytes)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Shift-Webhook/1.0",
            "X-Shift-Signature": signature,
            "X-Shift-Event": delivery.event,
            "X-Shift-Delivery-Id": str(delivery.id),
            "X-Shift-Timestamp": str(int(time.time())),
        }
        # --- Trace propagation no wire ---
        # Injeta ``traceparent`` / ``tracestate`` (W3C) no request outbound
        # para que o servico cliente possa correlacionar. No-op silencioso
        # quando tracing esta desabilitado.
        try:
            inject_trace_context(headers)
        except Exception:  # noqa: BLE001
            pass

        # --- Defesa contra DNS rebinding (Tarefa 2) ---
        # Re-resolve o host AGORA. Se atacante mudou o DNS depois do
        # cadastro pra apontar pra rede interna, captura aqui e nao posta.
        # Erro vira ``terminal`` (dead-letter, sem retry).
        try:
            parsed = urlparse(str(subscription.url))
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            await asyncio.to_thread(_resolve_and_check, host, port)
        except WebhookSecurityError as exc:
            return _DeliveryOutcome(
                kind="terminal",
                status_code=None,
                error=str(exc),
            )

        try:
            response = await client.post(
                subscription.url,
                content=body_bytes,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            return _DeliveryOutcome(
                kind="retryable",
                status_code=None,
                error=f"timeout: {exc.__class__.__name__}",
            )
        except httpx.HTTPError as exc:
            # ConnectError, RemoteProtocolError, etc — todos retryable.
            return _DeliveryOutcome(
                kind="retryable",
                status_code=None,
                error=f"network: {exc.__class__.__name__}: {exc}",
            )

        status = response.status_code

        # --- Redirect blocking (Tarefa 2) ---
        # ``follow_redirects=False`` no client garante que httpx nao segue
        # automaticamente. Aqui transformamos em falha terminal — nao
        # retentar e nao seguir manualmente.
        if status in _REDIRECT_STATUSES:
            location = response.headers.get("Location") or ""
            redirect_host = _safe_host_from_redirect(location)
            WEBHOOK_SECURITY_BLOCKED.labels("redirect_blocked").inc()
            logger.warning(
                "webhook.dispatch.redirect_blocked",
                extra={
                    "from_host": _safe_host_from_redirect(str(subscription.url)),
                    "to_host": redirect_host,
                    "status": status,
                },
            )
            return _DeliveryOutcome(
                kind="terminal",
                status_code=status,
                error="Redirect rejeitado por politica de seguranca",
            )

        if 200 <= status < 300:
            return _DeliveryOutcome(kind="success", status_code=status, error=None)
        if 400 <= status < 500:
            # 4xx = erro do cliente (auth, body invalido, URL errada).
            # NAO retentar — vai para dead-letter direto.
            return _DeliveryOutcome(
                kind="terminal",
                status_code=status,
                error=f"4xx response: {status}",
            )
        # 5xx: retryable.
        return _DeliveryOutcome(
            kind="retryable",
            status_code=status,
            error=f"server response: {status}",
        )

    async def _persist_outcome(
        self,
        delivery: WebhookDelivery,
        subscription: WebhookSubscription,
        outcome: "_DeliveryOutcome | BaseException",
    ) -> None:
        """Atualiza linhas no DB conforme o resultado da entrega."""
        if isinstance(outcome, BaseException):
            # Excecao inesperada (nao deveria acontecer — _post_one captura
            # tudo). Trata como retryable defensivamente.
            outcome = _DeliveryOutcome(
                kind="retryable",
                status_code=None,
                error=f"unexpected: {outcome!r}",
            )

        async with async_session_factory() as session:
            # Reload com o lock para escrita.
            d = await session.get(WebhookDelivery, delivery.id, with_for_update=True)
            if d is None:
                return
            sub = await session.get(WebhookSubscription, subscription.id)

            d.attempt_count += 1
            d.last_status_code = outcome.status_code
            d.last_error = outcome.error[:500] if outcome.error else None
            now = datetime.now(timezone.utc)

            if outcome.kind == "success":
                d.status = STATUS_DELIVERED
                d.delivered_at = now
                if sub is not None:
                    sub.last_attempt_at = now
                    sub.last_status_code = outcome.status_code
            elif outcome.kind == "terminal":
                # 4xx — dead-letter imediato, sem retry.
                d.status = STATUS_FAILED
                d.failed_at = now
                if sub is not None:
                    sub.last_attempt_at = now
                    sub.last_status_code = outcome.status_code
                session.add(_build_dead_letter(d, outcome))
                SPAWNER_ERRORS_TOTAL.labels(
                    "webhook_dispatch", "ClientError4xx"
                ).inc()
            else:  # retryable
                if d.attempt_count >= d.max_attempts:
                    # Esgotou — dead-letter.
                    d.status = STATUS_FAILED
                    d.failed_at = now
                    if sub is not None:
                        sub.last_attempt_at = now
                        sub.last_status_code = outcome.status_code
                    session.add(_build_dead_letter(d, outcome))
                    SPAWNER_ERRORS_TOTAL.labels(
                        "webhook_dispatch", "MaxRetriesExceeded"
                    ).inc()
                else:
                    delay_s = compute_next_attempt_delay(d.attempt_count)
                    d.status = STATUS_PENDING
                    d.next_attempt_at = now + timedelta(seconds=delay_s)
                    if sub is not None:
                        sub.last_attempt_at = now
                        sub.last_status_code = outcome.status_code

            await session.commit()

    # ------------------------------------------------------------------
    # TEST — dispatch sincrono pra UI testar uma URL
    # ------------------------------------------------------------------

    async def deliver_test(
        self,
        db: AsyncSession,
        *,
        subscription: WebhookSubscription,
        custom_payload: dict[str, Any] | None = None,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> tuple[bool, int | None, str | None, UUID | None]:
        """Envia um payload de teste e retorna (success, status_code, error, delivery_id).

        Cria uma delivery com ``event='webhook.test'`` mas a manda pela
        mesma maquinaria de POST + assinatura — apenas roda inline em vez
        de delegar pro worker. Persiste a delivery para que apareca no
        historico (status final delivered/failed).
        """
        payload = custom_payload or _default_test_payload(subscription)
        delivery = WebhookDelivery(
            subscription_id=subscription.id,
            event="webhook.test",
            payload=payload,
            status=STATUS_IN_FLIGHT,
            max_attempts=1,  # testes nao retentam — feedback imediato pra UI
            next_attempt_at=datetime.now(timezone.utc),
        )
        db.add(delivery)
        await db.flush()  # pega ID

        client_kwargs: dict[str, Any] = {
            "timeout": http_timeout,
            "follow_redirects": False,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        async with httpx.AsyncClient(**client_kwargs) as client:
            outcome = await self._post_one(client, delivery, subscription)

        delivery.attempt_count = 1
        delivery.last_status_code = outcome.status_code
        delivery.last_error = outcome.error[:500] if outcome.error else None
        now = datetime.now(timezone.utc)
        if outcome.kind == "success":
            delivery.status = STATUS_DELIVERED
            delivery.delivered_at = now
        else:
            delivery.status = STATUS_FAILED
            delivery.failed_at = now
        subscription.last_attempt_at = now
        subscription.last_status_code = outcome.status_code
        await db.commit()
        return (
            outcome.kind == "success",
            outcome.status_code,
            outcome.error,
            delivery.id,
        )

    # ------------------------------------------------------------------
    # REPLAY — reentrega manual de um dead-letter
    # ------------------------------------------------------------------

    async def replay_dead_letter(
        self,
        db: AsyncSession,
        *,
        dead_letter: WebhookDeadLetter,
    ) -> WebhookDelivery:
        """Cria nova ``WebhookDelivery`` a partir do dead-letter e marca-o resolvido.

        Nao envia inline — joga na fila normal para que o worker processe.
        """
        new_delivery = WebhookDelivery(
            subscription_id=dead_letter.subscription_id,
            event=dead_letter.event,
            payload=dead_letter.payload,
            next_attempt_at=datetime.now(timezone.utc),
            max_attempts=DEFAULT_MAX_ATTEMPTS,
        )
        db.add(new_delivery)
        dead_letter.resolved_at = datetime.now(timezone.utc)
        await db.flush()
        return new_delivery


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


class _DeliveryOutcome:
    """Resultado de uma tentativa POST.

    ``kind``:
    - ``success``  : 2xx
    - ``terminal`` : 4xx — vai para dead-letter sem retry
    - ``retryable``: 5xx, timeout, network error
    """

    __slots__ = ("kind", "status_code", "error")

    def __init__(self, *, kind: str, status_code: int | None, error: str | None) -> None:
        self.kind = kind
        self.status_code = status_code
        self.error = error


def _serialize_payload(payload: dict[str, Any]) -> bytes:
    """Serializa o payload de forma deterministica para o body POST.

    ``sort_keys=True`` garante que o cliente que recalcular o HMAC
    independentemente chegue ao mesmo digest.
    """
    return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")


def _build_dead_letter(
    delivery: WebhookDelivery,
    outcome: _DeliveryOutcome,
) -> WebhookDeadLetter:
    return WebhookDeadLetter(
        subscription_id=delivery.subscription_id,
        delivery_id=delivery.id,
        event=delivery.event,
        payload=delivery.payload,
        last_status_code=outcome.status_code,
        last_error=outcome.error[:500] if outcome.error else None,
        attempt_count=delivery.attempt_count,
    )


def _scrub_url_for_span(url: str) -> str:
    """Remove userinfo/credenciais (``user:pass@host``) de URLs antes de
    setar como atributo de span. Nao remove path — paths sao geralmente
    seguros e o cliente os escolheu publicamente."""
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
    except Exception:  # noqa: BLE001
        pass
    return url


def _safe_host_from_redirect(location: str) -> str:
    """Extrai hostname de uma URL de redirect para log, sem path/query.

    Logs de seguranca devem mostrar PRA ONDE o redirect tentou levar
    (host) sem expor caminhos sensitivos. URLs relativas viram ``""``.
    """
    if not location:
        return "<empty>"
    try:
        parsed = urlparse(location)
        return parsed.hostname or "<relative>"
    except Exception:  # noqa: BLE001
        return "<unparseable>"


def _default_test_payload(subscription: WebhookSubscription) -> dict[str, Any]:
    return {
        "event": "webhook.test",
        "subscription_id": str(subscription.id),
        "workspace_id": str(subscription.workspace_id),
        "message": "Este e um payload de teste do Shift.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Singleton + APScheduler hook
# ---------------------------------------------------------------------------


webhook_dispatch_service = WebhookDispatchService()


# Intervalo do worker periodico — 5s default.
#
# Por que NAO 1s: cada tick faz um SELECT FOR UPDATE SKIP LOCKED +
# pickup + UPDATE + reload. Em deploy com Postgres serverless (Neon) ou
# com latencia >1s, esse roundtrip ja e mais lento que o proprio tick,
# causando ``JOB_MAX_INSTANCES_REACHED`` em rajada e flood de log.
#
# Trade-off de freshness: o backoff curto (1s apos a 1a falha) fica
# arredondado para ate 5s no pior caso. Webhooks sao assincronos — nenhum
# cliente espera entrega sub-segundo.
#
# Quem precisar mais frequente em ambientes locais com Postgres rapido
# pode setar ``WEBHOOK_DISPATCH_INTERVAL_SECONDS=1`` via env.
_DISPATCH_INTERVAL_SECONDS = float(
    getattr(settings, "WEBHOOK_DISPATCH_INTERVAL_SECONDS", 5.0)
)


async def _dispatch_tick() -> None:
    """Tick periodico do worker de webhooks — module-level porque o
    ``SQLAlchemyJobStore`` do APScheduler precisa serializar a referencia
    via ``module:funcname``, o que NAO funciona com closures (capturadas
    pela funcao register, ficam nao-pickle-aveis).

    Falhas individuais sao logadas mas nao propagam para nao matar o
    scheduler — proximo tick tenta de novo.
    """
    try:
        await webhook_dispatch_service.dispatch_due()
    except Exception:  # noqa: BLE001
        logger.exception("webhook.dispatch_tick_failed")


def register_dispatch_job(scheduler: Any) -> None:
    """Registra job APScheduler que chama ``dispatch_due`` periodicamente.

    Idempotente — se o job ja existe (replicas ou restart), substitui.
    Ate o codebase migrar para Celery (caso volume justifique), este e o
    runner oficial.
    """
    scheduler.add_job(
        _dispatch_tick,
        trigger="interval",
        seconds=_DISPATCH_INTERVAL_SECONDS,
        id="webhook_dispatch_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        name="Webhook dispatch tick",
    )
