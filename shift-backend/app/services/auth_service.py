"""
Servico de autenticacao: registro, login local, login Google, refresh, logout e reset de senha.
"""

import asyncio
import random
import string
import time
from dataclasses import dataclass
from math import floor
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
    Project,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.schemas.user import TokenResponse, TokenUserInfo, UserCreate

# ─── Armazenamento em memória (desenvolvimento) ────────────────────────────────
# Em produção, substitua por Redis ou tabela de banco.

# refresh tokens invalidados via logout
_revoked_refresh_tokens: set[str] = set()

# códigos de reset de senha: email → (código, expira_em_unix_timestamp)
_reset_codes: dict[str, tuple[str, float]] = {}

_RESET_CODE_TTL_SECONDS = 15 * 60  # 15 minutos


# ─── Helper ───────────────────────────────────────────────────────────────────

def _build_token_response(user: User) -> TokenResponse:
    now = floor(time.time())
    access_expires_at = now + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    refresh_expires_at = now + settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        access_token_expires_at=access_expires_at,
        refresh_token_expires_at=refresh_expires_at,
        user=TokenUserInfo(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_verified=user.is_active,
            auth_provider=user.auth_provider,
            created_at=user.created_at.isoformat(),
            updated_at=user.created_at.isoformat(),
            last_login_at=None,
        ),
    )


# ─── Dataclass de resultado do registro ───────────────────────────────────────

@dataclass(slots=True)
class ProvisionedContext:
    user: User
    organization: Organization
    workspace: Workspace
    project: Project


class GoogleAuthError(Exception):
    """Erro de autenticacao Google."""


# ─── Serviço principal ─────────────────────────────────────────────────────────

class AuthService:
    """Logica de negocio para autenticacao e gestao de usuarios."""

    # ── Registro ──────────────────────────────────────────────────────────────

    async def register(self, db: AsyncSession, user_data: UserCreate) -> TokenResponse:
        """Registra um novo usuario local e retorna tokens. Sem provisionamento automatico."""
        user = User(
            email=user_data.email,
            full_name=user_data.full_name,
            hashed_password=hash_password(user_data.password),
            auth_provider="local",
        )
        db.add(user)
        await db.flush()
        return _build_token_response(user)

    # ── Login local ───────────────────────────────────────────────────────────

    async def authenticate(
        self, db: AsyncSession, email: str, password: str
    ) -> TokenResponse | None:
        """Autentica via email/senha e retorna tokens completos."""
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None or user.hashed_password is None:
            return None
        if not verify_password(password, user.hashed_password):
            return None

        return _build_token_response(user)

    # ── Refresh ───────────────────────────────────────────────────────────────

    async def refresh(
        self, db: AsyncSession, refresh_token: str
    ) -> TokenResponse | None:
        """Valida o refresh token e emite novos tokens."""
        if refresh_token in _revoked_refresh_tokens:
            return None

        try:
            payload = decode_access_token(refresh_token)
            if payload.get("type") != "refresh":
                return None
            user_id = UUID(payload["sub"])
        except Exception:
            return None

        user = await self.get_user_by_id(db, user_id)
        if user is None or not user.is_active:
            return None

        # invalida o refresh token usado (rotação de tokens)
        _revoked_refresh_tokens.add(refresh_token)
        return _build_token_response(user)

    # ── Logout ────────────────────────────────────────────────────────────────

    def logout(self, refresh_token: str) -> None:
        """Invalida o refresh token e remove o user do cache in-memory."""
        _revoked_refresh_tokens.add(refresh_token)
        try:
            payload = decode_access_token(refresh_token)
            user_id = UUID(payload["sub"])
        except Exception:
            return
        from app.core.cache import user_cache
        user_cache.invalidate(user_id)

    # ── /me ───────────────────────────────────────────────────────────────────

    async def get_me(self, db: AsyncSession, user_id: UUID) -> User | None:
        return await self.get_user_by_id(db, user_id)

    # ── Reset de senha ────────────────────────────────────────────────────────

    async def request_password_reset(
        self, db: AsyncSession, email: str
    ) -> str | None:
        """Gera e armazena um código de 6 dígitos. Retorna o código (para envio por email)."""
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            return None

        code = "".join(random.choices(string.digits, k=6))
        _reset_codes[email] = (code, time.time() + _RESET_CODE_TTL_SECONDS)
        return code

    def verify_reset_code(self, email: str, code: str) -> bool:
        """Verifica se o código é válido e não expirou."""
        entry = _reset_codes.get(email)
        if entry is None:
            return False
        stored_code, expires_at = entry
        if time.time() > expires_at:
            del _reset_codes[email]
            return False
        return stored_code == code

    async def reset_password(
        self, db: AsyncSession, email: str, code: str, new_password: str
    ) -> bool:
        """Valida o código e atualiza a senha. Retorna True em caso de sucesso."""
        if not self.verify_reset_code(email, code):
            return False

        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            return False

        user.hashed_password = hash_password(new_password)
        await db.flush()

        # remove o código após uso
        _reset_codes.pop(email, None)
        return True

    # ── Google OAuth2 ─────────────────────────────────────────────────────────

    async def authenticate_google(
        self, db: AsyncSession, google_token: str
    ) -> TokenResponse:
        """Valida o id_token do Google e retorna tokens internos do Shift."""
        if not settings.GOOGLE_CLIENT_ID:
            raise GoogleAuthError(
                "GOOGLE_CLIENT_ID nao configurado no servidor. "
                "Defina a variavel de ambiente antes de usar o login com Google."
            )

        idinfo = await asyncio.to_thread(
            _verify_google_token, google_token, settings.GOOGLE_CLIENT_ID
        )

        google_id: str = idinfo["sub"]
        email: str = idinfo["email"]
        name: str = idinfo.get("name") or email.split("@")[0]

        user = await self._get_by_google_id(db, google_id)

        if user is None:
            user = await self._get_by_email(db, email)
            if user is not None:
                user.google_id = google_id
                await db.flush()
            else:
                context = await self._create_google_user(db, email, name, google_id)
                user = context.user

        if user is None:
            raise GoogleAuthError("Falha ao provisionar o usuario autenticado via Google.")

        return _build_token_response(user)

    # ── Helpers internos ──────────────────────────────────────────────────────

    async def _get_by_google_id(self, db: AsyncSession, google_id: str) -> User | None:
        result = await db.execute(select(User).where(User.google_id == google_id))
        return result.scalar_one_or_none()

    async def _get_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def _create_google_user(
        self, db: AsyncSession, email: str, name: str, google_id: str
    ) -> ProvisionedContext:
        user = User(
            email=email,
            full_name=name,
            hashed_password=None,
            auth_provider="google",
            google_id=google_id,
        )
        return await self._provision_default_hierarchy(
            db=db,
            user=user,
            organization_name=f"Organization de {name}",
        )

    async def _provision_default_hierarchy(
        self,
        db: AsyncSession,
        user: User,
        organization_name: str | None = None,
    ) -> ProvisionedContext:
        """Provisiona a hierarquia padrao para usuarios sem convite."""
        org_name = organization_name or _default_organization_name(user.email)

        organization = Organization(name=org_name, billing_email=user.email)
        workspace = Workspace(name="General", organization=organization)
        project = Project(
            name="Default Project",
            description="Projeto inicial criado automaticamente no cadastro.",
            workspace=workspace,
        )

        db.add_all([organization, workspace, project, user])
        await db.flush()

        db.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=user.id,
                role=OrganizationRole.OWNER,
            )
        )
        db.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.MANAGER,
            )
        )
        await db.flush()

        return ProvisionedContext(
            user=user,
            organization=organization,
            workspace=workspace,
            project=project,
        )

    async def get_user_by_id(self, db: AsyncSession, user_id: UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


def _default_organization_name(email: str) -> str:
    local_part = email.split("@", 1)[0].replace(".", " ").strip()
    fallback = local_part.title() if local_part else "New Organization"
    return f"{fallback} Organization"


def _verify_google_token(token: str, client_id: str) -> dict:
    """Valida o id_token do Google e retorna o payload decodificado."""
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            client_id,
        )
    except ValueError as exc:
        raise GoogleAuthError(f"Token Google invalido ou expirado: {exc}") from exc
    except Exception as exc:
        raise GoogleAuthError(
            f"Nao foi possivel verificar o token Google: {exc}"
        ) from exc

    if not idinfo.get("email_verified", False):
        raise GoogleAuthError(
            "O email da conta Google nao esta verificado. Acesso negado."
        )

    return idinfo


auth_service = AuthService()
