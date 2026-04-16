"""
Endpoints de autenticacao: registro, login, refresh, logout, /me, Google OAuth2 e reset de senha.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.rate_limit import limiter
from app.models import User
from app.schemas.user import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleAuthRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    TokenResponse,
    UserCreate,
    UserMeResponse,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.services.auth_service import GoogleAuthError, auth_service

router = APIRouter(prefix="/auth", tags=["autenticacao"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Registra um novo usuario, provisiona hierarquia e retorna tokens."""
    try:
        return await auth_service.register(db, user_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao registrar usuario: {exc}",
        ) from exc


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Autentica o usuario com email/senha e retorna tokens."""
    tokens = await auth_service.authenticate(db, payload.email, payload.password)
    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tokens


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Usa o refresh token para emitir novos tokens."""
    tokens = await auth_service.refresh(db, payload.refresh_token)
    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tokens


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(payload: LogoutRequest) -> dict[str, str]:
    """Invalida o refresh token."""
    auth_service.logout(payload.refresh_token)
    return {"detail": "Sessao encerrada com sucesso."}


@router.get("/me", response_model=UserMeResponse)
async def me(
    current_user: User = Depends(get_current_user),
) -> UserMeResponse:
    """Retorna os dados do usuario autenticado."""
    return UserMeResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_verified=current_user.is_active,
        auth_provider=current_user.auth_provider,
        created_at=current_user.created_at.isoformat(),
        updated_at=current_user.created_at.isoformat(),
        last_login_at=None,
    )


@router.post("/google", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login_google(
    request: Request,
    payload: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Autentica via Google Identity Services e retorna tokens internos do Shift."""
    try:
        return await auth_service.authenticate_google(db, payload.credential)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ─── Reset de senha ───────────────────────────────────────────────────────────

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """
    Gera e armazena um código de reset de 6 dígitos.

    Em produção, o código deve ser enviado por email.
    Em desenvolvimento, o código é retornado diretamente na resposta.
    """
    code = await auth_service.request_password_reset(db, payload.email)

    if code is None:
        # Resposta genérica para não vazar se o email existe
        return ForgotPasswordResponse(
            message="Se o email estiver cadastrado, um codigo de verificacao sera enviado."
        )

    # TODO: integrar com servico de email para enviar o codigo
    # Por ora retornamos o codigo diretamente (apenas para desenvolvimento)
    return ForgotPasswordResponse(
        message=f"Codigo de verificacao gerado. [DEV] Codigo: {code}"
    )


@router.post("/verify-reset-code", response_model=VerifyCodeResponse)
@limiter.limit("10/minute")
async def verify_reset_code(
    request: Request,
    payload: VerifyCodeRequest,
) -> VerifyCodeResponse:
    """Verifica se o codigo de reset e valido."""
    valid = auth_service.verify_reset_code(payload.email, payload.code)
    return VerifyCodeResponse(valid=valid)


@router.post("/reset-password", response_model=ResetPasswordResponse)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ResetPasswordResponse:
    """Redefine a senha usando o codigo de verificacao."""
    success = await auth_service.reset_password(
        db, payload.email, payload.code, payload.new_password
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codigo invalido, expirado ou email nao encontrado.",
        )
    return ResetPasswordResponse(message="Senha redefinida com sucesso.")
