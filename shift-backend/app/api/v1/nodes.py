"""
Endpoints utilitários para nós de workflow.

Atualmente expõe apenas o preview de resultados DuckDB para nós SQL,
restaurando a visualização em tabela no modo de teste.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.models import User

router = APIRouter(tags=["nodes"])

_MAX_PREVIEW_ROWS = 500
_SHIFT_EXECUTIONS_DIR = Path(tempfile.gettempdir()) / "shift" / "executions"


class DuckDbPreviewRequest(BaseModel):
    database_path: str = Field(..., description="Caminho do arquivo .duckdb")
    table_name: str = Field(..., description="Nome da tabela dentro do arquivo")
    dataset_name: str | None = Field(default=None, description="Schema/dataset (dlt usa 'shift_extract')")
    limit: int = Field(default=_MAX_PREVIEW_ROWS, ge=1, le=_MAX_PREVIEW_ROWS)


class DuckDbPreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


def _quote_ident(name: str) -> str:
    """Escapa um identificador SQL para DuckDB (aspas duplas, dobrando as existentes)."""
    return '"' + name.replace('"', '""') + '"'


def _validate_duckdb_path(database_path: str) -> Path:
    """Garante que o caminho está dentro do diretório de execuções do Shift."""
    try:
        path = Path(database_path).resolve()
        allowed = _SHIFT_EXECUTIONS_DIR.resolve()
        path.relative_to(allowed)
    except (ValueError, OSError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Caminho de banco inválido ou fora do diretório permitido.",
        )
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo DuckDB não encontrado. A execução pode ter expirado.",
        )
    return path


@router.post("/nodes/duckdb-preview", response_model=DuckDbPreviewResponse)
async def duckdb_preview(
    body: DuckDbPreviewRequest,
    _current_user: User = Depends(get_current_user),
) -> DuckDbPreviewResponse:
    """Retorna até 500 linhas de um resultado DuckDB materializado por um nó SQL."""
    path = _validate_duckdb_path(body.database_path)

    try:
        # ``read_only=True`` removido — vide nota em filter_node sobre
        # incompatibilidade de configs concorrentes pra mesmo arquivo.
        con = duckdb.connect(str(path))
        try:
            fetch_limit = body.limit + 1
            if body.dataset_name:
                table_ref = f"{_quote_ident(body.dataset_name)}.{_quote_ident(body.table_name)}"
            else:
                table_ref = _quote_ident(body.table_name)
            result = con.execute(f"SELECT * FROM {table_ref} LIMIT {fetch_limit}")
            raw_rows = result.fetchall()
            columns = [desc[0] for desc in result.description or []]
        finally:
            con.close()
    except duckdb.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Erro ao ler DuckDB: {exc}",
        )

    truncated = len(raw_rows) > body.limit
    rows_to_return = raw_rows[: body.limit]

    def _serialize(v: Any) -> Any:
        if v is None:
            return None
        try:
            # duckdb pode retornar tipos como Decimal, date, etc.
            import decimal, datetime
            if isinstance(v, decimal.Decimal):
                return float(v)
            if isinstance(v, (datetime.date, datetime.datetime)):
                return v.isoformat()
            if isinstance(v, bytes):
                # BLOBs ou strings em encoding não-UTF-8 (ex.: Firebird latin-1)
                try:
                    return v.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        return v.decode("latin-1")
                    except Exception:
                        return v.hex()
            if isinstance(v, str):
                # Garante que a string é UTF-8 válida; substitui bytes inválidos.
                # Necessário porque DuckDB pode retornar str com surrogates de
                # dados cuja origem (ex.: Firebird) não respeitou o encoding declarado.
                return v.encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            pass
        return v

    rows_dict = [
        {col: _serialize(val) for col, val in zip(columns, row)}
        for row in rows_to_return
    ]

    return DuckDbPreviewResponse(
        columns=columns,
        rows=rows_dict,
        row_count=len(rows_to_return),
        truncated=truncated,
    )
