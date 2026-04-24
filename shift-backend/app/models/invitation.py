"""
Modelo ORM de convites para membership.
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class InvitationScope(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    WORKSPACE = "WORKSPACE"
    PROJECT = "PROJECT"


class InvitationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class Invitation(Base):
    """Convite para um usuario entrar em um escopo (org/workspace/project)."""

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint(
            """
            (scope = 'ORGANIZATION' AND organization_id IS NOT NULL
                AND workspace_id IS NULL AND project_id IS NULL)
            OR
            (scope = 'WORKSPACE' AND workspace_id IS NOT NULL
                AND project_id IS NULL)
            OR
            (scope = 'PROJECT' AND project_id IS NOT NULL)
            """,
            name="ck_invitation_scope_ids",
        ),
        Index("ix_invitations_email_status", "email", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )

    scope: Mapped[InvitationScope] = mapped_column(
        SqlEnum(InvitationScope, native_enum=False, length=32),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    role: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[InvitationStatus] = mapped_column(
        SqlEnum(InvitationStatus, native_enum=False, length=32),
        nullable=False,
        server_default=text("'PENDING'"),
    )

    invited_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    invited_by: Mapped["User"] = relationship(foreign_keys=[invited_by_id])
    accepted_by: Mapped["User | None"] = relationship(foreign_keys=[accepted_by_id], lazy="raise_on_sql")


from app.models.user import User  # noqa: E402
