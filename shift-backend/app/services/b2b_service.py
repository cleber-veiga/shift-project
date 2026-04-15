"""
Servico de negocio para Organization, Workspace, Project e memberships.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EconomicGroup,
    Establishment,
    Organization,
    OrganizationMember,
    OrganizationRole,
    Project,
    ProjectMember,
    ProjectRole,
    User,
    Workspace,
    WorkspaceMember,
    WorkspacePlayer,
    WorkspaceRole,
)
from app.schemas import (
    AddMemberRequest,
    EconomicGroupCreate,
    EconomicGroupUpdate,
    EstablishmentCreate,
    EstablishmentUpdate,
    MemberResponse,
    OrganizationCreate,
    OrganizationUpdate,
    ProjectCreate,
    ProjectUpdate,
    WorkspaceCreate,
    WorkspacePlayerCreate,
    WorkspacePlayerUpdate,
    WorkspaceUpdate,
)

class B2BService:
    """CRUD e visibilidade da hierarquia B2B."""

    async def list_organizations_for_user(
        self,
        db: AsyncSession,
        user_id: UUID,
    ) -> list[Organization]:
        stmt = (
            select(Organization)
            .where(self._organization_visibility_condition(user_id))
            .order_by(Organization.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_organizations_with_roles_for_user(
        self,
        db: AsyncSession,
        user_id: UUID,
    ) -> list[tuple[Organization, str | None]]:
        """Retorna organizações visíveis ao usuário junto com o papel direto dele em cada uma.
        Usa LEFT JOIN para buscar entidades e roles em 1 query."""
        stmt = (
            select(Organization, OrganizationMember.role)
            .outerjoin(
                OrganizationMember,
                (OrganizationMember.organization_id == Organization.id)
                & (OrganizationMember.user_id == user_id),
            )
            .where(self._organization_visibility_condition(user_id))
            .order_by(Organization.name)
        )
        result = await db.execute(stmt)
        return [
            (org, role.value if role is not None else None)
            for org, role in result.all()
        ]

    async def create_organization(
        self,
        db: AsyncSession,
        data: OrganizationCreate,
        creator: User,
    ) -> Organization:
        organization = Organization(
            name=data.name,
            billing_email=data.billing_email or creator.email,
        )
        db.add(organization)
        await db.flush()

        db.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=creator.id,
                role=OrganizationRole.OWNER,
            )
        )
        await db.flush()
        await db.refresh(organization)
        return organization

    async def get_organization_for_user(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
    ) -> Organization | None:
        stmt = select(Organization).where(
            Organization.id == org_id,
            self._organization_visibility_condition(user_id),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_organization(
        self,
        db: AsyncSession,
        org_id: UUID,
        data: OrganizationUpdate,
    ) -> Organization | None:
        organization = await db.get(Organization, org_id)
        if organization is None:
            return None

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(organization, field, value)

        await db.flush()
        await db.refresh(organization)
        return organization

    async def delete_organization(
        self,
        db: AsyncSession,
        org_id: UUID,
    ) -> bool:
        organization = await db.get(Organization, org_id)
        if organization is None:
            return False
        await db.delete(organization)
        await db.flush()
        return True

    async def list_organization_members(
        self,
        db: AsyncSession,
        org_id: UUID,
    ) -> list[MemberResponse]:
        result = await db.execute(
            select(
                User.id,
                User.email,
                User.is_active,
                OrganizationMember.role,
                OrganizationMember.created_at,
            )
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == org_id)
            .order_by(User.email)
        )
        return [
            MemberResponse(
                user_id=row.id,
                email=row.email,
                is_active=row.is_active,
                role=row.role.value if hasattr(row.role, "value") else str(row.role),
                created_at=row.created_at,
            )
            for row in result.all()
        ]

    async def add_organization_member(
        self,
        db: AsyncSession,
        org_id: UUID,
        payload: AddMemberRequest,
    ) -> MemberResponse:
        role = self._parse_role(OrganizationRole, payload.role)
        user = await self._get_user_by_email(db, payload.email)
        self._ensure_found(user, f"Usuario '{payload.email}' nao encontrado.")

        exists_result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )
        if exists_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Usuario ja e membro desta organization.",
            )

        membership = OrganizationMember(
            organization_id=org_id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
        await db.flush()
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            is_active=user.is_active,
            role=membership.role.value,
            created_at=membership.created_at,
        )

    async def update_organization_member_role(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        role_raw: str,
    ) -> MemberResponse | None:
        result = await db.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None

        membership, user = row[0], row[1]
        new_role = self._parse_role(OrganizationRole, role_raw)
        if membership.role == OrganizationRole.OWNER and new_role != OrganizationRole.OWNER:
            await self._ensure_not_last_owner(db, org_id, user_id)

        membership.role = new_role
        await db.flush()
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            is_active=user.is_active,
            role=membership.role.value,
            created_at=membership.created_at,
        )

    async def remove_organization_member(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
    ) -> bool:
        membership = await self._get_organization_member(db, org_id, user_id)
        if membership is None:
            return False

        if membership.role == OrganizationRole.OWNER:
            await self._ensure_not_last_owner(db, org_id, user_id)

        await db.delete(membership)
        await db.flush()
        return True

    async def list_workspaces_for_user(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
    ) -> list[Workspace]:
        stmt = (
            select(Workspace)
            .where(
                Workspace.organization_id == org_id,
                self._workspace_visibility_condition(user_id),
            )
            .order_by(Workspace.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_workspaces_with_roles_for_user(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
    ) -> list[tuple[Workspace, str | None]]:
        """Retorna workspaces visíveis junto com o papel efetivo do usuário em cada um.
        Busca workspace role direto + org role (fallback) em 1 query via LEFT JOINs."""
        stmt = (
            select(
                Workspace,
                WorkspaceMember.role,
                OrganizationMember.role,
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
            .where(
                Workspace.organization_id == org_id,
                self._workspace_visibility_condition(user_id),
            )
            .order_by(Workspace.name)
        )
        result = await db.execute(stmt)

        items: list[tuple[Workspace, str | None]] = []
        for ws, ws_role, org_role in result.all():
            if ws_role is not None:
                effective = ws_role.value
            elif org_role is not None:
                effective = org_role.value
            else:
                effective = None
            items.append((ws, effective))
        return items

    async def create_workspace(
        self,
        db: AsyncSession,
        org_id: UUID,
        data: WorkspaceCreate,
        creator_id: UUID | None = None,
    ) -> Workspace:
        workspace = Workspace(
            organization_id=org_id,
            name=data.name,
        )
        db.add(workspace)
        await db.flush()

        if creator_id is not None:
            db.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=creator_id,
                    role=WorkspaceRole.MANAGER,
                )
            )
            await db.flush()

        await db.refresh(workspace)
        return workspace

    async def get_workspace_for_user(
        self,
        db: AsyncSession,
        ws_id: UUID,
        user_id: UUID,
    ) -> Workspace | None:
        stmt = select(Workspace).where(
            Workspace.id == ws_id,
            self._workspace_visibility_condition(user_id),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_workspace(
        self,
        db: AsyncSession,
        ws_id: UUID,
        data: WorkspaceUpdate,
    ) -> Workspace | None:
        workspace = await db.get(Workspace, ws_id)
        if workspace is None:
            return None

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(workspace, field, value)

        await db.flush()
        await db.refresh(workspace)
        return workspace

    async def delete_workspace(
        self,
        db: AsyncSession,
        ws_id: UUID,
    ) -> bool:
        workspace = await db.get(Workspace, ws_id)
        if workspace is None:
            return False
        await db.delete(workspace)
        await db.flush()
        return True

    async def list_workspace_members(
        self,
        db: AsyncSession,
        ws_id: UUID,
    ) -> list[MemberResponse]:
        result = await db.execute(
            select(
                User.id,
                User.email,
                User.is_active,
                WorkspaceMember.role,
                WorkspaceMember.created_at,
            )
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == ws_id)
            .order_by(User.email)
        )
        return [
            MemberResponse(
                user_id=row.id,
                email=row.email,
                is_active=row.is_active,
                role=row.role.value if hasattr(row.role, "value") else str(row.role),
                created_at=row.created_at,
            )
            for row in result.all()
        ]

    async def add_workspace_member(
        self,
        db: AsyncSession,
        ws_id: UUID,
        payload: AddMemberRequest,
    ) -> MemberResponse:
        role = self._parse_role(WorkspaceRole, payload.role)
        user = await self._get_user_by_email(db, payload.email)
        self._ensure_found(user, f"Usuario '{payload.email}' nao encontrado.")

        exists_result = await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if exists_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Usuario ja e membro deste workspace.",
            )

        membership = WorkspaceMember(
            workspace_id=ws_id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
        await db.flush()
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            is_active=user.is_active,
            role=membership.role.value,
            created_at=membership.created_at,
        )

    async def update_workspace_member_role(
        self,
        db: AsyncSession,
        ws_id: UUID,
        user_id: UUID,
        role_raw: str,
    ) -> MemberResponse | None:
        result = await db.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(
                WorkspaceMember.workspace_id == ws_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None

        membership, user = row[0], row[1]
        membership.role = self._parse_role(WorkspaceRole, role_raw)
        await db.flush()
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            is_active=user.is_active,
            role=membership.role.value,
            created_at=membership.created_at,
        )

    async def remove_workspace_member(
        self,
        db: AsyncSession,
        ws_id: UUID,
        user_id: UUID,
    ) -> bool:
        membership = await self._get_workspace_member(db, ws_id, user_id)
        if membership is None:
            return False
        await db.delete(membership)
        await db.flush()
        return True

    async def list_workspace_players(
        self,
        db: AsyncSession,
        ws_id: UUID,
    ) -> list[WorkspacePlayer]:
        result = await db.execute(
            select(WorkspacePlayer)
            .where(WorkspacePlayer.workspace_id == ws_id)
            .order_by(WorkspacePlayer.name)
        )
        return list(result.scalars().all())

    async def create_workspace_player(
        self,
        db: AsyncSession,
        ws_id: UUID,
        data: WorkspacePlayerCreate,
    ) -> WorkspacePlayer:
        existing = await db.execute(
            select(WorkspacePlayer).where(
                WorkspacePlayer.workspace_id == ws_id,
                WorkspacePlayer.name == data.name,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ja existe um concorrente com este nome neste workspace.",
            )

        player = WorkspacePlayer(
            workspace_id=ws_id,
            name=data.name,
            database_type=data.database_type,
        )
        db.add(player)
        await db.flush()
        await db.refresh(player)
        return player

    async def update_workspace_player(
        self,
        db: AsyncSession,
        ws_id: UUID,
        player_id: UUID,
        data: WorkspacePlayerUpdate,
    ) -> WorkspacePlayer | None:
        player = await db.get(WorkspacePlayer, player_id)
        if player is None or player.workspace_id != ws_id:
            return None

        next_name = data.name if data.name is not None else player.name
        if next_name != player.name:
            existing = await db.execute(
                select(WorkspacePlayer).where(
                    WorkspacePlayer.workspace_id == ws_id,
                    WorkspacePlayer.name == next_name,
                    WorkspacePlayer.id != player_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ja existe um concorrente com este nome neste workspace.",
                )

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(player, field, value)

        await db.flush()
        await db.refresh(player)
        return player

    async def delete_workspace_player(
        self,
        db: AsyncSession,
        ws_id: UUID,
        player_id: UUID,
    ) -> bool:
        player = await db.get(WorkspacePlayer, player_id)
        if player is None or player.workspace_id != ws_id:
            return False

        await db.delete(player)
        await db.flush()
        return True

    async def list_economic_groups_for_user(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
    ) -> list[EconomicGroup]:
        stmt = (
            select(EconomicGroup)
            .join(Organization, Organization.id == EconomicGroup.organization_id)
            .where(
                EconomicGroup.organization_id == org_id,
                self._organization_visibility_condition(user_id),
            )
            .order_by(EconomicGroup.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_economic_group(
        self,
        db: AsyncSession,
        org_id: UUID,
        data: EconomicGroupCreate,
    ) -> EconomicGroup:
        existing = await db.execute(
            select(EconomicGroup).where(
                EconomicGroup.organization_id == org_id,
                EconomicGroup.name == data.name,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ja existe um grupo economico com este nome nesta organizacao.",
            )

        economic_group = EconomicGroup(
            organization_id=org_id,
            name=data.name,
            description=data.description,
            is_active=data.is_active,
        )
        db.add(economic_group)
        await db.flush()
        await db.refresh(economic_group)
        return economic_group

    async def get_economic_group_for_user(
        self,
        db: AsyncSession,
        group_id: UUID,
        user_id: UUID,
    ) -> EconomicGroup | None:
        stmt = (
            select(EconomicGroup)
            .join(Organization, Organization.id == EconomicGroup.organization_id)
            .where(
                EconomicGroup.id == group_id,
                self._organization_visibility_condition(user_id),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_economic_group(
        self,
        db: AsyncSession,
        group_id: UUID,
        data: EconomicGroupUpdate,
    ) -> EconomicGroup | None:
        economic_group = await db.get(EconomicGroup, group_id)
        if economic_group is None:
            return None

        next_name = data.name if data.name is not None else economic_group.name
        if next_name != economic_group.name:
            existing = await db.execute(
                select(EconomicGroup).where(
                    EconomicGroup.organization_id == economic_group.organization_id,
                    EconomicGroup.name == next_name,
                    EconomicGroup.id != group_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ja existe um grupo economico com este nome nesta organizacao.",
                )

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(economic_group, field, value)

        await db.flush()
        await db.refresh(economic_group)
        return economic_group

    async def delete_economic_group(
        self,
        db: AsyncSession,
        group_id: UUID,
    ) -> bool:
        economic_group = await db.get(EconomicGroup, group_id)
        if economic_group is None:
            return False

        await db.delete(economic_group)
        await db.flush()
        return True

    async def list_establishments_for_user(
        self,
        db: AsyncSession,
        group_id: UUID,
        user_id: UUID,
    ) -> list[Establishment]:
        stmt = (
            select(Establishment)
            .join(EconomicGroup, EconomicGroup.id == Establishment.economic_group_id)
            .join(Organization, Organization.id == EconomicGroup.organization_id)
            .where(
                Establishment.economic_group_id == group_id,
                self._organization_visibility_condition(user_id),
            )
            .order_by(Establishment.corporate_name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_establishment(
        self,
        db: AsyncSession,
        group_id: UUID,
        data: EstablishmentCreate,
    ) -> Establishment:
        economic_group = await db.get(EconomicGroup, group_id)
        self._ensure_found(economic_group, "Grupo economico nao encontrado.")

        existing = await db.execute(
            select(Establishment).where(Establishment.cnpj == data.cnpj)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ja existe um estabelecimento com este CNPJ.",
            )

        establishment = Establishment(
            economic_group_id=group_id,
            corporate_name=data.corporate_name,
            trade_name=data.trade_name,
            cnpj=data.cnpj,
            erp_code=data.erp_code,
            cnae=data.cnae,
            state_registration=data.state_registration,
            cep=data.cep,
            city=data.city,
            state=data.state,
            notes=data.notes,
            is_active=data.is_active,
        )
        db.add(establishment)
        await db.flush()
        await db.refresh(establishment)
        return establishment

    async def get_establishment_for_user(
        self,
        db: AsyncSession,
        establishment_id: UUID,
        user_id: UUID,
    ) -> Establishment | None:
        stmt = (
            select(Establishment)
            .join(EconomicGroup, EconomicGroup.id == Establishment.economic_group_id)
            .join(Organization, Organization.id == EconomicGroup.organization_id)
            .where(
                Establishment.id == establishment_id,
                self._organization_visibility_condition(user_id),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_establishment(
        self,
        db: AsyncSession,
        establishment_id: UUID,
        data: EstablishmentUpdate,
    ) -> Establishment | None:
        establishment = await db.get(Establishment, establishment_id)
        if establishment is None:
            return None

        next_cnpj = data.cnpj if data.cnpj is not None else establishment.cnpj
        if next_cnpj != establishment.cnpj:
            existing = await db.execute(
                select(Establishment).where(
                    Establishment.cnpj == next_cnpj,
                    Establishment.id != establishment_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ja existe um estabelecimento com este CNPJ.",
                )

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(establishment, field, value)

        await db.flush()
        await db.refresh(establishment)
        return establishment

    async def delete_establishment(
        self,
        db: AsyncSession,
        establishment_id: UUID,
    ) -> bool:
        establishment = await db.get(Establishment, establishment_id)
        if establishment is None:
            return False

        await db.delete(establishment)
        await db.flush()
        return True

    async def list_projects_for_user(
        self,
        db: AsyncSession,
        ws_id: UUID,
        user_id: UUID,
    ) -> list[Project]:
        stmt = (
            select(Project)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .where(
                Project.workspace_id == ws_id,
                self._project_visibility_condition(user_id),
            )
            .order_by(Project.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_project(
        self,
        db: AsyncSession,
        ws_id: UUID,
        data: ProjectCreate,
    ) -> Project:
        project = Project(
            workspace_id=ws_id,
            name=data.name,
            description=data.description,
        )
        db.add(project)
        await db.flush()
        await db.refresh(project)
        return project

    async def get_project_for_user(
        self,
        db: AsyncSession,
        proj_id: UUID,
        user_id: UUID,
    ) -> Project | None:
        stmt = (
            select(Project)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .where(
                Project.id == proj_id,
                self._project_visibility_condition(user_id),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_project(
        self,
        db: AsyncSession,
        proj_id: UUID,
        data: ProjectUpdate,
    ) -> Project | None:
        project = await db.get(Project, proj_id)
        if project is None:
            return None

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(project, field, value)

        await db.flush()
        await db.refresh(project)
        return project

    async def delete_project(
        self,
        db: AsyncSession,
        proj_id: UUID,
    ) -> bool:
        project = await db.get(Project, proj_id)
        if project is None:
            return False
        await db.delete(project)
        await db.flush()
        return True

    async def list_project_members(
        self,
        db: AsyncSession,
        proj_id: UUID,
    ) -> list[MemberResponse]:
        result = await db.execute(
            select(
                User.id,
                User.email,
                User.is_active,
                ProjectMember.role,
                ProjectMember.created_at,
            )
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == proj_id)
            .order_by(User.email)
        )
        return [
            MemberResponse(
                user_id=row.id,
                email=row.email,
                is_active=row.is_active,
                role=row.role.value if hasattr(row.role, "value") else str(row.role),
                created_at=row.created_at,
            )
            for row in result.all()
        ]

    async def add_project_member(
        self,
        db: AsyncSession,
        proj_id: UUID,
        payload: AddMemberRequest,
    ) -> MemberResponse:
        role = self._parse_role(ProjectRole, payload.role)
        user = await self._get_user_by_email(db, payload.email)
        self._ensure_found(user, f"Usuario '{payload.email}' nao encontrado.")

        exists_result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj_id,
                ProjectMember.user_id == user.id,
            )
        )
        if exists_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Usuario ja e membro deste projeto.",
            )

        membership = ProjectMember(
            project_id=proj_id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
        await db.flush()
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            is_active=user.is_active,
            role=membership.role.value,
            created_at=membership.created_at,
        )

    async def update_project_member_role(
        self,
        db: AsyncSession,
        proj_id: UUID,
        user_id: UUID,
        role_raw: str,
    ) -> MemberResponse | None:
        result = await db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == proj_id,
                ProjectMember.user_id == user_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None

        membership, user = row[0], row[1]
        membership.role = self._parse_role(ProjectRole, role_raw)
        await db.flush()
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            is_active=user.is_active,
            role=membership.role.value,
            created_at=membership.created_at,
        )

    async def remove_project_member(
        self,
        db: AsyncSession,
        proj_id: UUID,
        user_id: UUID,
    ) -> bool:
        membership = await self._get_project_member(db, proj_id, user_id)
        if membership is None:
            return False
        await db.delete(membership)
        await db.flush()
        return True

    async def _get_user_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def _get_organization_member(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
    ) -> OrganizationMember | None:
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_workspace_member(
        self,
        db: AsyncSession,
        ws_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMember | None:
        result = await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_project_member(
        self,
        db: AsyncSession,
        proj_id: UUID,
        user_id: UUID,
    ) -> ProjectMember | None:
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _ensure_not_last_owner(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
    ) -> None:
        count_result = await db.execute(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == OrganizationRole.OWNER,
                OrganizationMember.user_id != user_id,
            )
        )
        remaining_owners = count_result.scalar_one()
        if remaining_owners == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nao e permitido remover ou rebaixar o ultimo OWNER da organization.",
            )

    def _parse_role(self, enum_cls, raw_role: str):
        try:
            return enum_cls(raw_role.upper())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in enum_cls)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Role invalido. Valores aceitos: {allowed}.",
            ) from exc

    def _ensure_found(self, value, detail: str) -> None:
        if value is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

    def _organization_visibility_condition(self, user_id: UUID):
        internal_org_member = exists(
            select(1)
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == Organization.id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.role.in_(
                    [
                        OrganizationRole.OWNER,
                        OrganizationRole.MANAGER,
                        OrganizationRole.MEMBER,
                    ]
                ),
            )
            .correlate(Organization)
        )
        workspace_member = exists(
            select(1)
            .select_from(WorkspaceMember)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(
                Workspace.organization_id == Organization.id,
                WorkspaceMember.user_id == user_id,
            )
            .correlate(Organization)
        )
        project_member = exists(
            select(1)
            .select_from(ProjectMember)
            .join(Project, Project.id == ProjectMember.project_id)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .where(
                Workspace.organization_id == Organization.id,
                ProjectMember.user_id == user_id,
            )
            .correlate(Organization)
        )
        return or_(internal_org_member, workspace_member, project_member)

    def _workspace_visibility_condition(self, user_id: UUID):
        internal_org_member = exists(
            select(1)
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == Workspace.organization_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.role.in_(
                    [
                        OrganizationRole.OWNER,
                        OrganizationRole.MANAGER,
                        OrganizationRole.MEMBER,
                    ]
                ),
            )
            .correlate(Workspace)
        )
        workspace_member = exists(
            select(1)
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == Workspace.id,
                WorkspaceMember.user_id == user_id,
            )
            .correlate(Workspace)
        )
        project_member = exists(
            select(1)
            .select_from(ProjectMember)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                Project.workspace_id == Workspace.id,
                ProjectMember.user_id == user_id,
            )
            .correlate(Workspace)
        )
        return or_(internal_org_member, workspace_member, project_member)

    def _project_visibility_condition(self, user_id: UUID):
        internal_org_member = exists(
            select(1)
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == Workspace.organization_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.role.in_(
                    [
                        OrganizationRole.OWNER,
                        OrganizationRole.MANAGER,
                        OrganizationRole.MEMBER,
                    ]
                ),
            )
            .correlate(Workspace)
        )
        workspace_member = exists(
            select(1)
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == Project.workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .correlate(Project)
        )
        project_member = exists(
            select(1)
            .select_from(ProjectMember)
            .where(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user_id,
            )
            .correlate(Project)
        )
        return or_(internal_org_member, workspace_member, project_member)


b2b_service = B2BService()
