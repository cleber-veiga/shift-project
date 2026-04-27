"""Schemas Pydantic para webhooks de saida (Prompt 6.3).

A interface esconde o ``secret`` em todas as respostas EXCETO
``WebhookSubscriptionCreated``, devolvido APENAS no POST inicial. Apos
isso, o secret nunca mais aparece — se o cliente perdeu, gera um novo
via PATCH (rotate).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import HttpUrl

from app.models.webhook_subscription import SUPPORTED_EVENTS
from app.services.webhooks.url_validator import validate_webhook_url


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------


class WebhookSubscriptionCreate(BaseModel):
    """Body do POST /webhook-subscriptions."""

    workspace_id: UUID
    url: HttpUrl
    events: list[str] = Field(min_length=1)
    description: str | None = None
    active: bool = True

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url_ssrf(cls, v: str | HttpUrl) -> HttpUrl:
        # Validacao SSRF dedicada — bloqueia hosts internos, IPs privados,
        # e hostnames que resolvem pra rede interna. Falha com
        # ``WebhookUrlError`` (subclasse de ``ValueError``), que pydantic
        # converte em 422 com mensagem opaca — detalhes ficam em log.
        return validate_webhook_url(v)

    @field_validator("events")
    @classmethod
    def _validate_events(cls, v: list[str]) -> list[str]:
        invalid = [e for e in v if e not in SUPPORTED_EVENTS]
        if invalid:
            raise ValueError(
                f"Eventos nao suportados: {invalid}. Suportados: {list(SUPPORTED_EVENTS)}"
            )
        # Deduplica preservando ordem.
        seen: set[str] = set()
        return [e for e in v if not (e in seen or seen.add(e))]


class WebhookSubscriptionUpdate(BaseModel):
    """Body do PATCH /webhook-subscriptions/{id}.

    Todos os campos opcionais — apenas os fornecidos sao atualizados.
    Para rotacionar o secret use ``rotate_secret=True``; o backend gera
    um novo e o devolve em ``WebhookSubscriptionRotated``.
    """

    url: HttpUrl | None = None
    events: list[str] | None = None
    description: str | None = None
    active: bool | None = None
    rotate_secret: bool = False

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url_ssrf(cls, v: str | HttpUrl | None) -> HttpUrl | None:
        if v is None:
            return None
        return validate_webhook_url(v)

    @field_validator("events")
    @classmethod
    def _validate_events(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        invalid = [e for e in v if e not in SUPPORTED_EVENTS]
        if invalid:
            raise ValueError(
                f"Eventos nao suportados: {invalid}. Suportados: {list(SUPPORTED_EVENTS)}"
            )
        seen: set[str] = set()
        return [e for e in v if not (e in seen or seen.add(e))]


class WebhookSubscriptionRead(BaseModel):
    """Representacao publica — NUNCA inclui secret."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    url: str
    events: list[str]
    description: str | None
    active: bool
    created_at: datetime
    updated_at: datetime
    last_attempt_at: datetime | None
    last_status_code: int | None


class WebhookSubscriptionCreated(WebhookSubscriptionRead):
    """Apenas o POST inicial devolve o secret em texto puro.

    O cliente DEVE armazenar — depois disso o backend nunca mais expoe.
    """

    secret: str


class WebhookSubscriptionRotated(BaseModel):
    """Resposta do PATCH com ``rotate_secret=True``."""

    id: UUID
    secret: str


# ---------------------------------------------------------------------------
# Deliveries (somente leitura)
# ---------------------------------------------------------------------------


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subscription_id: UUID
    event: str
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    execution_id: UUID | None
    # ``payload`` omitido aqui — exposto apenas no detalhamento individual
    # (``GET /webhook-subscriptions/{id}/deliveries/{delivery_id}``) para
    # nao inflar a listagem.


class WebhookDeliveryDetail(WebhookDeliveryRead):
    """Detalhes completos: inclui o payload que foi enviado."""

    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Dead-letters
# ---------------------------------------------------------------------------


class WebhookDeadLetterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subscription_id: UUID
    delivery_id: UUID | None
    event: str
    last_status_code: int | None
    last_error: str | None
    attempt_count: int
    created_at: datetime
    resolved_at: datetime | None


class WebhookDeadLetterDetail(WebhookDeadLetterRead):
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Test / Replay actions
# ---------------------------------------------------------------------------


class WebhookTestRequest(BaseModel):
    """Body opcional de POST /webhook-subscriptions/{id}/test.

    Por default usa um payload sintetico fixo; ``custom_payload`` permite
    ao cliente testar a forma exata que ele recebera no formato real.
    """

    custom_payload: dict[str, Any] | None = None


class WebhookTestResponse(BaseModel):
    """Resposta sincrona do dispatch de teste — diferente do fluxo
    assincrono normal: o teste roda inline e retorna o status code."""

    delivery_id: UUID | None = None
    status_code: int | None = None
    success: bool
    error: str | None = None


class WebhookReplayResponse(BaseModel):
    """Resposta de POST /webhook-dead-letters/{id}/replay."""

    new_delivery_id: UUID
    dead_letter_id: UUID
