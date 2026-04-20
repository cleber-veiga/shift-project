"""
Servico de gerenciamento de chaves de API do Platform Agent.

Responsavel por criar, validar, listar, revogar e deletar AgentApiKey.
Plaintext e retornado uma unica vez na criacao; depois apenas prefix
e hash sao persistidos. Hash usa Argon2 via pwdlib (mesmo algoritmo
das senhas de usuario).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import (
    authorization_service,
    hash_password,
    verify_password,
)
from app.models.agent_api_key import AgentApiKey
from app.models.user import User
from app.services.agent.tools.registry import TOOL_REGISTRY

logger = get_logger(__name__)


# Prefixo visivel do plaintext (inclui marcador publico sk_shift_ + 4 chars
# aleatorios). 13 chars no total, indexado para lookup rapido no validate().
_PLAINTEXT_MARKER = "sk_shift_"
_PREFIX_RANDOM_CHARS = 4
_PREFIX_LENGTH = len(_PLAINTEXT_MARKER) + _PREFIX_RANDOM_CHARS

_WS_ROLE_RANK: dict[str, int] = {"VIEWER": 0, "CONSULTANT": 1, "MANAGER": 2}
_PROJECT_ROLE_RANK: dict[str, int] = {"CLIENT": 0, "EDITOR": 1}


class AgentApiKeyError(Exception):
    """Erro de negocio ao manipular chaves de API."""


class AgentApiKeyPermissionError(AgentApiKeyError):
    """Usuario tentou criar/revogar chave alem do proprio nivel."""


class AgentApiKeyValidationError(AgentApiKeyError):
    """Dados invalidos (tools desconhecidas, role fora de faixa, etc.)."""


def _generate_plaintext_key() -> str:
    """Retorna sk_shift_ + ~48 chars url-safe base64 (>= 256 bits de entropia)."""
    suffix = secrets.token_urlsafe(36)
    return f"{_PLAINTEXT_MARKER}{suffix}"


def _extract_prefix(plaintext: str) -> str:
    """Extrai prefixo visivel (sk_shift_XXXX) do plaintext."""
    return plaintext[:_PREFIX_LENGTH]


class AgentApiKeyService:
    async def create(
        self,
        db: AsyncSession,
        *,
        creator: User,
        workspace_id: UUID,
        project_id: UUID | None,
        name: str,
        max_workspace_role: str,
        max_project_role: str | None,
        allowed_tools: list[str],
        require_human_approval: bool,
        expires_at: datetime | None,
    ) -> tuple[AgentApiKey, str]:
        """Cria uma nova chave e retorna (entidade, plaintext).

        O plaintext retornado NUNCA deve ser persistido; e devolvido uma
        unica vez para o criador copiar. Apenas prefix e hash Argon2 sao
        gravados.
        """
        if max_workspace_role not in _WS_ROLE_RANK:
            raise AgentApiKeyValidationError(
                f"max_workspace_role invalido: '{max_workspace_role}'"
            )
        if (
            max_project_role is not None
            and max_project_role not in _PROJECT_ROLE_RANK
        ):
            raise AgentApiKeyValidationError(
                f"max_project_role invalido: '{max_project_role}'"
            )

        self._validate_allowed_tools(allowed_tools)

        await self._ensure_creator_role_covers_max(
            db,
            creator=creator,
            workspace_id=workspace_id,
            project_id=project_id,
            max_workspace_role=max_workspace_role,
            max_project_role=max_project_role,
        )

        plaintext = _generate_plaintext_key()
        prefix = _extract_prefix(plaintext)
        key_hash = hash_password(plaintext)

        entity = AgentApiKey(
            name=name.strip(),
            prefix=prefix,
            key_hash=key_hash,
            workspace_id=workspace_id,
            project_id=project_id,
            created_by=creator.id,
            max_workspace_role=max_workspace_role,
            max_project_role=max_project_role,
            allowed_tools=list(allowed_tools),
            require_human_approval=require_human_approval,
            expires_at=expires_at,
        )
        db.add(entity)
        await db.flush()
        await db.refresh(entity)
        logger.info(
            "agent_api_key.created",
            api_key_id=str(entity.id),
            workspace_id=str(workspace_id),
            project_id=str(project_id) if project_id else None,
            created_by=str(creator.id),
            prefix=prefix,
            tools=allowed_tools,
        )
        return entity, plaintext

    async def validate(
        self,
        db: AsyncSession,
        *,
        plaintext_key: str,
    ) -> AgentApiKey | None:
        """Valida chave plaintext. Atualiza last_used_at + usage_count em sucesso.

        Retorna None se:
          - formato invalido
          - nenhuma chave com o prefixo existe
          - hash nao confere para nenhuma candidata
          - chave revogada
          - chave expirada
        """
        if not plaintext_key or not plaintext_key.startswith(_PLAINTEXT_MARKER):
            return None
        if len(plaintext_key) < _PREFIX_LENGTH + 10:
            return None

        prefix = _extract_prefix(plaintext_key)
        stmt = select(AgentApiKey).where(AgentApiKey.prefix == prefix)
        candidates = list((await db.execute(stmt)).scalars().all())
        if not candidates:
            return None

        now = datetime.now(timezone.utc)
        matched: AgentApiKey | None = None
        for candidate in candidates:
            try:
                if verify_password(plaintext_key, candidate.key_hash):
                    matched = candidate
                    break
            except Exception:  # noqa: BLE001
                continue

        if matched is None:
            return None

        if matched.revoked_at is not None:
            return None
        if matched.expires_at is not None and matched.expires_at <= now:
            return None

        matched.last_used_at = now
        matched.usage_count = (matched.usage_count or 0) + 1
        await db.flush()
        return matched

    async def list(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        include_revoked: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AgentApiKey], int]:
        """Lista chaves do workspace ordenadas pela mais recente."""
        filters = [AgentApiKey.workspace_id == workspace_id]
        if not include_revoked:
            filters.append(AgentApiKey.revoked_at.is_(None))

        stmt_count = select(func.count(AgentApiKey.id)).where(and_(*filters))
        total = int((await db.execute(stmt_count)).scalar_one() or 0)

        stmt_rows = (
            select(AgentApiKey)
            .where(and_(*filters))
            .order_by(desc(AgentApiKey.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = list((await db.execute(stmt_rows)).scalars().all())
        return rows, total

    async def get(
        self,
        db: AsyncSession,
        *,
        key_id: UUID,
    ) -> AgentApiKey | None:
        stmt = select(AgentApiKey).where(AgentApiKey.id == key_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def revoke(
        self,
        db: AsyncSession,
        *,
        key: AgentApiKey,
    ) -> AgentApiKey:
        """Marca revoked_at=now. Idempotente se ja revogada."""
        if key.revoked_at is None:
            key.revoked_at = datetime.now(timezone.utc)
            await db.flush()
        return key

    async def delete(
        self,
        db: AsyncSession,
        *,
        key: AgentApiKey,
    ) -> None:
        """Hard delete. agent_audit_log mantem registro com api_key_id via metadata."""
        await db.delete(key)
        await db.flush()

    # --- helpers privados -------------------------------------------------

    def _validate_allowed_tools(self, tools: list[str]) -> None:
        """Confirma que cada tool existe no TOOL_REGISTRY ou e o wildcard '*'."""
        if "*" in tools:
            return
        unknown = [t for t in tools if t not in TOOL_REGISTRY]
        if unknown:
            raise AgentApiKeyValidationError(
                f"Tools desconhecidas: {', '.join(unknown)}"
            )

    async def _ensure_creator_role_covers_max(
        self,
        db: AsyncSession,
        *,
        creator: User,
        workspace_id: UUID,
        project_id: UUID | None,
        max_workspace_role: str,
        max_project_role: str | None,
    ) -> None:
        """Verifica que o criador tem role >= max_* no escopo correspondente."""
        ws_ok = await authorization_service.has_permission(
            db=db,
            user_id=creator.id,
            scope="workspace",
            required_role=max_workspace_role,
            scope_id=workspace_id,
        )
        if not ws_ok:
            raise AgentApiKeyPermissionError(
                "Criador nao pode conceder role maior que a propria no workspace."
            )

        if max_project_role is not None:
            if project_id is None:
                raise AgentApiKeyValidationError(
                    "max_project_role so pode ser definido quando project_id e fornecido."
                )
            proj_ok = await authorization_service.has_permission(
                db=db,
                user_id=creator.id,
                scope="project",
                required_role=max_project_role,
                scope_id=project_id,
            )
            if not proj_ok:
                raise AgentApiKeyPermissionError(
                    "Criador nao pode conceder role maior que a propria no projeto."
                )


agent_api_key_service = AgentApiKeyService()
