"""Endpoints REST para webhooks de saida (Prompt 6.3).

Caminho ``/webhook-subscriptions`` (em vez de ``/webhooks``) para nao colidir
com os webhooks de ENTRADA — esses ja consomem ``/webhooks/...`` no
workflow.

Permissoes
----------
- Listar/CRUD/replay: requer role MANAGER no workspace dono da subscription.
- Test (POST /test): mesma regra — MANAGER. Disparar HTTP arbitrario
  para URLs configuradas e operacao sensivel.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import authorization_service
from app.models import User
from app.models.webhook_subscription import (
    WebhookDeadLetter,
    WebhookDelivery,
    WebhookSubscription,
)
from app.schemas.webhook_subscription import (
    WebhookDeadLetterDetail,
    WebhookDeadLetterRead,
    WebhookDeliveryDetail,
    WebhookDeliveryRead,
    WebhookReplayResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionRead,
    WebhookSubscriptionRotated,
    WebhookSubscriptionUpdate,
    WebhookTestRequest,
    WebhookTestResponse,
)
from app.services.webhook_dispatch_service import (
    generate_secret,
    webhook_dispatch_service,
)
from app.services.webhooks.replay_limiter import (
    ReplayRateLimitExceeded,
    replay_limiter,
)


router = APIRouter(prefix="/webhook-subscriptions", tags=["webhook-subscriptions"])


# ---------------------------------------------------------------------------
# Helpers de permissao
# ---------------------------------------------------------------------------


async def _ensure_workspace_manager(
    db: AsyncSession, user: User, workspace_id: UUID,
) -> None:
    allowed = await authorization_service.has_permission(
        db=db,
        user_id=user.id,
        scope="workspace",
        required_role="MANAGER",
        scope_id=workspace_id,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas MANAGER do workspace pode gerenciar webhooks.",
        )


async def _load_subscription_or_404(
    db: AsyncSession, subscription_id: UUID,
) -> WebhookSubscription:
    sub = await db.get(WebhookSubscription, subscription_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription nao encontrada.",
        )
    return sub


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=WebhookSubscriptionCreated, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: WebhookSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSubscriptionCreated:
    await _ensure_workspace_manager(db, current_user, body.workspace_id)

    secret = generate_secret()
    sub = WebhookSubscription(
        workspace_id=body.workspace_id,
        url=str(body.url),
        events=body.events,
        secret=secret,
        description=body.description,
        active=body.active,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    # Resposta UNICA com o secret em texto puro — o cliente DEVE armazenar.
    return WebhookSubscriptionCreated(
        id=sub.id,
        workspace_id=sub.workspace_id,
        url=sub.url,
        events=sub.events,
        description=sub.description,
        active=sub.active,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
        last_attempt_at=sub.last_attempt_at,
        last_status_code=sub.last_status_code,
        secret=sub.secret,
    )


@router.get("", response_model=list[WebhookSubscriptionRead])
async def list_subscriptions(
    workspace_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WebhookSubscription]:
    await _ensure_workspace_manager(db, current_user, workspace_id)
    result = await db.execute(
        select(WebhookSubscription)
        .where(WebhookSubscription.workspace_id == workspace_id)
        .order_by(WebhookSubscription.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{subscription_id}", response_model=WebhookSubscriptionRead)
async def get_subscription(
    subscription_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSubscription:
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)
    return sub


@router.patch("/{subscription_id}", response_model=WebhookSubscriptionRead)
async def update_subscription(
    subscription_id: UUID,
    body: WebhookSubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSubscription:
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)

    if body.url is not None:
        sub.url = str(body.url)
    if body.events is not None:
        sub.events = body.events
    if body.description is not None:
        sub.description = body.description
    if body.active is not None:
        sub.active = body.active
    if body.rotate_secret:
        sub.secret = generate_secret()

    await db.commit()
    await db.refresh(sub)
    return sub


@router.post(
    "/{subscription_id}/rotate-secret",
    response_model=WebhookSubscriptionRotated,
)
async def rotate_secret(
    subscription_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSubscriptionRotated:
    """Atalho: rota dedicada para rotacionar o secret e devolver o valor novo.

    Equivale a PATCH com ``rotate_secret=true``, mas separada porque a
    UI tipicamente chama em fluxo distinto (botao "rotacionar segredo").
    """
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)
    sub.secret = generate_secret()
    await db.commit()
    return WebhookSubscriptionRotated(id=sub.id, secret=sub.secret)


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_subscription(
    subscription_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)
    await db.delete(sub)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Test / Replay
# ---------------------------------------------------------------------------


@router.post("/{subscription_id}/test", response_model=WebhookTestResponse)
async def test_subscription(
    subscription_id: UUID,
    body: WebhookTestRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookTestResponse:
    """Dispara um POST sintetico imediatamente e retorna o resultado.

    Differente do dispatch normal: roda inline e nao retenta. Cria uma
    delivery com event=``webhook.test`` para que apareca no historico.
    """
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)

    custom = body.custom_payload if body else None
    success, code, error, delivery_id = await webhook_dispatch_service.deliver_test(
        db, subscription=sub, custom_payload=custom,
    )
    return WebhookTestResponse(
        delivery_id=delivery_id,
        status_code=code,
        success=success,
        error=error,
    )


# ---------------------------------------------------------------------------
# Deliveries (read-only)
# ---------------------------------------------------------------------------


@router.get(
    "/{subscription_id}/deliveries",
    response_model=list[WebhookDeliveryRead],
)
async def list_deliveries(
    subscription_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WebhookDelivery]:
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)

    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == subscription_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(WebhookDelivery.status == status_filter)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{subscription_id}/deliveries/{delivery_id}",
    response_model=WebhookDeliveryDetail,
)
async def get_delivery(
    subscription_id: UUID,
    delivery_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookDelivery:
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)

    delivery = await db.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.subscription_id != subscription_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery nao encontrada.",
        )
    return delivery


# ---------------------------------------------------------------------------
# Dead-letters
# ---------------------------------------------------------------------------


@router.get(
    "/{subscription_id}/dead-letters",
    response_model=list[WebhookDeadLetterRead],
)
async def list_dead_letters(
    subscription_id: UUID,
    include_resolved: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WebhookDeadLetter]:
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)

    stmt = (
        select(WebhookDeadLetter)
        .where(WebhookDeadLetter.subscription_id == subscription_id)
        .order_by(WebhookDeadLetter.created_at.desc())
        .limit(limit)
    )
    if not include_resolved:
        stmt = stmt.where(WebhookDeadLetter.resolved_at.is_(None))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{subscription_id}/dead-letters/{dead_letter_id}",
    response_model=WebhookDeadLetterDetail,
)
async def get_dead_letter(
    subscription_id: UUID,
    dead_letter_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookDeadLetter:
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)
    dl = await db.get(WebhookDeadLetter, dead_letter_id)
    if dl is None or dl.subscription_id != subscription_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead-letter nao encontrado.",
        )
    return dl


@router.post(
    "/{subscription_id}/dead-letters/{dead_letter_id}/replay",
    response_model=WebhookReplayResponse,
    status_code=status.HTTP_201_CREATED,
)
async def replay_dead_letter(
    subscription_id: UUID,
    dead_letter_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookReplayResponse:
    """Cria uma nova delivery a partir do dead-letter; marca-o resolvido.

    O worker picka a delivery normalmente — se voltar a falhar, gera um
    NOVO dead-letter (o atual fica resolved_at preenchido como rastro).
    """
    sub = await _load_subscription_or_404(db, subscription_id)
    await _ensure_workspace_manager(db, current_user, sub.workspace_id)
    dl = await db.get(WebhookDeadLetter, dead_letter_id)
    if dl is None or dl.subscription_id != subscription_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead-letter nao encontrado.",
        )
    if dl.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dead-letter ja foi resolvido (replay anterior).",
        )

    # Rate limit (Tarefa 5): 1 replay/min do mesmo dead-letter,
    # 5 replays/h de uma mesma subscription.
    try:
        await replay_limiter.check_and_increment(
            subscription_id=subscription_id,
            dead_letter_id=dead_letter_id,
            workspace_id=sub.workspace_id,
        )
    except ReplayRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.reason,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    new_delivery = await webhook_dispatch_service.replay_dead_letter(
        db, dead_letter=dl,
    )
    await db.commit()
    return WebhookReplayResponse(
        new_delivery_id=new_delivery.id,
        dead_letter_id=dl.id,
    )


# ---------------------------------------------------------------------------
# Dashboard helper — quantos dead-letters pendentes por workspace
# ---------------------------------------------------------------------------


@router.get("/dead-letters/summary")
async def dead_letters_summary(
    workspace_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Conta dead-letters NAO resolvidos por subscription do workspace.

    Util para a UI mostrar o badge "X webhooks em alerta" sem fazer N
    requests por subscription.
    """
    await _ensure_workspace_manager(db, current_user, workspace_id)
    result = await db.execute(
        select(
            WebhookDeadLetter.subscription_id,
            func.count(WebhookDeadLetter.id).label("count"),
        )
        .join(
            WebhookSubscription,
            WebhookSubscription.id == WebhookDeadLetter.subscription_id,
        )
        .where(
            WebhookSubscription.workspace_id == workspace_id,
            WebhookDeadLetter.resolved_at.is_(None),
        )
        .group_by(WebhookDeadLetter.subscription_id)
    )
    rows = result.all()
    return {
        "by_subscription": {str(sid): int(c) for sid, c in rows},
        "total": int(sum(c for _, c in rows)),
    }
