"""
Servico unificado de extracao de dados.

Centraliza toda leitura de fontes SQL (incluindo Firebird via driver direto),
com streaming, paginacao e serializacao automatica de tipos.

Usado tanto pelo modo teste (workflow_test_service) quanto pelo modo
producao (workflow/nodes/sql_database).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import dlt
import sqlalchemy as sa


# ─── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    """Resultado de uma extracao SQL."""
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    preview_limit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "row_count": self.row_count,
            "columns": self.columns,
            "rows": self.rows,
        }
        if self.preview_limit is not None:
            d["preview_limit"] = self.preview_limit
        return d


@dataclass
class DuckDbExtractionResult:
    """Resultado de uma extracao SQL materializada em DuckDB."""
    storage_type: str = "duckdb"
    pipeline_name: str = ""
    dataset_name: str = ""
    resource_name: str = ""
    table_name: str = ""
    database_path: str = ""
    load_ids: list[str] = field(default_factory=list)
    destination_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "storage_type": self.storage_type,
            "pipeline_name": self.pipeline_name,
            "dataset_name": self.dataset_name,
            "resource_name": self.resource_name,
            "table_name": self.table_name,
            "database_path": self.database_path,
            "load_ids": self.load_ids,
            "destination_name": self.destination_name,
        }


# ─── Servico ─────────────────────────────────────────────────────────────────

class ExtractionService:
    """Servico unificado de leitura/extracao de dados."""

    def extract_sql(
        self,
        connection_string: str,
        conn_type: str,
        query: str,
        *,
        max_rows: int = 200,
        chunk_size: int = 1000,
        firebird_config: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """
        Extrai dados SQL e retorna rows em memoria.

        Para modo teste: retorna rows[] limitados a max_rows.
        Para Firebird: usa driver direto via firebird_config.
        """
        if firebird_config is not None:
            return self._extract_firebird(firebird_config, query, max_rows)

        return self._extract_sa(connection_string, conn_type, query, max_rows)

    def extract_sql_to_duckdb(
        self,
        connection_string: str,
        query: str,
        execution_id: str,
        resource_name: str,
        *,
        table_name: str | None = None,
        max_rows: int | None = None,
        chunk_size: int = 1000,
    ) -> DuckDbExtractionResult:
        """
        Extrai dados SQL em streaming e persiste em DuckDB temporario.

        Para modo producao: materializa em DuckDB temp usando dlt pipeline.
        """
        normalized_url = _normalize_connection_url(connection_string)
        safe_resource = _sanitize_name(resource_name or "sql_extract")
        safe_table = _sanitize_name(table_name or safe_resource)
        duckdb_path = _build_duckdb_path(execution_id, safe_resource)
        pipelines_dir = _build_dlt_pipelines_dir(execution_id)
        pipeline_name = _sanitize_name(
            f"shift_extract_{execution_id}_{safe_resource}"
        )
        dataset_name = "shift_extract"

        @dlt.resource(name=safe_resource, write_disposition="replace")
        def sql_resource() -> Any:
            engine = sa.create_engine(normalized_url)
            total_rows = 0
            try:
                with engine.connect().execution_options(stream_results=True) as conn:
                    result = conn.execute(sa.text(query))
                    while True:
                        batch = result.mappings().fetchmany(chunk_size)
                        if not batch:
                            break
                        for row in batch:
                            yield dict(row)
                            total_rows += 1
                            if max_rows is not None and total_rows >= max_rows:
                                return
            finally:
                engine.dispose()

        pipeline = dlt.pipeline(
            pipeline_name=pipeline_name,
            pipelines_dir=str(pipelines_dir),
            destination=dlt.destinations.duckdb(credentials=str(duckdb_path)),
            dataset_name=dataset_name,
            progress="log",
        )

        load_info = pipeline.run(
            sql_resource(),
            table_name=safe_table,
            write_disposition="replace",
        )

        return DuckDbExtractionResult(
            pipeline_name=pipeline.pipeline_name,
            dataset_name=dataset_name,
            resource_name=safe_resource,
            table_name=safe_table,
            database_path=str(duckdb_path),
            load_ids=list(load_info.loads_ids),
            destination_name=str(load_info.destination_name),
        )

    # ── Extractores internos ─────────────────────────────────────────────────

    def _extract_sa(
        self,
        connection_string: str,
        conn_type: str,
        query: str,
        max_rows: int,
    ) -> ExtractionResult:
        """Extracao via SQLAlchemy para todos os bancos exceto Firebird.

        max_rows=0 significa sem limite (busca todas as linhas).
        """
        connect_args: dict[str, Any] = {}
        if conn_type == "sqlserver":
            connect_args["TrustServerCertificate"] = "yes"

        engine: sa.Engine | None = None
        try:
            engine = sa.create_engine(
                connection_string,
                pool_pre_ping=False,
                pool_size=1,
                max_overflow=0,
                connect_args=connect_args,
            )
            with engine.connect() as db_conn:
                result = db_conn.execute(sa.text(query))
                columns = list(result.keys())
                if max_rows > 0:
                    rows = result.fetchmany(max_rows)
                else:
                    rows = result.fetchall()
                serialized = [
                    {col: _serialize_value(val) for col, val in zip(columns, row)}
                    for row in rows
                ]
                return ExtractionResult(
                    rows=serialized,
                    columns=columns,
                    row_count=len(serialized),
                    preview_limit=max_rows if max_rows > 0 else None,
                )
        finally:
            if engine:
                engine.dispose()

    def _extract_firebird(
        self,
        config: dict[str, Any],
        query: str,
        max_rows: int,
    ) -> ExtractionResult:
        """Extracao via driver Firebird direto.

        max_rows=0 significa sem limite (busca todas as linhas).
        """
        from app.services.firebird_client import connect_firebird

        fb_conn = None
        try:
            fb_conn = connect_firebird(
                config=config,
                secret={"password": config.get("password", "")},
            )
            cur = fb_conn.cursor()
            cur.execute(query)
            columns = [desc[0] for desc in (cur.description or [])]
            if max_rows > 0:
                rows = cur.fetchmany(max_rows)
            else:
                rows = cur.fetchall()
            cur.close()
            serialized = [
                {col: _serialize_value(val) for col, val in zip(columns, row)}
                for row in rows
            ]
            return ExtractionResult(
                rows=serialized,
                columns=columns,
                row_count=len(serialized),
                preview_limit=max_rows if max_rows > 0 else None,
            )
        finally:
            if fb_conn is not None:
                try:
                    fb_conn.close()
                except Exception:
                    pass


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _serialize_value(val: Any) -> Any:
    """Converte valores nao-serializaveis para JSON."""
    if val is None or isinstance(val, (int, float, str, bool)):
        return val
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, dt_time):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    return str(val)


def _normalize_connection_url(connection_url: str) -> str:
    """Converte drivers async para variantes sincronas."""
    replacements = {
        "+asyncpg": "+psycopg2",
        "+aiosqlite": "",
        "+asyncmy": "+pymysql",
    }
    normalized = connection_url
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _sanitize_name(value: str) -> str:
    sanitized = "".join(
        c if c.isalnum() or c == "_" else "_"
        for c in value.strip().lower()
    )
    return sanitized.strip("_") or "resource"


def _build_duckdb_path(execution_id: str, resource_name: str) -> Path:
    base_dir = Path(tempfile.gettempdir()) / "shift" / "executions" / execution_id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{resource_name}.duckdb"


def _build_dlt_pipelines_dir(execution_id: str) -> Path:
    base_dir = (
        Path(tempfile.gettempdir())
        / "shift"
        / "executions"
        / execution_id
        / "dlt"
    )
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


# ─── Instancia singleton ────────────────────────────────────────────────────

extraction_service = ExtractionService()
