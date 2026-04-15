"""
Modelo ORM: Connection (conector de banco de dados reutilizavel).

Uma conexao pode pertencer a um Workspace (compartilhada) ou a um Project
(exclusiva do cliente). A senha e persistida criptografada via
EncryptedString, um TypeDecorator Fernet que opera de forma transparente
no SQLAlchemy.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.encryption import EncryptedString
from app.db.base import Base


class Connection(Base):
    """Conector reutilizavel de banco de dados com senha criptografada."""

    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint(
            "workspace_id IS NOT NULL OR project_id IS NOT NULL",
            name="ck_connection_owner_not_null",
        ),
        CheckConstraint(
            "NOT (workspace_id IS NOT NULL AND project_id IS NOT NULL)",
            name="ck_connection_single_owner",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Tipo do banco: oracle | postgresql | firebird | sqlserver | mysql
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    # Caminho/nome do banco. Populado do player quando player_id for informado.
    # Texto longo para suportar caminhos Windows do Firebird.
    database: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Concorrente (player) ao qual esta conexão está vinculada (opcional).
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Senha armazenada como token Fernet — descriptografada automaticamente ao ler.
    password: Mapped[str] = mapped_column(EncryptedString(1024), nullable=False)
    # Parametros adicionais de conexao (ex: {"driver": "ODBC+Driver+17+for+SQL+Server"})
    extra_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Schemas adicionais a incluir na introspecção (ex: ["VIASOFTBASE", "VIASOFTCTB"]).
    # Quando informado, as tabelas desses schemas aparecem como "SCHEMA.TABELA" no catálogo.
    include_schemas: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Visibilidade: True = visivel a todos do workspace/projeto; False = somente o criador.
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Quem cadastrou a conexao.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
