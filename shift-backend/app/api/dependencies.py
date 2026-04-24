"""
Injeção de dependências do FastAPI: sessão de banco e autenticação.
"""

from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import user_cache
from app.core.rate_limit import _wf_project_cache
from app.db.session import get_db
from app.models import User
from app.services.auth_service import auth_service

# Esquema OAuth2 — aponta para o endpoint de login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Reexporta `get_db` (alias de `get_async_session` definido em app.db.session).
# Mantido aqui para compatibilidade com `from app.api.dependencies import get_db`
# usado em rotas e overrides de teste — todos resolvem ao MESMO objeto callable,
# o que garante uma única sessão por request em toda a cadeia de Depends.
__all__ = ["get_db", "get_current_user", "oauth2_scheme", "populate_rate_limit_context"]


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

    cached = user_cache.get(user_id)
    if cached is not None:
        return cached  # type: ignore[return-value]

    user = await auth_service.get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    user_cache.set(user_id, user)
    return user


async def populate_rate_limit_context(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Popula ``request.state`` com user_id e project_id para rate limiting.

    Usado pelos endpoints de execucao (POST /execute, POST /test) para
    alimentar ``_user_key_func`` e ``_project_key_func`` do rate limiter
    sem que estes precisem fazer DB lookups (nao sao async).

    O mapeamento workflow_id -> project_id e cacheado em memoria por ser
    imutavel apos a criacao do workflow.
    """
    request.state.rate_limit_user_id = str(current_user.id)

    # Extrai workflow_id do path (ex: /workflows/{workflow_id}/execute)
    workflow_id_str = request.path_params.get("workflow_id")
    if workflow_id_str and workflow_id_str not in _wf_project_cache:
        try:
            from sqlalchemy import select as sa_select
            from app.models.workflow import Workflow
            row = (
                await db.execute(
                    sa_select(Workflow.project_id).where(
                        Workflow.id == UUID(workflow_id_str)
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                _wf_project_cache[workflow_id_str] = str(row)
        except Exception:  # noqa: BLE001
            pass

    project_id = _wf_project_cache.get(workflow_id_str or "", workflow_id_str or "")
    request.state.rate_limit_project_id = project_id
