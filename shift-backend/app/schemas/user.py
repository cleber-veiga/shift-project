"""
Schemas Pydantic para autenticacao e usuarios.
"""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ─── Registro ─────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    """Payload de registro de novo usuario."""

    email: EmailStr
    password: str
    full_name: str | None = None


# ─── Login ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Payload de login via JSON."""

    email: str
    password: str


# ─── Token ────────────────────────────────────────────────────────────────────

class TokenUserInfo(BaseModel):
    """Dados do usuario embutidos no token de resposta."""

    id: str
    email: str
    full_name: str | None = None
    is_active: bool
    is_verified: bool
    auth_provider: str
    created_at: str
    updated_at: str
    last_login_at: str | None = None


class TokenResponse(BaseModel):
    """Resposta completa de autenticacao com tokens e dados do usuario."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_at: int
    refresh_token_expires_at: int
    user: TokenUserInfo


class RefreshRequest(BaseModel):
    """Payload para renovar o access token."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Payload de logout (invalida o refresh token)."""

    refresh_token: str


# ─── /auth/me ─────────────────────────────────────────────────────────────────

class UserMeResponse(BaseModel):
    """Dados do usuario autenticado."""

    id: str
    email: str
    full_name: str | None = None
    is_active: bool
    is_verified: bool
    auth_provider: str
    created_at: str
    updated_at: str
    last_login_at: str | None = None


# ─── Reset de senha ───────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str


class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str


class VerifyCodeResponse(BaseModel):
    valid: bool


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


class ResetPasswordResponse(BaseModel):
    message: str


# ─── Google OAuth2 ────────────────────────────────────────────────────────────

class GoogleAuthRequest(BaseModel):
    """Payload para autenticacao via Google Identity Services."""

    credential: str


# ─── Legado (mantido para compatibilidade interna) ────────────────────────────

class UserResponse(BaseModel):
    """Resposta do registro inicial do usuario (legado)."""

    id: UUID
    email: str
    is_active: bool
    auth_provider: str
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID
