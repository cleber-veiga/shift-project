"""
Modelos ORM de workspace, memberships e concorrentes.
"""

import uuid
from datetime import datetime
from enum import Enum, StrEnum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class WorkspaceRole(str, Enum):
    MANAGER = "MANAGER"
    CONSULTANT = "CONSULTANT"
    VIEWER = "VIEWER"


class WorkspacePlayerDatabaseType(StrEnum):
    POSTGRESQL = "POSTGRESQL"
    MYSQL = "MYSQL"
    SQLSERVER = "SQLSERVER"
    ORACLE = "ORACLE"
    FIREBIRD = "FIREBIRD"
    SQLITE = "SQLITE"
    SNOWFLAKE = "SNOWFLAKE"


class Workspace(Base):
    """Produto ou departamento da organization."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="workspaces", lazy="raise_on_sql")
    projects: Mapped[list["Project"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    players: Mapped[list["WorkspacePlayer"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    users: Mapped[list["User"]] = relationship(
        secondary="workspace_members",
        viewonly=True,
        lazy="raise_on_sql",
    )
    workflows: Mapped[list["Workflow"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )
    input_models: Mapped[list["InputModel"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )


class WorkspaceMember(Base):
    """Membership do usuario no workspace."""

    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        SqlEnum(
            WorkspaceRole,
            name="workspace_role",
            native_enum=False,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="members", lazy="raise_on_sql")
    user: Mapped["User"] = relationship(back_populates="workspace_memberships", lazy="raise_on_sql")


class WorkspacePlayer(Base):
    __tablename__ = "workspace_players"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_workspace_player_workspace_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    database_type: Mapped[WorkspacePlayerDatabaseType] = mapped_column(
        SqlEnum(
            WorkspacePlayerDatabaseType,
            name="workspace_player_database_type",
            native_enum=False,
        ),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="players", lazy="raise_on_sql")
