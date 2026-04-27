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
    ForeignKey,
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
                "workspace_id": conn.workspace_id,
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
            args = (url, query, max_rows, conn.type, conn.workspace_id)  # type: ignore[assignment]

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
        conn_type: str,
        workspace_id: UUID | None,
    ) -> PlaygroundQueryResponse:
        from app.services.db.engine_cache import get_engine_from_url

        # Engine compartilhado entre execucoes do mesmo playground/conexao —
        # nao chamar dispose() aqui.
        engine = get_engine_from_url(workspace_id, url, conn_type)
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
        workspace_id: UUID | None = None,
    ) -> SchemaResponse:
        from app.services.db.engine_cache import get_engine_from_url

        is_oracle = conn_type == ConnectionType.oracle.value
        engine: sa.Engine | None = None
        try:
            engine = get_engine_from_url(workspace_id, url, conn_type or "unknown")
            inspector = sa.inspect(engine)
            tables: list[SchemaTable] = []

            def _norm(name: str | None) -> str | None:
                if name is None:
                    return None
                return name.upper() if is_oracle else name

            def _collect(schema: str | None) -> None:
                display_schema = schema if schema is not None else default_schema
                for raw_name in sorted(inspector.get_table_names(schema=schema)):
                    display_name = _norm(raw_name) or raw_name

                    # Primary key
                    try:
                        pk_info = inspector.get_pk_constraint(raw_name, schema=schema) or {}
                        pk_cols = {
                            (_norm(c) or c)
                            for c in (pk_info.get("constrained_columns") or [])
                        }
                    except Exception:
                        pk_cols = set()

                    # Columns (com flag de PK)
                    cols = []
                    for col in inspector.get_columns(raw_name, schema=schema):
                        col_name = _norm(col["name"]) or col["name"]
                        cols.append(
                            SchemaColumn(
                                name=col_name,
                                type=str(col["type"]),
                                nullable=col.get("nullable", True),
                                primary_key=col_name in pk_cols,
                            )
                        )

                    # Foreign keys
                    fks: list[ForeignKey] = []
                    try:
                        for fk in inspector.get_foreign_keys(raw_name, schema=schema) or []:
                            ref_table = fk.get("referred_table")
                            if not ref_table:
                                continue
                            fks.append(
                                ForeignKey(
                                    columns=[
                                        _norm(c) or c
                                        for c in (fk.get("constrained_columns") or [])
                                    ],
                                    ref_table=_norm(ref_table) or ref_table,
                                    ref_columns=[
                                        _norm(c) or c
                                        for c in (fk.get("referred_columns") or [])
                                    ],
                                    ref_schema=_norm(fk.get("referred_schema")),
                                )
                            )
                    except Exception:
                        pass

                    tables.append(
                        SchemaTable(
                            name=display_name,
                            schema_name=display_schema,
                            columns=cols,
                            foreign_keys=fks,
                        )
                    )

            # Schema padrão (usuário conectado)
            _collect(None)
            # Schemas adicionais — sempre em maiúsculo
            for extra in (include_schemas or []):
                normalized = extra.strip().upper()
                if normalized:
                    _collect(normalized)

            # Row counts (best-effort, dialect-specific)
            try:
                _populate_row_counts(engine, tables, conn_type)
            except Exception:
                pass

            return SchemaResponse(tables=tables)
        finally:
            # Engine compartilhado pelo engine_cache — nao chamar dispose().
            pass

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

            # Primary keys: table -> set(col)
            pks_map: dict[str, set[str]] = {}
            try:
                cur.execute(
                    "SELECT TRIM(rc.rdb$relation_name), TRIM(sg.rdb$field_name) "
                    "FROM rdb$relation_constraints rc "
                    "JOIN rdb$index_segments sg ON sg.rdb$index_name = rc.rdb$index_name "
                    "WHERE rc.rdb$constraint_type = 'PRIMARY KEY'"
                )
                for tname, col in cur.fetchall():
                    pks_map.setdefault(tname, set()).add(col)
            except Exception:
                pass

            # Foreign keys: table -> list of FK
            fks_map: dict[str, list[ForeignKey]] = {}
            try:
                cur.execute(
                    "SELECT "
                    "  TRIM(rc.rdb$relation_name), "
                    "  TRIM(rc.rdb$constraint_name), "
                    "  TRIM(sg.rdb$field_name), "
                    "  TRIM(rc2.rdb$relation_name) AS ref_table, "
                    "  TRIM(sg2.rdb$field_name) AS ref_col, "
                    "  sg.rdb$field_position "
                    "FROM rdb$relation_constraints rc "
                    "JOIN rdb$ref_constraints refc ON refc.rdb$constraint_name = rc.rdb$constraint_name "
                    "JOIN rdb$relation_constraints rc2 ON rc2.rdb$constraint_name = refc.rdb$const_name_uq "
                    "JOIN rdb$index_segments sg ON sg.rdb$index_name = rc.rdb$index_name "
                    "JOIN rdb$index_segments sg2 ON sg2.rdb$index_name = rc2.rdb$index_name "
                    "  AND sg2.rdb$field_position = sg.rdb$field_position "
                    "WHERE rc.rdb$constraint_type = 'FOREIGN KEY' "
                    "ORDER BY rc.rdb$relation_name, rc.rdb$constraint_name, sg.rdb$field_position"
                )
                # agrupa por (tabela, constraint)
                grouped: dict[tuple[str, str], dict[str, Any]] = {}
                for tname, cname, col, ref_t, ref_c, _pos in cur.fetchall():
                    key = (tname, cname)
                    entry = grouped.setdefault(
                        key, {"ref_table": ref_t, "columns": [], "ref_columns": []}
                    )
                    entry["columns"].append(col)
                    entry["ref_columns"].append(ref_c)
                for (tname, _cname), entry in grouped.items():
                    fks_map.setdefault(tname, []).append(
                        ForeignKey(
                            columns=entry["columns"],
                            ref_table=entry["ref_table"],
                            ref_columns=entry["ref_columns"],
                        )
                    )
            except Exception:
                pass

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
                pk_cols = pks_map.get(table_name, set())
                cols = [
                    SchemaColumn(
                        name=row[0].strip() if row[0] else row[0],
                        type=row[1].strip() if row[1] else "UNKNOWN",
                        nullable=row[2] is None,
                        primary_key=(row[0] and row[0].strip() in pk_cols),
                    )
                    for row in cur.fetchall()
                ]
                table_display = table_name.strip() if table_name else table_name
                tables.append(
                    SchemaTable(
                        name=table_display,
                        columns=cols,
                        foreign_keys=fks_map.get(table_name, []),
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


def _populate_row_counts(
    engine: sa.Engine, tables: list[SchemaTable], conn_type: str
) -> None:
    """Preenche row_count_estimate usando estatísticas nativas (best-effort)."""
    if not tables:
        return

    if conn_type == ConnectionType.postgresql.value:
        sql = (
            "SELECT schemaname, relname, n_live_tup "
            "FROM pg_stat_user_tables"
        )
        with engine.connect() as db_conn:
            rows = db_conn.execute(sa.text(sql)).fetchall()
        counts = {(r[0], r[1]): int(r[2] or 0) for r in rows}
        for t in tables:
            key = (t.schema_name, t.name) if t.schema_name else None
            if key and key in counts:
                t.row_count_estimate = counts[key]
            else:
                # fallback: match só por nome (schema público)
                for (_, name), val in counts.items():
                    if name == t.name:
                        t.row_count_estimate = val
                        break
        return

    if conn_type == ConnectionType.oracle.value:
        sql = (
            "SELECT owner, table_name, num_rows "
            "FROM all_tables "
            "WHERE num_rows IS NOT NULL"
        )
        with engine.connect() as db_conn:
            rows = db_conn.execute(sa.text(sql)).fetchall()
        counts = {(str(r[0]).upper(), str(r[1]).upper()): int(r[2]) for r in rows}
        for t in tables:
            schema = (t.schema_name or "").upper()
            key = (schema, t.name.upper())
            if key in counts:
                t.row_count_estimate = counts[key]
        return

    if conn_type == ConnectionType.mysql.value:
        sql = (
            "SELECT table_schema, table_name, table_rows "
            "FROM information_schema.tables "
            "WHERE table_schema NOT IN "
            "('information_schema','mysql','performance_schema','sys')"
        )
        with engine.connect() as db_conn:
            rows = db_conn.execute(sa.text(sql)).fetchall()
        counts = {(r[0], r[1]): int(r[2] or 0) for r in rows}
        for t in tables:
            for (_, name), val in counts.items():
                if name == t.name:
                    t.row_count_estimate = val
                    break
        return

    if conn_type == ConnectionType.sqlserver.value:
        sql = (
            "SELECT s.name, t.name, SUM(p.rows) AS rowcnt "
            "FROM sys.tables t "
            "JOIN sys.schemas s ON s.schema_id = t.schema_id "
            "JOIN sys.partitions p ON p.object_id = t.object_id "
            "WHERE p.index_id IN (0, 1) "
            "GROUP BY s.name, t.name"
        )
        with engine.connect() as db_conn:
            rows = db_conn.execute(sa.text(sql)).fetchall()
        counts = {(r[0], r[1]): int(r[2] or 0) for r in rows}
        for t in tables:
            for (_, name), val in counts.items():
                if name == t.name:
                    t.row_count_estimate = val
                    break


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
