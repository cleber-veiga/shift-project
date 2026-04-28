"""
Schemas Pydantic para conectores de banco de dados.

Regra de ouro: a senha NUNCA aparece em ConnectionResponse.
O frontend deve tratar o campo como write-only.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConnectionType(str, Enum):
    """Tipos de banco de dados suportados pela plataforma."""

    oracle = "oracle"
    postgresql = "postgresql"
    firebird = "firebird"
    sqlserver = "sqlserver"
    mysql = "mysql"


class ConnectionCreate(BaseModel):
    """Payload para criar um novo conector."""

    name: str = Field(..., min_length=1, max_length=255, description="Nome legivel do conector")
    workspace_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    # Concorrente ao qual a conexao esta vinculada (apenas para categorização).
    player_id: uuid.UUID | None = None
    type: ConnectionType
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., gt=0, lt=65536)
    database: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, description="Senha em texto plano — sera criptografada")
    extra_params: dict[str, Any] | None = Field(
        default=None,
        description="Parametros extras de URL (ex: driver para SQL Server)",
    )
    include_schemas: list[str] | None = Field(
        default=None,
        description="Schemas adicionais a incluir na introspecção (ex: ['VIASOFTBASE']). "
                    "As tabelas aparecem como SCHEMA.TABELA no catálogo.",
    )
    is_public: bool = Field(
        default=True,
        description="True = visivel a todos do workspace/projeto; False = somente o criador.",
    )

    @model_validator(mode="after")
    def validate_scope(self) -> "ConnectionCreate":
        if (self.workspace_id is None) == (self.project_id is None):
            raise ValueError("Informe exatamente um entre workspace_id e project_id.")
        return self


class ConnectionUpdate(BaseModel):
    """Payload para atualizar parcialmente um conector (todos os campos opcionais)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    player_id: uuid.UUID | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, gt=0, lt=65536)
    database: str | None = Field(default=None, min_length=1)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, description="Deixe nulo para manter a senha atual")
    extra_params: dict[str, Any] | None = None
    include_schemas: list[str] | None = None
    is_public: bool | None = None


class ConnectionResponse(BaseModel):
    """Representacao publica de um conector — sem a senha."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    player_id: uuid.UUID | None = None
    name: str
    type: ConnectionType
    host: str
    port: int
    database: str
    username: str
    # A senha e intencionalmente omitida.
    extra_params: dict[str, Any] | None = None
    include_schemas: list[str] | None = None
    is_public: bool
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class TestConnectionResult(BaseModel):
    """Resultado do teste de conectividade."""

    success: bool
    message: str


class ConnectionListResponse(BaseModel):
    """Resposta paginada de conectores."""

    items: list[ConnectionResponse]
    total: int
    page: int
    size: int


class DiagnosticStepSchema(BaseModel):
    """Uma etapa do pipeline de diagnostico.

    'dns'|'tcp'|'greeting'|'auth_query' sao etapas do pipeline Firebird.
    'test' e usado como stage unico para tipos de banco que ainda nao tem
    pipeline em etapas (Postgres, Oracle, etc) — apenas tenta conectar via
    SQLAlchemy e devolve sucesso/falha.
    """

    stage: Literal["dns", "tcp", "greeting", "auth_query", "test"]
    ok: bool
    latency_ms: int | None = None
    error_class: str | None = None
    error_msg: str | None = None
    hint: str | None = None


class DiagnosticReport(BaseModel):
    """Resultado do pipeline de diagnostico (1 ou 4 etapas)."""

    overall_ok: bool
    first_failure_stage: str | None = None
    steps: list[DiagnosticStepSchema]


class ConnectionDiagnosePayload(BaseModel):
    """Payload stateless para testar uma conexao SEM persistir.

    Usado durante o fluxo de criacao no frontend, antes do usuario clicar
    em 'Salvar'. So contem o necessario para abrir conexao — sem name,
    workspace_id, etc.
    """

    type: ConnectionType
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., gt=0, lt=65536)
    database: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)
    extra_params: dict[str, Any] | None = None
