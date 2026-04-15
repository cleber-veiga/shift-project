"""
Injeção de dependências do FastAPI: sessão de banco e autenticação.
"""

from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.models import User
from app.services.auth_service import auth_service

# Esquema OAuth2 — aponta para o endpoint de login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncSession:
    """Provê uma sessão assíncrona do banco de dados."""
    async for session in get_async_session():
        yield session


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependência que extrai e valida o usuário autenticado a partir do token JWT.

    Raises:
        HTTPException 401: Se o token for inválido ou o usuário não existir.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        from app.core.security import decode_access_token
        payload = decode_access_token(token)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = UUID(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user = await auth_service.get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    return user
