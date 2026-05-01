"""
Endpoints para consulta de resultados de execucoes de workflows.

Expoe o preview on-demand de nós — separado do evento SSE para manter
o stream leve e buscar dados apenas quando o usuário clicar num nó.
"""
from __future__ import annotations

import datetime
import decimal
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import require_permission
from app.data_pipelines.duckdb_storage import quote_identifier, sanitize_name
from app.models.workflow import WorkflowExecution

logger = get_logger(__name__)

router = APIRouter(tags=["executions"])

_SHIFT_EXECUTIONS_DIR = Path(tempfile.gettempdir()) / "shift" / "executions"
_MAX_PREVIEW_ROWS = 1000
_MAX_PIN_ROWS = 5_000


def _serialize(v: Any) -> Any:
    """Normaliza tipos DuckDB para JSON."""
    if v is None:
        return None
    try:
        if isinstance(v, decimal.Decimal):
            return float(v)
        if isinstance(v, (datetime.date, datetime.datetime)):
            return v.isoformat()
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return v.decode("latin-1")
                except Exception:
                    return v.hex()
        if isinstance(v, str):
            return v.encode("utf-8", errors="replace").decode("utf-8")
    except Exception:  # noqa: BLE001
        pass
    return v


def _open_node_duckdb_table(
    execution_id: str,
    node_id: str,
) -> tuple[duckdb.DuckDBPyConnection, str]:
    """Abre conexão DuckDB para o output de um nó e retorna (con, table_ref).

    Lança HTTPException em caso de caminho inválido, arquivo ausente ou erro
    de query. O chamador é responsável por fechar a conexão.

    Fallback para nós com branches (bulk_insert escreve em
    ``{node_id}_success.duckdb`` em vez de ``{node_id}.duckdb``) — quando o
    arquivo principal não existe, tenta o ``_success`` como preview default.
    """
    safe_node = sanitize_name(node_id)
    base_dir = _SHIFT_EXECUTIONS_DIR / execution_id
    main_path = base_dir / f"{safe_node}.duckdb"
    success_path = base_dir / f"{safe_node}_success.duckdb"

    db_path = main_path if main_path.exists() else success_path

    try:
        resolved = db_path.resolve()
        allowed = _SHIFT_EXECUTIONS_DIR.resolve()
        resolved.relative_to(allowed)
    except (ValueError, OSError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parâmetros de execução inválidos.",
        )

    if not db_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Resultado do nó '{node_id}' não encontrado. "
                "O nó pode não ter rodado ainda ou a execução foi limpa."
            ),
        )

    try:
        con = duckdb.connect(str(db_path))
        # Caminho legacy do extractor (extract_sql_to_duckdb com dlt) cria
        # tabelas em schema "shift_extract"; o particionado materializa
        # em "main". information_schema unifica os dois sem precisar
        # mudar o extractor.
        tables_res = con.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'system')
              AND table_type = 'BASE TABLE'
            ORDER BY
              CASE table_schema WHEN 'main' THEN 0 ELSE 1 END,
              table_name
            """
        ).fetchall()
        if not tables_res:
            con.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nenhuma tabela encontrada no resultado do nó.",
            )

        # dlt cria _dlt_loads, _dlt_pipeline_state, _dlt_version no
        # mesmo schema da tabela do usuário; sem esse filtro o preview
        # pode mostrar metadados internos do dlt.
        user_tables = [
            (s, t) for s, t in tables_res
            if not t.startswith("_dlt_")
        ]
        if not user_tables:
            con.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nenhuma tabela encontrada no resultado do nó.",
            )

        # Last table = output. Processadores appendam tabelas em ordem;
        # ORDER BY acima já posiciona "main" antes de outros schemas.
        table_schema, table_name_str = user_tables[-1]
        if table_schema != "main":
            logger.info(
                "preview.non_main_schema",
                execution_id=execution_id,
                node_id=node_id,
                schema=table_schema,
                table=table_name_str,
            )
        table_ref = (
            f"{quote_identifier(table_schema)}.{quote_identifier(table_name_str)}"
        )
        return con, table_ref
    except HTTPException:
        raise
    except duckdb.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Erro ao ler resultado do nó: {exc}",
        )


@router.get("/executions/{execution_id}/nodes/{node_id}/preview")
async def get_node_preview(
    execution_id: str,
    node_id: str,
    limit: int = Query(default=100, ge=1, le=_MAX_PREVIEW_ROWS),
    offset: int = Query(default=0, ge=0),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """
    Retorna N linhas do output de um nó de execução.

    Usa a convenção de caminho /tmp/shift/executions/{execution_id}/{node_id}.duckdb
    já persistida pelo runner em modo ``test``. Retorna 404 se o nó não tiver
    rodado ainda ou se a execução foi limpa.
    """
    con, table_ref = _open_node_duckdb_table(execution_id, node_id)
    try:
        total_row = con.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()
        total = int(total_row[0]) if total_row else 0

        result = con.execute(
            f"SELECT * FROM {table_ref} LIMIT {limit} OFFSET {offset}"
        )
        raw_rows = result.fetchall()
        columns = [desc[0] for desc in result.description or []]
    except HTTPException:
        raise
    except duckdb.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Erro ao ler resultado do nó: {exc}",
        )
    finally:
        con.close()

    rows_dict = [
        {col: _serialize(val) for col, val in zip(columns, row)}
        for row in raw_rows
    ]

    return {
        "columns": columns,
        "rows": rows_dict,
        "row_count": len(rows_dict),
        "total_rows": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/executions/{execution_id}/nodes/{node_id}/materialize-pin")
async def materialize_node_pin(
    execution_id: str,
    node_id: str,
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Materializa as linhas do output de um nó para persistência como pin v3.

    Lê até ``_MAX_PIN_ROWS`` linhas do DuckDB do nó e devolve o payload
    pronto para ser armazenado em ``node.data.pinnedOutput`` no YAML do
    workflow. Ao contrário do preview paginado, o pin precisa de todos os
    dados para que o workflow rode offline (sem execução prévia).
    """
    con, table_ref = _open_node_duckdb_table(execution_id, node_id)
    try:
        total_row = con.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()
        total_rows = int(total_row[0]) if total_row else 0

        result = con.execute(f"SELECT * FROM {table_ref} LIMIT {_MAX_PIN_ROWS}")
        raw_rows = result.fetchall()
        columns = [desc[0] for desc in result.description or []]
    except HTTPException:
        raise
    except duckdb.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Erro ao materializar pin: {exc}",
        )
    finally:
        con.close()

    rows_dict = [
        {col: _serialize(val) for col, val in zip(columns, row)}
        for row in raw_rows
    ]

    truncated = total_rows > _MAX_PIN_ROWS
    row_count = len(rows_dict)
    schema_fingerprint = hashlib.md5(
        json.dumps(columns).encode(), usedforsecurity=False
    ).hexdigest()[:8]

    logger.info(
        "pin.materialized",
        execution_id=execution_id,
        node_id=node_id,
        total_rows=total_rows,
        row_count=row_count,
        truncated=truncated,
    )

    return {
        "columns": columns,
        "rows": rows_dict,
        "row_count": row_count,
        "total_rows": total_rows,
        "truncated": truncated,
        "schema_fingerprint": schema_fingerprint,
    }


@router.get("/executions/{execution_id}/plan")
async def get_execution_plan(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Retorna o ExecutionPlanSnapshot de uma execução.

    Disponível após qualquer execução que tenha passado pelo dynamic_runner
    com Fase 4 ativa. Retorna 404 se a execução não existe ou se o plano
    ainda não foi capturado (execuções anteriores à Fase 4).
    """
    try:
        eid = UUID(execution_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="execution_id deve ser um UUID válido.",
        )

    result = await db.execute(
        select(WorkflowExecution.plan_snapshot, WorkflowExecution.status).where(
            WorkflowExecution.id == eid
        )
    )
    row = result.first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execução '{execution_id}' não encontrada.",
        )

    plan_snapshot, exec_status = row

    if plan_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Plano de execução não disponível. "
                "Esta execução pode ter ocorrido antes da Fase 4 ser ativada, "
                f"ou a execução falhou antes do plano ser capturado (status: {exec_status})."
            ),
        )

    return {"execution_id": execution_id, "status": exec_status, "plan": plan_snapshot}
