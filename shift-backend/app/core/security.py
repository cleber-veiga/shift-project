"""
Utilitarios de seguranca: hashing, JWT e autorizacao multi-tenant.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_async_session
from app.models.connection import Connection
from app.models.input_model import InputModel
from app.models.input_model_row import InputModelRow
from app.models import (
    EconomicGroup,
    Establishment,
    OrganizationMember,
    OrganizationRole,
    Project,
    ProjectMember,
    ProjectRole,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.models.workflow import Workflow, WorkflowExecution

pwd_context = PasswordHash((Argon2Hasher(),))

_ORG_RANK: dict[OrganizationRole, int] = {
    OrganizationRole.GUEST: 0,
    OrganizationRole.MEMBER: 1,
    OrganizationRole.MANAGER: 2,
    OrganizationRole.OWNER: 3,
}
_WORKSPACE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.VIEWER: 0,
    WorkspaceRole.CONSULTANT: 1,
    WorkspaceRole.MANAGER: 2,
}
_PROJECT_RANK: dict[ProjectRole, int] = {
    ProjectRole.CLIENT: 0,
    ProjectRole.EDITOR: 1,
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


class AuthorizationService:
    """Resolve escopo e verifica papeis com heranca entre organization, workspace e project."""

    async def require(
        self,
        scope: str,
        required_role: str,
        request: Request,
        db: AsyncSession,
        current_user: User,
    ) -> None:
        scope_id = await self.resolve_scope_id(scope, request, db)
        if scope_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Nao foi possivel determinar o {scope}_id para autorizacao.",
            )

        if not await self.has_permission(
            db=db,
            user_id=current_user.id,
            scope=scope,
            required_role=required_role,
            scope_id=scope_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sem permissao para executar esta operacao.",
            )

        request.state.authorized_scope = {
            "scope": scope,
            "scope_id": scope_id,
        }

    async def resolve_scope_id(
        self,
        scope: str,
        request: Request,
        db: AsyncSession,
    ) -> UUID | None:
        if scope == "organization":
            return await self._resolve_organization_id(request, db)
        if scope == "workspace":
            return await self._resolve_workspace_id(request, db)
        if scope == "project":
            return await self._resolve_project_id(request, db)
        raise ValueError(f"Escopo desconhecido: {scope}")

    async def has_permission(
        self,
        db: AsyncSession,
        user_id: UUID,
        scope: str,
        required_role: str,
        scope_id: UUID,
    ) -> bool:
        if scope == "organization":
            role = await self._get_effective_org_role(db, user_id, scope_id)
            return self._role_meets_threshold(scope, role, required_role)

        if scope == "workspace":
            role = await self._get_effective_workspace_role(db, user_id, scope_id)
            return self._role_meets_threshold(scope, role, required_role)

        if scope == "project":
            role = await self._get_effective_project_role(db, user_id, scope_id)
            return self._role_meets_threshold(scope, role, required_role)

        raise ValueError(f"Escopo desconhecido: {scope}")

    async def _get_effective_org_role(
        self,
        db: AsyncSession,
        user_id: UUID,
        organization_id: UUID,
    ) -> OrganizationRole | None:
        result = await db.execute(
            select(OrganizationMember.role).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_effective_workspace_role(
        self,
        db: AsyncSession,
        user_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceRole | None:
        """Busca papel direto no workspace + papel na org em 1 query via JOIN."""
        result = await db.execute(
            select(
                WorkspaceMember.role,
                OrganizationMember.role,
            )
            .select_from(Workspace)
            .outerjoin(
                WorkspaceMember,
                (WorkspaceMember.workspace_id == Workspace.id)
                & (WorkspaceMember.user_id == user_id),
            )
            .outerjoin(
                OrganizationMember,
                (OrganizationMember.organization_id == Workspace.organization_id)
                & (OrganizationMember.user_id == user_id),
            )
            .where(Workspace.id == workspace_id)
        )
        row = result.one_or_none()
        if row is None:
            return None

        explicit_role, org_role = row[0], row[1]

        inherited_role: WorkspaceRole | None = None
        if org_role in {OrganizationRole.OWNER, OrganizationRole.MANAGER}:
            inherited_role = WorkspaceRole.MANAGER
        elif org_role == OrganizationRole.MEMBER:
            inherited_role = WorkspaceRole.VIEWER

        return self._max_workspace_role(explicit_role, inherited_role)

    async def _get_effective_project_role(
        self,
        db: AsyncSession,
        user_id: UUID,
        project_id: UUID,
    ) -> ProjectRole | None:
        """Busca papeis diretos no project, workspace e org em 1 query via JOINs."""
        result = await db.execute(
            select(
                ProjectMember.role,
                WorkspaceMember.role,
                OrganizationMember.role,
            )
            .select_from(Project)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .outerjoin(
                ProjectMember,
                (ProjectMember.project_id == Project.id)
                & (ProjectMember.user_id == user_id),
            )
            .outerjoin(
                WorkspaceMember,
                (WorkspaceMember.workspace_id == Workspace.id)
                & (WorkspaceMember.user_id == user_id),
            )
            .outerjoin(
                OrganizationMember,
                (OrganizationMember.organization_id == Workspace.organization_id)
                & (OrganizationMember.user_id == user_id),
            )
            .where(Project.id == project_id)
        )
        row = result.one_or_none()
        if row is None:
            return None

        explicit_role, ws_role, org_role = row[0], row[1], row[2]

        # Calcula workspace_role herdado da org
        inherited_ws: WorkspaceRole | None = None
        if org_role in {OrganizationRole.OWNER, OrganizationRole.MANAGER}:
            inherited_ws = WorkspaceRole.MANAGER
        elif org_role == OrganizationRole.MEMBER:
            inherited_ws = WorkspaceRole.VIEWER
        effective_ws = self._max_workspace_role(ws_role, inherited_ws)

        inherited_roles: list[ProjectRole] = [r for r in [explicit_role] if r]

        if effective_ws in {WorkspaceRole.MANAGER, WorkspaceRole.CONSULTANT}:
            inherited_roles.append(ProjectRole.EDITOR)
        elif effective_ws == WorkspaceRole.VIEWER:
            inherited_roles.append(ProjectRole.CLIENT)

        if org_role in {OrganizationRole.OWNER, OrganizationRole.MANAGER}:
            inherited_roles.append(ProjectRole.EDITOR)
        elif org_role == OrganizationRole.MEMBER:
            inherited_roles.append(ProjectRole.CLIENT)

        if not inherited_roles:
            return None
        return max(inherited_roles, key=lambda role: _PROJECT_RANK[role])

    async def _resolve_organization_id(
        self,
        request: Request,
        db: AsyncSession,
    ) -> UUID | None:
        direct = self._read_uuid_param(request, "organization_id", "org_id")
        if direct is not None:
            return direct

        economic_group_id = self._read_uuid_param(request, "economic_group_id", "group_id")
        if economic_group_id is not None:
            result = await db.execute(
                select(EconomicGroup.organization_id).where(EconomicGroup.id == economic_group_id)
            )
            return result.scalar_one_or_none()

        establishment_id = self._read_uuid_param(request, "establishment_id")
        if establishment_id is not None:
            result = await db.execute(
                select(EconomicGroup.organization_id)
                .join(Establishment, Establishment.economic_group_id == EconomicGroup.id)
                .where(Establishment.id == establishment_id)
            )
            return result.scalar_one_or_none()

        workspace_id = self._read_uuid_param(request, "workspace_id", "ws_id")
        if workspace_id is not None:
            result = await db.execute(
                select(Workspace.organization_id).where(Workspace.id == workspace_id)
            )
            return result.scalar_one_or_none()

        project_id = await self._resolve_project_id(request, db)
        if project_id is not None:
            result = await db.execute(
                select(Workspace.organization_id)
                .join(Project, Project.workspace_id == Workspace.id)
                .where(Project.id == project_id)
            )
            return result.scalar_one_or_none()

        return None

    async def _resolve_workspace_id(
        self,
        request: Request,
        db: AsyncSession,
    ) -> UUID | None:
        direct = self._read_uuid_param(request, "workspace_id", "ws_id")
        if direct is not None:
            return direct

        connection_id = self._read_uuid_param(request, "connection_id")
        if connection_id is not None:
            result = await db.execute(
                select(
                    func.coalesce(Connection.workspace_id, Project.workspace_id)
                )
                .select_from(Connection)
                .outerjoin(Project, Project.id == Connection.project_id)
                .where(Connection.id == connection_id)
            )
            return result.scalar_one_or_none()

        project_id = self._read_uuid_param(request, "project_id", "proj_id")
        if project_id is not None:
            result = await db.execute(
                select(Project.workspace_id).where(Project.id == project_id)
            )
            return result.scalar_one_or_none()

        workflow_id = self._read_uuid_param(request, "workflow_id")
        if workflow_id is not None:
            # Tenta resolver via project_id (workflow de projeto)
            result = await db.execute(
                select(Project.workspace_id)
                .join(Workflow, Workflow.project_id == Project.id)
                .where(Workflow.id == workflow_id)
            )
            ws_id = result.scalar_one_or_none()
            if ws_id is not None:
                return ws_id
            # Fallback: workflow pode ser workspace-scoped (workspace_id direto)
            result = await db.execute(
                select(Workflow.workspace_id).where(Workflow.id == workflow_id)
            )
            return result.scalar_one_or_none()

        execution_id = self._read_uuid_param(request, "execution_id")
        if execution_id is not None:
            # Tenta resolver via project-scoped workflow
            result = await db.execute(
                select(Project.workspace_id)
                .join(Workflow, Workflow.project_id == Project.id)
                .join(WorkflowExecution, WorkflowExecution.workflow_id == Workflow.id)
                .where(WorkflowExecution.id == execution_id)
            )
            ws_id = result.scalar_one_or_none()
            if ws_id is not None:
                return ws_id
            # Fallback: workspace-scoped workflow
            result = await db.execute(
                select(Workflow.workspace_id)
                .join(WorkflowExecution, WorkflowExecution.workflow_id == Workflow.id)
                .where(WorkflowExecution.id == execution_id)
            )
            return result.scalar_one_or_none()

        input_model_id = self._read_uuid_param(request, "input_model_id")
        if input_model_id is not None:
            result = await db.execute(
                select(InputModel.workspace_id).where(InputModel.id == input_model_id)
            )
            return result.scalar_one_or_none()

        row_id = self._read_uuid_param(request, "row_id")
        if row_id is not None:
            result = await db.execute(
                select(InputModel.workspace_id)
                .join(InputModelRow, InputModelRow.input_model_id == InputModel.id)
                .where(InputModelRow.id == row_id)
            )
            return result.scalar_one_or_none()

        return None

    async def _resolve_project_id(
        self,
        request: Request,
        db: AsyncSession,
    ) -> UUID | None:
        direct = self._read_uuid_param(request, "project_id", "proj_id")
        if direct is not None:
            return direct

        connection_id = self._read_uuid_param(request, "connection_id")
        if connection_id is not None:
            result = await db.execute(
                select(Connection.project_id).where(Connection.id == connection_id)
            )
            return result.scalar_one_or_none()

        workflow_id = self._read_uuid_param(request, "workflow_id")
        if workflow_id is not None:
            result = await db.execute(
                select(Workflow.project_id).where(Workflow.id == workflow_id)
            )
            return result.scalar_one_or_none()

        execution_id = self._read_uuid_param(request, "execution_id")
        if execution_id is not None:
            result = await db.execute(
                select(Workflow.project_id)
                .join(WorkflowExecution, WorkflowExecution.workflow_id == Workflow.id)
                .where(WorkflowExecution.id == execution_id)
            )
            return result.scalar_one_or_none()

        return None

    def _read_uuid_param(self, request: Request, *keys: str) -> UUID | None:
        for source in (request.path_params, request.query_params):
            for key in keys:
                raw = source.get(key)
                if raw is None:
                    continue
                try:
                    return UUID(str(raw))
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Parametro '{key}' invalido.",
                    ) from None
        return None

    def _role_meets_threshold(
        self,
        scope: str,
        actual_role: OrganizationRole | WorkspaceRole | ProjectRole | None,
        required_role: str,
    ) -> bool:
        if actual_role is None:
            return False

        if scope == "organization":
            required = OrganizationRole(required_role)
            return _ORG_RANK[actual_role] >= _ORG_RANK[required]
        if scope == "workspace":
            required = WorkspaceRole(required_role)
            return _WORKSPACE_RANK[actual_role] >= _WORKSPACE_RANK[required]
        if scope == "project":
            required = ProjectRole(required_role)
            return _PROJECT_RANK[actual_role] >= _PROJECT_RANK[required]
        raise ValueError(f"Escopo desconhecido: {scope}")

    def _max_workspace_role(
        self,
        left: WorkspaceRole | None,
        right: WorkspaceRole | None,
    ) -> WorkspaceRole | None:
        roles = [role for role in (left, right) if role is not None]
        if not roles:
            return None
        return max(roles, key=lambda role: _WORKSPACE_RANK[role])


authorization_service = AuthorizationService()


async def _get_db() -> AsyncSession:
    async for session in get_async_session():
        yield session


def require_permission(scope: str, role: str):
    """Dependencia FastAPI para validar permissao no banco a cada request."""

    async def dependency(
        request: Request,
        db: AsyncSession = Depends(_get_db),
        current_user: User = Depends(_resolve_current_user),
    ) -> User:
        await authorization_service.require(
            scope=scope,
            required_role=role,
            request=request,
            db=db,
            current_user=current_user,
        )
        return current_user

    return dependency


async def _resolve_current_user(
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> User:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
