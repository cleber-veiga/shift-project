"""
Servico do Playground SQL — execução de SELECT e introspecção de schema com cache.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.connection_schema import ConnectionSchema
from app.schemas.connection import ConnectionType
from app.schemas.playground import (
    PlaygroundQueryResponse,
    SchemaColumn,
    SchemaResponse,
    SchemaTable,
)
from app.services.connection_service import connection_service

_QUERY_TIMEOUT_SECONDS: float = 30.0
_SCHEMA_CACHE_MAX_AGE = timedelta(days=90)  # 3 meses

# Palavras proibidas no início da instrução SQL (após espaços/comentários)
_FORBIDDEN_KEYWORDS = re.compile(
    r"^\s*"
    r"(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|EXEC|EXECUTE"
    r"|CALL|GRANT|REVOKE|MERGE|UPSERT|SET|COMMIT|ROLLBACK|SAVEPOINT"
    r"|BEGIN|DECLARE|INTO)\b",
    re.IGNORECASE,
)

_ALLOWED_START = re.compile(
    r"^\s*(SELECT|WITH)\b",
    re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    """Remove comentários -- e /* */ para análise do comando real."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def validate_query(query: str) -> str | None:
    """Retorna None se válida, ou mensagem de erro."""
    stripped = _strip_sql_comments(query)
    if not stripped:
        return "A consulta está vazia."

    if _FORBIDDEN_KEYWORDS.search(stripped):
        return "Apenas consultas SELECT são permitidas no Playground."

    if not _ALLOWED_START.search(stripped):
        return "A consulta deve iniciar com SELECT ou WITH."

    parts = [p.strip() for p in stripped.split(";") if p.strip()]
    if len(parts) > 1:
        return "Apenas uma instrução SQL por vez é permitida."

    return None


class PlaygroundService:
    """Execução de consultas SELECT e introspecção de schema com cache."""

    # ── Schema cache ─────────────────────────────────────────────────────────

    async def get_schema(
        self,
        db: AsyncSession,
        connection_id: UUID,
        force: bool = False,
    ) -> SchemaResponse:
        conn = await connection_service.get(db, connection_id)
        if conn is None:
            raise ValueError("Conexão não encontrada.")

        # 1. Verificar cache (a menos que force=True)
        if not force:
            cached = await self._load_cache(db, connection_id)
            if cached is not None:
                return cached

        # 2. Buscar schema diretamente no banco externo
        if conn.type == ConnectionType.firebird.value:
            worker = self._schema_firebird_sync
            args: tuple = (conn,)
            kwargs: dict = {}
        else:
            url = connection_service.build_connection_string(conn)
            worker = self._schema_sync  # type: ignore[assignment]
            args = (url,)
            kwargs = {
                "include_schemas": conn.include_schemas or [],
                "conn_type": conn.type,
                # Para Oracle o schema padrão é o próprio usuário conectado
                "default_schema": conn.username.upper()
                if conn.type == ConnectionType.oracle.value
                else None,
            }

        try:
            result: SchemaResponse = await asyncio.wait_for(
                asyncio.to_thread(worker, *args, **kwargs),
                timeout=_QUERY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise ValueError("Timeout ao carregar schema.")

        # 3. Persistir cache
        await self._save_cache(db, connection_id, result)
        await db.commit()

        return result

    async def _load_cache(
        self,
        db: AsyncSession,
        connection_id: UUID,
    ) -> SchemaResponse | None:
        """Retorna o schema cacheado se existir e não estiver expirado (< 3 meses)."""
        stmt = sa.select(ConnectionSchema).where(
            ConnectionSchema.connection_id == connection_id
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None

        age_limit = datetime.now(tz=timezone.utc) - _SCHEMA_CACHE_MAX_AGE
        if row.updated_at.replace(tzinfo=timezone.utc) < age_limit:
            # Cache expirado — deixa buscar fresco
            return None

        schema = SchemaResponse.model_validate(row.schema_data)
        schema.updated_at = row.updated_at
        schema.is_cached = True
        return schema

    async def _save_cache(
        self,
        db: AsyncSession,
        connection_id: UUID,
        schema: SchemaResponse,
    ) -> None:
        """Cria ou atualiza o cache do schema para a conexão."""
        data = schema.model_dump(exclude={"updated_at", "is_cached"})

        stmt = sa.select(ConnectionSchema).where(
            ConnectionSchema.connection_id == connection_id
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()

        now = datetime.now(tz=timezone.utc)
        if existing is None:
            db.add(
                ConnectionSchema(
                    connection_id=connection_id,
                    schema_data=data,
                    updated_at=now,
                )
            )
        else:
            existing.schema_data = data
            existing.updated_at = now

        schema.updated_at = now
        schema.is_cached = False

    # ── Query execution ───────────────────────────────────────────────────────

    async def execute_query(
        self,
        db: AsyncSession,
        connection_id: UUID,
        query: str,
        max_rows: int = 500,
    ) -> PlaygroundQueryResponse:
        conn = await connection_service.get(db, connection_id)
        if conn is None:
            raise ValueError("Conexão não encontrada.")

        error = validate_query(query)
        if error:
            raise ValueError(error)

        if conn.type == ConnectionType.firebird.value:
            worker = self._execute_firebird_sync
            args = (conn, query, max_rows)
        else:
            url = connection_service.build_connection_string(conn)
            worker = self._execute_sync  # type: ignore[assignment]
            args = (url, query, max_rows)  # type: ignore[assignment]

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(worker, *args),
                timeout=_QUERY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise ValueError(
                f"Timeout: a consulta excedeu {int(_QUERY_TIMEOUT_SECONDS)}s."
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(str(exc)) from exc

        return result

    @staticmethod
    def _execute_sync(
        url: str,
        query: str,
        max_rows: int,
    ) -> PlaygroundQueryResponse:
        engine: sa.Engine | None = None
        try:
            engine = sa.create_engine(
                url, pool_pre_ping=False, pool_size=1, max_overflow=0
            )
            start = time.perf_counter_ns()
            with engine.connect() as db_conn:
                result = db_conn.execute(sa.text(query))
                columns = list(result.keys())
                rows_raw = result.fetchmany(max_rows + 1)

            elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
            truncated = len(rows_raw) > max_rows
            rows = [list(_serialize_row(r)) for r in rows_raw[:max_rows]]

            return PlaygroundQueryResponse(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                execution_time_ms=elapsed_ms,
            )
        finally:
            if engine is not None:
                engine.dispose()

    @staticmethod
    def _execute_firebird_sync(
        conn: Connection,
        query: str,
        max_rows: int,
    ) -> PlaygroundQueryResponse:
        from app.services.firebird_client import connect_firebird

        config: dict[str, Any] = {
            "host": conn.host,
            "port": conn.port,
            "database": conn.database,
            "username": conn.username,
        }
        if conn.extra_params:
            config.update(conn.extra_params)

        secret = {"password": conn.password}
        fb_conn = None
        try:
            fb_conn = connect_firebird(config=config, secret=secret)
            cur = fb_conn.cursor()

            start = time.perf_counter_ns()
            cur.execute(query)

            columns = [desc[0] for desc in cur.description] if cur.description else []

            # Busca linha a linha para isolar erros de encoding por linha
            rows_raw: list = []
            while len(rows_raw) <= max_rows:
                try:
                    batch = cur.fetchmany(min(100, max_rows + 1 - len(rows_raw)))
                except UnicodeDecodeError:
                    # Fallback: busca 1 linha por vez e substitui caracteres inválidos
                    batch = _fetch_with_encoding_fallback(cur, 1)
                if not batch:
                    break
                rows_raw.extend(batch)

            elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
            cur.close()

            truncated = len(rows_raw) > max_rows
            rows = [list(_serialize_row(r)) for r in rows_raw[:max_rows]]

            return PlaygroundQueryResponse(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                execution_time_ms=elapsed_ms,
            )
        finally:
            if fb_conn is not None:
                try:
                    fb_conn.close()
                except Exception:
                    pass

    @staticmethod
    def _schema_sync(
        url: str,
        include_schemas: list[str] | None = None,
        conn_type: str = "",
        default_schema: str | None = None,
    ) -> SchemaResponse:
        is_oracle = conn_type == ConnectionType.oracle.value
        engine: sa.Engine | None = None
        try:
            engine = sa.create_engine(
                url, pool_pre_ping=False, pool_size=1, max_overflow=0
            )
            inspector = sa.inspect(engine)
            tables: list[SchemaTable] = []

            def _collect(schema: str | None) -> None:
                # Oracle: o SQLAlchemy normaliza nomes para lowercase — revertemos para uppercase
                display_schema = schema if schema is not None else default_schema
                for raw_name in sorted(inspector.get_table_names(schema=schema)):
                    display_name = raw_name.upper() if is_oracle else raw_name
                    cols = []
                    for col in inspector.get_columns(raw_name, schema=schema):
                        col_name = col["name"].upper() if is_oracle else col["name"]
                        cols.append(
                            SchemaColumn(
                                name=col_name,
                                type=str(col["type"]),
                                nullable=col.get("nullable", True),
                            )
                        )
                    tables.append(SchemaTable(name=display_name, schema=display_schema, columns=cols))

            # Schema padrão (usuário conectado)
            _collect(None)
            # Schemas adicionais — sempre em maiúsculo
            for extra in (include_schemas or []):
                normalized = extra.strip().upper()
                if normalized:
                    _collect(normalized)

            return SchemaResponse(tables=tables)
        finally:
            if engine is not None:
                engine.dispose()

    @staticmethod
    def _schema_firebird_sync(conn: Connection) -> SchemaResponse:
        from app.services.firebird_client import connect_firebird

        config: dict[str, Any] = {
            "host": conn.host,
            "port": conn.port,
            "database": conn.database,
            "username": conn.username,
        }
        if conn.extra_params:
            config.update(conn.extra_params)

        secret = {"password": conn.password}
        fb_conn = None
        try:
            fb_conn = connect_firebird(config=config, secret=secret)
            cur = fb_conn.cursor()

            cur.execute(
                "SELECT TRIM(rdb$relation_name) FROM rdb$relations "
                "WHERE rdb$system_flag = 0 AND rdb$view_blr IS NULL "
                "ORDER BY rdb$relation_name"
            )
            table_names = [row[0] for row in cur.fetchall()]

            tables: list[SchemaTable] = []
            for table_name in table_names:
                cur.execute(
                    "SELECT TRIM(rf.rdb$field_name), "
                    "CASE f.rdb$field_type "
                    "  WHEN 7 THEN 'SMALLINT' "
                    "  WHEN 8 THEN 'INTEGER' "
                    "  WHEN 10 THEN 'FLOAT' "
                    "  WHEN 12 THEN 'DATE' "
                    "  WHEN 13 THEN 'TIME' "
                    "  WHEN 14 THEN 'CHAR' "
                    "  WHEN 16 THEN 'BIGINT' "
                    "  WHEN 23 THEN 'BOOLEAN' "
                    "  WHEN 27 THEN 'DOUBLE PRECISION' "
                    "  WHEN 35 THEN 'TIMESTAMP' "
                    "  WHEN 37 THEN 'VARCHAR' "
                    "  WHEN 261 THEN 'BLOB' "
                    "  ELSE 'OTHER(' || f.rdb$field_type || ')' "
                    "END, "
                    "rf.rdb$null_flag "
                    "FROM rdb$relation_fields rf "
                    "JOIN rdb$fields f ON rf.rdb$field_source = f.rdb$field_name "
                    "WHERE rf.rdb$relation_name = ? "
                    "ORDER BY rf.rdb$field_position",
                    (table_name,),
                )
                cols = [
                    SchemaColumn(
                        name=row[0].strip() if row[0] else row[0],
                        type=row[1].strip() if row[1] else "UNKNOWN",
                        nullable=row[2] is None,
                    )
                    for row in cur.fetchall()
                ]
                tables.append(
                    SchemaTable(
                        name=table_name.strip() if table_name else table_name,
                        columns=cols,
                    )
                )

            cur.close()
            return SchemaResponse(tables=tables)
        finally:
            if fb_conn is not None:
                try:
                    fb_conn.close()
                except Exception:
                    pass


def _fetch_with_encoding_fallback(cur: Any, count: int) -> list:
    """Busca linhas do cursor substituindo bytes indecodificáveis por '?'."""
    rows = []
    for _ in range(count):
        try:
            row = cur.fetchone()
            if row is None:
                break
            rows.append(row)
        except UnicodeDecodeError:
            # Linha com dados irrecuperáveis — insere marcador
            rows.append(["[encoding error]"] * (len(cur.description) if cur.description else 1))
    return rows


def _decode_str(val: Any) -> str:
    """Decodifica bytes ou strings com fallback para WIN1252/Latin-1."""
    if isinstance(val, bytes):
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return val.decode(enc)
            except (UnicodeDecodeError, ValueError):
                continue
        return val.decode("latin-1", errors="replace")
    if isinstance(val, str):
        # Tenta recodificar caso o driver tenha feito decode errado
        try:
            return val.encode("latin-1").decode("cp1252")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return val
    return str(val)


def _serialize_row(row: Any) -> list:
    """Converte valores da row para tipos JSON-serializáveis."""
    result = []
    items = row if isinstance(row, (list, tuple)) else list(row)
    for val in items:
        if val is None:
            result.append(None)
        elif isinstance(val, bool):
            result.append(val)
        elif isinstance(val, (int, float)):
            result.append(val)
        elif isinstance(val, str):
            result.append(_decode_str(val))
        elif isinstance(val, bytes):
            result.append(_decode_str(val))
        else:
            result.append(str(val))
    return result


playground_service = PlaygroundService()
