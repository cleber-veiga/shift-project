"""
Servico de negocio para convites (invitations).
"""

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.models import (
    Invitation,
    InvitationScope,
    InvitationStatus,
    Organization,
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
from app.schemas import (
    AcceptInvitationResponse,
    InvitationDetailResponse,
    InvitationResponse,
)
from app.core.security import authorization_service
from app.services.email_service import SCOPE_LABELS, email_service


# Roles validas por escopo
_VALID_ROLES: dict[InvitationScope, list[str]] = {
    InvitationScope.ORGANIZATION: [r.value for r in OrganizationRole],
    InvitationScope.WORKSPACE: [r.value for r in WorkspaceRole],
    InvitationScope.PROJECT: [r.value for r in ProjectRole],
}

# Rank maps para validar hierarquia de role
_RANK_MAPS: dict[InvitationScope, dict[str, int]] = {
    InvitationScope.ORGANIZATION: {r.value: i for i, r in enumerate(
        [OrganizationRole.GUEST, OrganizationRole.MEMBER, OrganizationRole.MANAGER, OrganizationRole.OWNER]
    )},
    InvitationScope.WORKSPACE: {r.value: i for i, r in enumerate(
        [WorkspaceRole.VIEWER, WorkspaceRole.CONSULTANT, WorkspaceRole.MANAGER]
    )},
    InvitationScope.PROJECT: {r.value: i for i, r in enumerate(
        [ProjectRole.CLIENT, ProjectRole.EDITOR]
    )},
}


class InvitationService:
    """CRUD e logica de convites."""

    async def create_invitation(
        self,
        db: AsyncSession,
        email: str,
        scope: InvitationScope,
        scope_id: UUID,
        role: str,
        invited_by: User,
    ) -> InvitationResponse:
        role_upper = role.upper()

        # Validar role
        if role_upper not in _VALID_ROLES[scope]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role '{role}' invalida para escopo {scope.value}. "
                       f"Validas: {', '.join(_VALID_ROLES[scope])}",
            )

        # Validar que nao esta convidando com role >= propria
        inviter_role_rank = await self._get_user_role_rank(db, invited_by.id, scope, scope_id)
        invited_rank = _RANK_MAPS[scope][role_upper]
        if invited_rank >= inviter_role_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Voce nao pode convidar com um papel igual ou superior ao seu.",
            )

        # Checar se usuario ja e membro
        existing_user = await self._get_user_by_email(db, email)
        if existing_user:
            is_member = await self._check_already_member(db, existing_user.id, scope, scope_id)
            if is_member:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Este usuario ja e membro deste escopo.",
                )

        # Checar duplicata PENDING
        existing = await self._find_pending_invitation(db, email, scope, scope_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ja existe um convite pendente para este email neste escopo.",
            )

        # Rate limit: max 10 PENDING por escopo
        pending_count = await self._count_pending_for_scope(db, scope, scope_id)
        if pending_count >= 10:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Limite de 10 convites pendentes por escopo atingido.",
            )

        # Rate limit: max 50/dia por usuario
        daily_count = await self._count_daily_invitations(db, invited_by.id)
        if daily_count >= 50:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Limite de 50 convites por dia atingido.",
            )

        # Criar convite
        token = secrets.token_hex(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.INVITATION_EXPIRE_DAYS)

        org_id, ws_id, proj_id = None, None, None
        if scope == InvitationScope.ORGANIZATION:
            org_id = scope_id
        elif scope == InvitationScope.WORKSPACE:
            ws_id = scope_id
        else:
            proj_id = scope_id

        invitation = Invitation(
            email=email.lower(),
            token=token,
            scope=scope,
            organization_id=org_id,
            workspace_id=ws_id,
            project_id=proj_id,
            role=role_upper,
            invited_by_id=invited_by.id,
            expires_at=expires_at,
        )
        db.add(invitation)
        await db.flush()

        # Enviar email
        scope_name = await self._get_scope_name(db, scope, scope_id)
        accept_url = f"{settings.FRONTEND_BASE_URL}/invite/{token}"
        await email_service.send_invitation_email(
            to_email=email,
            inviter_name=invited_by.full_name or invited_by.email,
            scope_label=SCOPE_LABELS.get(scope.value, scope.value),
            scope_name=scope_name,
            role=role_upper,
            accept_url=accept_url,
        )

        return InvitationResponse(
            id=invitation.id,
            email=invitation.email,
            scope=invitation.scope.value,
            role=invitation.role,
            status=invitation.status.value,
            invited_by_name=invited_by.full_name,
            invited_by_email=invited_by.email,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )

    async def list_invitations(
        self,
        db: AsyncSession,
        scope: InvitationScope,
        scope_id: UUID,
    ) -> list[InvitationResponse]:
        col = self._scope_column(scope)
        stmt = (
            select(Invitation)
            .options(joinedload(Invitation.invited_by))
            .where(col == scope_id)
            .order_by(Invitation.created_at.desc())
        )
        result = await db.execute(stmt)
        invitations = result.scalars().unique().all()

        return [
            InvitationResponse(
                id=inv.id,
                email=inv.email,
                scope=inv.scope.value,
                role=inv.role,
                status=(
                    InvitationStatus.EXPIRED.value
                    if inv.status == InvitationStatus.PENDING
                    and inv.expires_at < datetime.now(timezone.utc)
                    else inv.status.value
                ),
                invited_by_name=inv.invited_by.full_name if inv.invited_by else None,
                invited_by_email=inv.invited_by.email if inv.invited_by else "",
                expires_at=inv.expires_at,
                created_at=inv.created_at,
            )
            for inv in invitations
        ]

    async def cancel_invitation(
        self,
        db: AsyncSession,
        invitation_id: UUID,
    ) -> bool:
        inv = await self._get_invitation(db, invitation_id)
        if inv.status != InvitationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Apenas convites pendentes podem ser cancelados.",
            )
        inv.status = InvitationStatus.CANCELLED
        await db.flush()
        return True

    async def resend_invitation(
        self,
        db: AsyncSession,
        invitation_id: UUID,
        resender: User,
    ) -> InvitationResponse:
        inv = await self._get_invitation(db, invitation_id)
        if inv.status != InvitationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Apenas convites pendentes podem ser reenviados.",
            )

        # Gerar novo token e resetar expiracao
        inv.token = secrets.token_hex(32)
        inv.expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.INVITATION_EXPIRE_DAYS
        )
        await db.flush()

        scope_id = inv.organization_id or inv.workspace_id or inv.project_id
        scope_name = await self._get_scope_name(db, inv.scope, scope_id)
        accept_url = f"{settings.FRONTEND_BASE_URL}/invite/{inv.token}"

        await email_service.send_invitation_email(
            to_email=inv.email,
            inviter_name=resender.full_name or resender.email,
            scope_label=SCOPE_LABELS.get(inv.scope.value, inv.scope.value),
            scope_name=scope_name,
            role=inv.role,
            accept_url=accept_url,
        )

        inviter = await db.get(User, inv.invited_by_id)
        return InvitationResponse(
            id=inv.id,
            email=inv.email,
            scope=inv.scope.value,
            role=inv.role,
            status=inv.status.value,
            invited_by_name=inviter.full_name if inviter else None,
            invited_by_email=inviter.email if inviter else "",
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )

    async def get_invitation_by_token(
        self,
        db: AsyncSession,
        token: str,
    ) -> InvitationDetailResponse | None:
        stmt = (
            select(Invitation)
            .options(joinedload(Invitation.invited_by))
            .where(Invitation.token == token)
        )
        result = await db.execute(stmt)
        inv = result.scalars().first()
        if not inv:
            return None

        scope_id = inv.organization_id or inv.workspace_id or inv.project_id
        scope_name = await self._get_scope_name(db, inv.scope, scope_id)
        is_expired = (
            inv.status == InvitationStatus.PENDING
            and inv.expires_at < datetime.now(timezone.utc)
        )

        return InvitationDetailResponse(
            id=inv.id,
            email=inv.email,
            scope=inv.scope.value,
            scope_name=scope_name,
            role=inv.role,
            invited_by_name=inv.invited_by.full_name if inv.invited_by else None,
            is_expired=is_expired,
            is_accepted=inv.status == InvitationStatus.ACCEPTED,
        )

    async def accept_invitation(
        self,
        db: AsyncSession,
        token: str,
        user: User,
    ) -> AcceptInvitationResponse:
        stmt = select(Invitation).where(Invitation.token == token)
        result = await db.execute(stmt)
        inv = result.scalars().first()

        if not inv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Convite nao encontrado.")

        if inv.status == InvitationStatus.ACCEPTED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este convite ja foi aceito.")

        if inv.status == InvitationStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Este convite foi cancelado.")

        if inv.expires_at < datetime.now(timezone.utc):
            inv.status = InvitationStatus.EXPIRED
            await db.flush()
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Este convite expirou.")

        if inv.status != InvitationStatus.PENDING:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Convite em estado invalido.")

        # Validar email
        if user.email.lower() != inv.email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Este convite foi enviado para {inv.email}. Faca login com esse email para aceitar.",
            )

        # Criar membership
        scope_id = await self._create_membership(db, inv, user)

        # Marcar como aceito
        inv.status = InvitationStatus.ACCEPTED
        inv.accepted_by_id = user.id
        inv.accepted_at = datetime.now(timezone.utc)
        await db.flush()

        return AcceptInvitationResponse(
            success=True,
            message="Convite aceito com sucesso!",
            scope=inv.scope.value,
            scope_id=scope_id,
        )

    # ── helpers privados ──────────────────────────────────────────

    async def _get_invitation(self, db: AsyncSession, invitation_id: UUID) -> Invitation:
        inv = await db.get(Invitation, invitation_id)
        if not inv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Convite nao encontrado.")
        return inv

    def _scope_column(self, scope: InvitationScope):
        if scope == InvitationScope.ORGANIZATION:
            return Invitation.organization_id
        if scope == InvitationScope.WORKSPACE:
            return Invitation.workspace_id
        return Invitation.project_id

    async def _find_pending_invitation(
        self, db: AsyncSession, email: str, scope: InvitationScope, scope_id: UUID
    ) -> Invitation | None:
        col = self._scope_column(scope)
        stmt = select(Invitation).where(
            Invitation.email == email.lower(),
            Invitation.status == InvitationStatus.PENDING,
            col == scope_id,
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def _count_pending_for_scope(
        self, db: AsyncSession, scope: InvitationScope, scope_id: UUID
    ) -> int:
        col = self._scope_column(scope)
        stmt = select(func.count()).select_from(Invitation).where(
            Invitation.status == InvitationStatus.PENDING,
            col == scope_id,
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def _count_daily_invitations(self, db: AsyncSession, user_id: UUID) -> int:
        since = datetime.now(timezone.utc) - timedelta(days=1)
        stmt = select(func.count()).select_from(Invitation).where(
            Invitation.invited_by_id == user_id,
            Invitation.created_at >= since,
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def _get_user_by_email(self, db: AsyncSession, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        result = await db.execute(stmt)
        return result.scalars().first()

    async def _check_already_member(
        self, db: AsyncSession, user_id: UUID, scope: InvitationScope, scope_id: UUID
    ) -> bool:
        if scope == InvitationScope.ORGANIZATION:
            stmt = select(OrganizationMember).where(
                OrganizationMember.organization_id == scope_id,
                OrganizationMember.user_id == user_id,
            )
        elif scope == InvitationScope.WORKSPACE:
            stmt = select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == scope_id,
                WorkspaceMember.user_id == user_id,
            )
        else:
            stmt = select(ProjectMember).where(
                ProjectMember.project_id == scope_id,
                ProjectMember.user_id == user_id,
            )
        result = await db.execute(stmt)
        return result.scalars().first() is not None

    async def _get_user_role_rank(
        self, db: AsyncSession, user_id: UUID, scope: InvitationScope, scope_id: UUID
    ) -> int:
        """Retorna o rank efetivo do usuario no escopo, considerando heranca de roles."""
        scope_str = scope.value.lower()  # "organization", "workspace", "project"
        rank_map = _RANK_MAPS[scope]

        # Testar do maior rank para o menor; o primeiro que passar e o efetivo
        for role_str, rank in sorted(rank_map.items(), key=lambda x: x[1], reverse=True):
            if await authorization_service.has_permission(db, user_id, scope_str, role_str, scope_id):
                return rank
        return 0

    async def _get_scope_name(
        self, db: AsyncSession, scope: InvitationScope, scope_id: UUID
    ) -> str:
        if scope == InvitationScope.ORGANIZATION:
            org = await db.get(Organization, scope_id)
            return org.name if org else "Organizacao"
        if scope == InvitationScope.WORKSPACE:
            ws = await db.get(Workspace, scope_id)
            return ws.name if ws else "Workspace"
        proj = await db.get(Project, scope_id)
        return proj.name if proj else "Projeto"

    async def _create_membership(
        self, db: AsyncSession, inv: Invitation, user: User
    ) -> UUID:
        if inv.scope == InvitationScope.ORGANIZATION:
            role = OrganizationRole(inv.role)
            membership = OrganizationMember(
                organization_id=inv.organization_id,
                user_id=user.id,
                role=role,
            )
            db.add(membership)
            await db.flush()
            return inv.organization_id

        if inv.scope == InvitationScope.WORKSPACE:
            role = WorkspaceRole(inv.role)
            membership = WorkspaceMember(
                workspace_id=inv.workspace_id,
                user_id=user.id,
                role=role,
            )
            db.add(membership)
            await db.flush()
            return inv.workspace_id

        role = ProjectRole(inv.role)
        membership = ProjectMember(
            project_id=inv.project_id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
        await db.flush()
        return inv.project_id


invitation_service = InvitationService()
