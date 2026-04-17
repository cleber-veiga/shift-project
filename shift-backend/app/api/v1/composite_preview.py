"""
Endpoint de preview de SQL para o no composto personalizavel.

Recebe o blueprint (ou um step individual) + conn_type e devolve o SQL que
seria executado pelo ``load_service.insert_composite`` — sem tocar no banco.
Util na UI do editor para o usuario validar antes de salvar.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.models import User
from app.services.load_service import _build_upsert_sql

router = APIRouter(tags=["composite-preview"])


_SUPPORTED_DIALECTS = ("postgres", "sqlite", "oracle")


class CompositePreviewStep(BaseModel):
    """Descreve um passo do blueprint para geracao de SQL."""

    alias: str
    table: str = Field(..., min_length=1)
    columns: list[str] = Field(..., min_length=1)
    conflict_mode: Literal["insert", "upsert", "insert_or_ignore"] = "insert"
    conflict_keys: list[str] = Field(default_factory=list)
    update_columns: list[str] | None = None
    returning: list[str] = Field(default_factory=list)


class CompositePreviewRequest(BaseModel):
    """Payload do preview: blueprint normalizado + dialeto alvo."""

    conn_type: Literal["postgres", "sqlite", "oracle"] = Field(
        ..., description="Dialeto do conector de destino."
    )
    steps: list[CompositePreviewStep] = Field(..., min_length=1)


class CompositePreviewStatementOut(BaseModel):
    """SQL gerado para um passo."""

    alias: str
    table: str
    conflict_mode: str
    primary_sql: str
    fetch_existing_sql: str | None = None
    always_fetch: bool = False


class CompositePreviewResponse(BaseModel):
    """Resposta do preview com um statement por passo."""

    statements: list[CompositePreviewStatementOut]


@router.post(
    "/composite/preview-sql",
    response_model=CompositePreviewResponse,
)
async def preview_composite_sql(
    payload: CompositePreviewRequest,
    current_user: User = Depends(get_current_user),
) -> CompositePreviewResponse:
    """Gera o SQL que seria executado por cada passo do blueprint.

    Para ``conflict_mode == 'insert'`` devolve um INSERT simples
    parametrizado; para upsert/insert_or_ignore delega ao builder real
    usado pelo load_service, garantindo que o preview reflete o que
    vai rodar em producao.
    """
    if payload.conn_type not in _SUPPORTED_DIALECTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dialeto '{payload.conn_type}' nao suportado para preview.",
        )

    statements: list[CompositePreviewStatementOut] = []

    for step in payload.steps:
        try:
            if step.conflict_mode == "insert":
                primary_sql = _build_plain_insert_sql(
                    table=step.table,
                    columns=step.columns,
                    returning=step.returning,
                )
                statements.append(
                    CompositePreviewStatementOut(
                        alias=step.alias,
                        table=step.table,
                        conflict_mode=step.conflict_mode,
                        primary_sql=primary_sql,
                        fetch_existing_sql=None,
                        always_fetch=False,
                    )
                )
            else:
                stmts = _build_upsert_sql(
                    conn_type=payload.conn_type,
                    table=step.table,
                    columns=step.columns,
                    conflict_mode=step.conflict_mode,
                    conflict_keys=step.conflict_keys,
                    update_columns=step.update_columns,
                    returning=step.returning,
                )
                statements.append(
                    CompositePreviewStatementOut(
                        alias=step.alias,
                        table=step.table,
                        conflict_mode=step.conflict_mode,
                        primary_sql=stmts.primary,
                        fetch_existing_sql=stmts.fetch_existing,
                        always_fetch=stmts.always_fetch,
                    )
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"alias='{step.alias}': {exc}",
            ) from exc

    return CompositePreviewResponse(statements=statements)


def _build_plain_insert_sql(
    *,
    table: str,
    columns: list[str],
    returning: list[str],
) -> str:
    """INSERT portavel para preview no modo 'insert' (sem conflict handling)."""
    schema: str | None = None
    bare = table
    if "." in table:
        schema, bare = table.split(".", 1)
    if schema:
        target = f'"{schema}"."{bare}"'
    else:
        target = f'"{bare}"'
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    returning_clause = (
        " RETURNING " + ", ".join(f'"{c}"' for c in returning) if returning else ""
    )
    return f"INSERT INTO {target} ({col_list}) VALUES ({placeholders}){returning_clause}"
