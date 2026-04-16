"""
Servico unificado de carga de dados.

Centraliza toda escrita em bancos de destino (INSERT, TRUNCATE, MERGE),
com introspeccao automatica de tipos, cast inteligente e diagnostico de
erros por linha.

Estrategia de carga por tipo de destino:
  - Oracle / Firebird: SQLAlchemy direto (dlt tem bug ORA-00932 com CLOB).
  - Demais (PostgreSQL, MySQL, MSSQL): dlt nativo.

Usado tanto pelo modo teste (workflow_test_service) quanto pelo modo
producao (workflow/nodes/load_node).
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Literal
from uuid import uuid4

import dlt
import sqlalchemy as sa

from app.services.connection_service import ConnectionService, connection_service

# ─── Constantes de tipo para introspeccao ────────────────────────────────────

_NUMERIC_DB_TYPES = frozenset({
    "NUMBER", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL",
    "INTEGER", "INT", "SMALLINT", "BIGINT", "DOUBLE_PRECISION",
    "BINARY_FLOAT", "BINARY_DOUBLE", "MONEY", "TINYINT",
})

_INT_DB_TYPES = frozenset({
    "INTEGER", "INT", "SMALLINT", "BIGINT", "TINYINT",
})

_DATE_DB_TYPES = frozenset({
    "DATE", "DATETIME", "TIMESTAMP", "DATETIME2", "SMALLDATETIME",
    "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "TIMESTAMP_TZ",
})

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
)

_TABLE_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_.]*$')
_COLUMN_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


# ─── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class RejectedRow:
    """Uma linha que falhou na insercao."""
    row_number: int
    error: str
    column: str | None = None
    value: Any = None
    expected_type: str | None = None


@dataclass
class LoadResult:
    """Resultado de uma operacao de carga."""
    status: str = "success"
    rows_received: int = 0
    rows_written: int = 0
    duplicates_removed: int = 0
    target_table: str = ""
    dest_count_before: int = -1
    dest_count_after: int = -1
    column_types: dict[str, str] = field(default_factory=dict)
    cast_summary: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    batches: int = 0
    rejected_rows: list[RejectedRow] = field(default_factory=list)
    cast_warnings: list[str] = field(default_factory=list)
    loader: str = "sqlalchemy"
    write_disposition: str = "append"
    columns_mapped: int = 0
    unique_columns: list[str] = field(default_factory=list)
    duplicate_sample: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "rows_received": self.rows_received,
            "rows_written": self.rows_written,
            "target_table": self.target_table,
            "write_disposition": self.write_disposition,
        }
        if self.duplicates_removed > 0:
            d["duplicates_removed"] = self.duplicates_removed
        if self.duplicate_sample:
            d["duplicate_sample"] = self.duplicate_sample[:5]
        if self.unique_columns:
            d["unique_columns"] = self.unique_columns
        if self.dest_count_before >= 0:
            d["dest_count_before"] = self.dest_count_before
        if self.dest_count_after >= 0:
            d["dest_count_after"] = self.dest_count_after
        if self.column_types:
            d["column_types"] = self.column_types
        if self.cast_summary:
            d["cast_summary"] = self.cast_summary
        if self.duration_ms:
            d["duration_ms"] = self.duration_ms
        if self.batches:
            d["batches"] = self.batches
        if self.rejected_rows:
            d["rejected_count"] = len(self.rejected_rows)
            d["rejected_rows"] = [
                {k: v for k, v in rr.__dict__.items() if v is not None}
                for rr in self.rejected_rows[:10]
            ]
        if self.cast_warnings:
            d["cast_warnings"] = self.cast_warnings[:5]
        if self.columns_mapped:
            d["columns_mapped"] = self.columns_mapped
        d["loader"] = self.loader
        return d


@dataclass
class TruncateResult:
    """Resultado de uma operacao de truncate/delete."""
    status: str = "success"
    target_table: str = ""
    mode: str = "truncate"
    rows_affected: int = -1

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "target_table": self.target_table,
            "mode": self.mode,
            "rows_affected": self.rows_affected,
        }
        if self.rows_affected >= 0:
            d["message"] = (
                f"Tabela '{self.target_table}' limpa com sucesso. "
                f"{self.rows_affected} registros removidos."
            )
        else:
            d["message"] = f"Tabela '{self.target_table}' limpa com sucesso."
        return d


# ─── Servico ─────────────────────────────────────────────────────────────────

class LoadService:
    """Servico unificado de escrita em bancos de destino."""

    def __init__(self, conn_svc: ConnectionService | None = None) -> None:
        self._conn_svc = conn_svc or connection_service

    # ── API publica ──────────────────────────────────────────────────────────

    def insert(
        self,
        connection_string: str,
        conn_type: str,
        target_table: str,
        rows: list[dict[str, Any]],
        *,
        column_mapping: list[dict[str, str]] | None = None,
        write_disposition: str = "append",
        merge_key: list[str] | None = None,
        batch_size: int = 1000,
        unique_columns: list[str] | None = None,
    ) -> LoadResult:
        """
        Insere dados na tabela destino.

        Fluxo:
        1. Valida parametros
        2. Introspeccao da tabela destino (tipos das colunas)
        3. Aplica column_mapping (se fornecido)
        4. Cast de tipos (string->number, string->date, etc.)
        5. Dedup: remove duplicatas do input baseado em unique_columns
        6. COUNT(*) antes da insercao (para auditoria)
        7. Escolhe estrategia: dlt pipeline ou SQLAlchemy direto
        8. Insere em batches com tracking de progresso
        9. COUNT(*) apos insercao (para verificacao)
        10. Retorna LoadResult com metricas detalhadas
        """
        _validate_table_name(target_table)

        rows_received = len(rows)

        if not rows:
            return LoadResult(
                status="skipped",
                rows_received=0,
                target_table=target_table,
                write_disposition=write_disposition,
            )

        if write_disposition == "merge" and not merge_key:
            raise ValueError(
                f"write_disposition='merge' requer merge_key com ao menos uma coluna. "
                f"Tabela de destino: {target_table}"
            )

        engine = _create_engine(connection_string, conn_type)
        try:
            # Introspeccao dos tipos da tabela destino
            col_type_map = _introspect_columns(engine, target_table)

            # Aplica column_mapping e cast
            mapped_rows, cast_warnings, cast_summary = _map_and_cast(
                rows, column_mapping, col_type_map
            )

            if not mapped_rows:
                return LoadResult(
                    status="skipped",
                    rows_received=rows_received,
                    target_table=target_table,
                    write_disposition=write_disposition,
                )

            # Resolve colunas efetivas
            if column_mapping:
                valid_maps = [m for m in column_mapping if m.get("source") and m.get("target")]
                cols = [m["target"] for m in valid_maps]
            else:
                cols = list(mapped_rows[0].keys())

            for col in cols:
                if not _COLUMN_NAME_RE.match(col):
                    raise ValueError(f"Nome de coluna invalido para escrita: '{col}'")

            # ── Dedup baseado em unique_columns ─────────────────────────────
            duplicates_removed = 0
            duplicate_sample: list[dict[str, Any]] = []
            effective_unique = unique_columns or []

            if effective_unique:
                # Resolve nomes: unique_columns pode vir como nomes de
                # destino (target). Garante que existem nas mapped_rows.
                available_cols = set(mapped_rows[0].keys()) if mapped_rows else set()
                valid_unique = [c for c in effective_unique if c in available_cols]

                if valid_unique:
                    seen: set[tuple] = set()
                    deduped: list[dict[str, Any]] = []
                    for row in mapped_rows:
                        key = tuple(row.get(c) for c in valid_unique)
                        if key in seen:
                            duplicates_removed += 1
                            if len(duplicate_sample) < 5:
                                duplicate_sample.append(
                                    {c: row.get(c) for c in valid_unique}
                                )
                            continue
                        seen.add(key)
                        deduped.append(row)
                    mapped_rows = deduped

            if not mapped_rows:
                return LoadResult(
                    status="skipped",
                    rows_received=rows_received,
                    duplicates_removed=duplicates_removed,
                    target_table=target_table,
                    write_disposition=write_disposition,
                    unique_columns=effective_unique,
                    duplicate_sample=duplicate_sample,
                )

            # ── COUNT(*) antes da insercao ──────────────────────────────────
            count_before = _count_rows(engine, target_table)

            # Decide estrategia de carga
            loader = _choose_loader(connection_string)

            if loader == "dlt":
                result = _insert_via_dlt(
                    connection_string=connection_string,
                    target_table=target_table,
                    rows=mapped_rows,
                    write_disposition=write_disposition,
                    merge_key=merge_key,
                    batch_size=batch_size,
                )
            else:
                result = _insert_via_sqlalchemy(
                    engine=engine,
                    target_table=target_table,
                    rows=mapped_rows,
                    cols=cols,
                    write_disposition=write_disposition,
                    merge_key=merge_key or [],
                    batch_size=batch_size,
                )

            # ── COUNT(*) apos insercao ──────────────────────────────────────
            count_after = _count_rows(engine, target_table)

            # Enriquece resultado
            result.rows_received = rows_received
            result.duplicates_removed = duplicates_removed
            result.duplicate_sample = duplicate_sample
            result.unique_columns = effective_unique
            result.dest_count_before = count_before
            result.dest_count_after = count_after
            result.target_table = target_table
            result.write_disposition = write_disposition
            result.cast_warnings = cast_warnings
            result.cast_summary = cast_summary
            result.column_types = {
                col: col_type_map.get(col.upper(), "?") for col in cols
            }
            if column_mapping:
                result.columns_mapped = len(
                    [m for m in column_mapping if m.get("source") and m.get("target")]
                )
            return result

        finally:
            engine.dispose()

    def truncate(
        self,
        connection_string: str,
        conn_type: str,
        target_table: str,
        *,
        mode: str = "truncate",
        where_clause: str | None = None,
    ) -> TruncateResult:
        """Limpa (TRUNCATE ou DELETE) uma tabela de destino."""
        _validate_table_name(target_table)

        engine = _create_engine(connection_string, conn_type)
        try:
            with engine.begin() as db_conn:
                if mode == "delete":
                    sql = f"DELETE FROM {target_table}"
                    if where_clause:
                        sql += f" WHERE {where_clause}"
                    result = db_conn.execute(sa.text(sql))
                    rows_affected = result.rowcount
                else:
                    dialect = engine.dialect.name.lower()
                    if dialect == "sqlite":
                        db_conn.execute(sa.text(f"DELETE FROM {target_table}"))
                    else:
                        db_conn.execute(sa.text(f"TRUNCATE TABLE {target_table}"))
                    rows_affected = -1

            return TruncateResult(
                status="success",
                target_table=target_table,
                mode=mode,
                rows_affected=rows_affected,
            )
        finally:
            engine.dispose()

    def insert_from_source(
        self,
        source_connection: str,
        destination_connection: str,
        table_name: str,
        target_table: str,
        *,
        query: str | None = None,
        chunk_size: int = 1000,
        write_disposition: str = "append",
        merge_key: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Carrega dados de uma fonte SQL para um destino.

        Delega para dlt ou SQLAlchemy conforme o tipo de destino.
        Usado pelo modo producao onde a fonte e DuckDB staging.
        """
        cs = destination_connection.lower()

        if cs.startswith(("oracle", "firebird")):
            return _load_source_via_sqlalchemy(
                source_connection=source_connection,
                destination_connection=destination_connection,
                target_table=target_table,
                query=query or f"SELECT * FROM {table_name}",
                chunk_size=chunk_size,
                write_disposition=write_disposition,
                merge_key=merge_key or [],
            )

        return _load_source_via_dlt(
            source_connection=source_connection,
            destination_connection=destination_connection,
            table_name=table_name,
            target_table=target_table,
            query=query,
            chunk_size=chunk_size,
            write_disposition=write_disposition,
            merge_key=merge_key or [],
        )


# ─── Type casting centralizado ───────────────────────────────────────────────

def cast_for_db(val: Any, db_type: str) -> Any:
    """
    Converte um valor Python para o tipo esperado pela coluna do banco.

    Resolve o problema classico de strings numericas ('0.0') sendo enviadas
    para colunas NUMBER em Oracle/Postgres, causando ORA-01722 e similares.
    """
    if val is None:
        return None
    if not db_type:
        return val

    # ── Numerico ──
    if db_type in _NUMERIC_DB_TYPES:
        if isinstance(val, (int, float, Decimal)):
            if db_type in _INT_DB_TYPES:
                return int(val)
            return val
        if isinstance(val, str):
            s = val.strip()
            if s == "":
                return None
            if db_type in _INT_DB_TYPES:
                return int(float(s))
            try:
                return float(s)
            except ValueError:
                return val  # Deixa o DB rejeitar com mensagem clara
        return val

    # ── Data/hora ──
    if db_type in _DATE_DB_TYPES:
        if isinstance(val, (datetime, date)):
            return val
        if isinstance(val, str):
            s = val.strip()
            if s == "":
                return None
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            # Fallback: ISO parse
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                return val
        return val

    # ── String (VARCHAR, CHAR, CLOB, TEXT, NVARCHAR) — garante str ──
    if isinstance(val, (int, float, Decimal)):
        return str(val)

    return val


# ─── Funcoes privadas ────────────────────────────────────────────────────────

def _validate_table_name(name: str) -> None:
    if not name or not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Nome de tabela invalido: '{name}'")


def _create_engine(connection_string: str, conn_type: str) -> sa.Engine:
    connect_args: dict[str, Any] = {}
    if conn_type == "sqlserver":
        connect_args["TrustServerCertificate"] = "yes"

    return sa.create_engine(
        connection_string,
        pool_pre_ping=False,
        pool_size=1,
        max_overflow=0,
        connect_args=connect_args,
    )


def _count_rows(engine: sa.Engine, target_table: str) -> int:
    """Conta registros na tabela destino para auditoria pre/pos insercao."""
    try:
        with engine.connect() as conn:
            result = conn.execute(sa.text(f"SELECT COUNT(*) FROM {target_table}"))
            return result.scalar() or 0
    except Exception:
        return -1


def _choose_loader(connection_string: str) -> Literal["dlt", "sqlalchemy"]:
    """
    Oracle e Firebird -> sqlalchemy (bug ORA-00932 com CLOB).
    Tudo mais -> dlt.
    """
    cs = connection_string.lower()
    if cs.startswith(("oracle", "firebird")):
        return "sqlalchemy"
    return "dlt"


def _introspect_columns(engine: sa.Engine, target_table: str) -> dict[str, str]:
    """
    Descobre os tipos das colunas da tabela destino via Inspector.

    Retorna mapa COLUNA_UPPER -> TIPO_UPPER.
    O resultado e cacheavel durante a execucao (1 inspect por tabela).
    """
    col_type_map: dict[str, str] = {}
    try:
        inspector = sa.inspect(engine)
        parts = target_table.split(".", 1)
        if len(parts) == 2:
            tbl_schema, tbl_name = parts
        else:
            tbl_schema, tbl_name = None, parts[0]

        db_columns = inspector.get_columns(tbl_name, schema=tbl_schema)
        for c in db_columns:
            type_obj = c.get("type")
            type_name = type(type_obj).__name__.upper() if type_obj else ""
            col_type_map[c["name"].upper()] = type_name
    except Exception:
        pass
    return col_type_map


def _map_and_cast(
    rows: list[dict[str, Any]],
    column_mapping: list[dict[str, str]] | None,
    col_type_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str], dict[str, int]]:
    """
    Aplica column_mapping e cast de tipos.

    Retorna: (mapped_rows, cast_warnings, cast_summary)
    """
    valid_maps = None
    if column_mapping:
        valid_maps = [m for m in column_mapping if m.get("source") and m.get("target")]
        if not valid_maps:
            raise ValueError("Nenhum mapeamento de colunas valido encontrado.")

    mapped_rows: list[dict[str, Any]] = []
    cast_warnings: list[str] = []
    cast_summary: dict[str, int] = {}

    for row_idx, row in enumerate(rows):
        mapped_row: dict[str, Any] = {}

        if valid_maps:
            for m in valid_maps:
                src = m["source"]
                tgt = m["target"]
                val = row.get(src)
                db_type = col_type_map.get(tgt.upper(), "")

                try:
                    new_val = cast_for_db(val, db_type)
                    if new_val is not val and val is not None:
                        _track_cast(cast_summary, val, new_val, db_type)
                except (ValueError, TypeError) as cast_exc:
                    cast_warnings.append(
                        f"Linha {row_idx + 1}, coluna '{tgt}': "
                        f"valor '{val}' ({type(val).__name__}) -> {db_type}: {cast_exc}"
                    )
                    new_val = val

                mapped_row[tgt] = new_val
        else:
            for key, val in row.items():
                db_type = col_type_map.get(key.upper(), "")
                try:
                    new_val = cast_for_db(val, db_type)
                    if new_val is not val and val is not None:
                        _track_cast(cast_summary, val, new_val, db_type)
                except (ValueError, TypeError):
                    new_val = val
                mapped_row[key] = new_val

        mapped_rows.append(mapped_row)

    return mapped_rows, cast_warnings, cast_summary


def _track_cast(summary: dict[str, int], original: Any, converted: Any, db_type: str) -> None:
    """Rastreia conversoes de tipo para o cast_summary."""
    if converted is None and original is not None:
        summary["null_coerced"] = summary.get("null_coerced", 0) + 1
    elif db_type in _NUMERIC_DB_TYPES and isinstance(original, str):
        summary["string_to_number"] = summary.get("string_to_number", 0) + 1
    elif db_type in _DATE_DB_TYPES and isinstance(original, str):
        summary["string_to_date"] = summary.get("string_to_date", 0) + 1
    elif isinstance(original, (int, float, Decimal)) and isinstance(converted, str):
        summary["number_to_string"] = summary.get("number_to_string", 0) + 1


# ─── Insercao via SQLAlchemy (Oracle/Firebird + fallback) ────────────────────

def _insert_via_sqlalchemy(
    engine: sa.Engine,
    target_table: str,
    rows: list[dict[str, Any]],
    cols: list[str],
    write_disposition: str,
    merge_key: list[str],
    batch_size: int,
) -> LoadResult:
    """Insere dados usando SQLAlchemy direto com diagnostico de erros.

    Usa SAVEPOINT por batch para evitar que falhas parciais gerem linhas
    fantasma (Oracle nao invalida a transacao em caso de erro, entao as
    linhas inseridas antes do erro permaneciam e o fallback linha-a-linha
    as duplicava).
    """
    col_names = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    insert_sql = sa.text(
        f'INSERT INTO {target_table} ({col_names}) VALUES ({placeholders})'
    )

    rows_written = 0
    rejected: list[RejectedRow] = []
    batch_count = 0

    with engine.begin() as db_conn:
        # Limpa tabela se modo replace
        if write_disposition == "replace":
            dialect = engine.dialect.name.lower()
            if dialect == "sqlite":
                db_conn.execute(sa.text(f"DELETE FROM {target_table}"))
            else:
                db_conn.execute(sa.text(f"TRUNCATE TABLE {target_table}"))

        # Detecta suporte a savepoint (SQLite em modo autocommit nao suporta)
        supports_savepoint = engine.dialect.name.lower() != "sqlite"

        # Insere em lotes com savepoint para rollback preciso
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            batch_count += 1

            if supports_savepoint:
                # SAVEPOINT antes do batch — se falhar, rollback limpo
                savepoint = db_conn.begin_nested()
                try:
                    db_conn.execute(insert_sql, batch)
                    savepoint.commit()
                    rows_written += len(batch)
                except Exception:
                    # Rollback do savepoint: DESFAZ linhas parciais do batch
                    savepoint.rollback()
                    # Agora reinsere linha a linha com savepoint individual
                    for j, single_row in enumerate(batch):
                        sp_row = db_conn.begin_nested()
                        try:
                            db_conn.execute(insert_sql, [single_row])
                            sp_row.commit()
                            rows_written += 1
                        except Exception as row_exc:
                            sp_row.rollback()
                            row_num = i + j + 1
                            col_hint, val_hint, type_hint = _diagnose_row_error(
                                single_row, str(row_exc)
                            )
                            rejected.append(RejectedRow(
                                row_number=row_num,
                                error=str(row_exc)[:300],
                                column=col_hint,
                                value=val_hint,
                                expected_type=type_hint,
                            ))
                            if len(rejected) >= 50:
                                break
            else:
                # Fallback sem savepoint (SQLite)
                try:
                    db_conn.execute(insert_sql, batch)
                    rows_written += len(batch)
                except Exception:
                    for j, single_row in enumerate(batch):
                        try:
                            db_conn.execute(insert_sql, [single_row])
                            rows_written += 1
                        except Exception as row_exc:
                            row_num = i + j + 1
                            col_hint, val_hint, type_hint = _diagnose_row_error(
                                single_row, str(row_exc)
                            )
                            rejected.append(RejectedRow(
                                row_number=row_num,
                                error=str(row_exc)[:300],
                                column=col_hint,
                                value=val_hint,
                                expected_type=type_hint,
                            ))
                            if len(rejected) >= 50:
                                break

            if len(rejected) >= 50:
                break

    return LoadResult(
        status="success" if not rejected else "partial",
        rows_written=rows_written,
        batches=batch_count,
        rejected_rows=rejected,
        loader="sqlalchemy",
    )


def _diagnose_row_error(
    row: dict[str, Any],
    error_msg: str,
) -> tuple[str | None, Any, str | None]:
    """Tenta identificar qual coluna causou o erro."""
    error_lower = error_msg.lower()
    for col, val in row.items():
        if col.lower() in error_lower:
            return col, repr(val), type(val).__name__
    return None, None, None


# ─── Insercao via dlt ────────────────────────────────────────────────────────

def _insert_via_dlt(
    connection_string: str,
    target_table: str,
    rows: list[dict[str, Any]],
    write_disposition: str,
    merge_key: list[str] | None,
    batch_size: int,
) -> LoadResult:
    """Insere dados usando dlt pipeline."""
    destination = _build_dlt_destination(connection_string)
    dataset_name, effective_target = _resolve_dataset_and_table(
        connection_string, target_table
    )

    pipeline_name = _sanitize_name(
        f"shift_load_{effective_target}_{uuid4().hex[:8]}"
    )
    pipelines_dir = _build_dlt_pipelines_dir()

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        pipelines_dir=str(pipelines_dir),
        destination=destination,
        dataset_name=dataset_name,
    )

    dlt_write_disposition: Any = write_disposition
    if write_disposition == "merge" and merge_key:
        dlt_write_disposition = {
            "disposition": "merge",
            "strategy": "upsert",
            "merge_key": merge_key,
        }

    @dlt.resource(name=effective_target, write_disposition=dlt_write_disposition)
    def _data() -> Iterator[dict[str, Any]]:
        yield from rows

    load_info = pipeline.run(
        _data(),
        table_name=effective_target,
        write_disposition=dlt_write_disposition,
    )

    return LoadResult(
        status="success",
        rows_written=len(rows),
        batches=1,
        loader="dlt",
    )


# ─── Carga source-to-destination (modo producao) ────────────────────────────

def _read_source(
    source_connection: str,
    query: str,
    chunk_size: int,
) -> Iterator[dict[str, Any]]:
    """Gera linhas da fonte em streaming."""
    if source_connection.lower().startswith("duckdb"):
        import duckdb as _duckdb

        db_path = (
            source_connection.split("///", 1)[-1]
            if "///" in source_connection
            else ":memory:"
        )
        conn = _duckdb.connect(db_path, read_only=True)
        try:
            result = conn.execute(query)
            columns = [desc[0] for desc in result.description]
            while True:
                batch = result.fetchmany(chunk_size)
                if not batch:
                    break
                for row in batch:
                    yield dict(zip(columns, row))
        finally:
            conn.close()
        return

    normalized = source_connection.replace("+asyncpg", "+psycopg2")
    engine = sa.create_engine(normalized)
    try:
        with engine.connect().execution_options(stream_results=True) as conn:
            result = conn.execute(sa.text(query))
            while True:
                batch = result.mappings().fetchmany(chunk_size)
                if not batch:
                    break
                for row in batch:
                    yield dict(row)
    finally:
        engine.dispose()


def _load_source_via_sqlalchemy(
    source_connection: str,
    destination_connection: str,
    target_table: str,
    query: str,
    chunk_size: int,
    write_disposition: str,
    merge_key: list[str],
) -> dict[str, Any]:
    """Carrega dados usando SQLAlchemy puro (Oracle/Firebird)."""
    rows = list(_read_source(source_connection, query, chunk_size))
    if not rows:
        return {
            "loader": "sqlalchemy",
            "destination": destination_connection,
            "target_table": target_table,
            "rows_loaded": 0,
        }

    if write_disposition == "merge" and not merge_key:
        raise ValueError(
            f"write_disposition='merge' requer merge_key. "
            f"Tabela de destino: {target_table}"
        )

    schema: str | None = None
    bare_table = target_table
    if "." in target_table:
        schema, bare_table = target_table.split(".", 1)

    normalized = destination_connection.replace("+asyncpg", "+psycopg2")
    engine = sa.create_engine(normalized)

    try:
        meta = sa.MetaData(schema=schema)

        table_obj: Any = None
        try:
            table_obj = sa.Table(
                bare_table, meta,
                autoload_with=engine,
                schema=schema,
            )
        except Exception:
            table_obj = None

        with engine.begin() as conn:
            if write_disposition == "replace" and table_obj is not None:
                dialect = engine.dialect.name.lower()
                if dialect == "sqlite":
                    conn.execute(sa.text(
                        f"DELETE FROM {_quote_table(schema, bare_table)}"
                    ))
                else:
                    conn.execute(sa.text(
                        f"TRUNCATE TABLE {_quote_table(schema, bare_table)}"
                    ))

            if table_obj is None:
                table_obj = _create_table_from_rows(
                    engine=engine,
                    meta=meta,
                    schema=schema,
                    table_name=bare_table,
                    rows=rows,
                    merge_key=merge_key,
                )

            columns = [col.name for col in table_obj.columns]
            rows_loaded = 0

            if write_disposition == "merge":
                rows_loaded = _execute_merge(
                    conn=conn,
                    engine=engine,
                    table_obj=table_obj,
                    rows=rows,
                    columns=columns,
                    merge_key=merge_key,
                    chunk_size=chunk_size,
                    schema=schema,
                    bare_table=bare_table,
                )
            else:
                batch: list[dict[str, Any]] = []
                for row in rows:
                    filtered = {k: v for k, v in row.items() if k in columns}
                    batch.append(filtered)
                    if len(batch) >= chunk_size:
                        conn.execute(table_obj.insert(), batch)
                        rows_loaded += len(batch)
                        batch = []
                if batch:
                    conn.execute(table_obj.insert(), batch)
                    rows_loaded += len(batch)

    finally:
        engine.dispose()

    return {
        "loader": "sqlalchemy",
        "destination": destination_connection,
        "target_table": target_table,
        "rows_loaded": rows_loaded,
    }


def _load_source_via_dlt(
    source_connection: str,
    destination_connection: str,
    table_name: str,
    target_table: str,
    query: str | None,
    chunk_size: int,
    write_disposition: str,
    merge_key: list[str],
) -> dict[str, Any]:
    """Carrega dados usando dlt nativo."""
    destination = _build_dlt_destination(destination_connection)
    dataset_name, effective_target = _resolve_dataset_and_table(
        destination_connection, target_table,
    )

    pipeline_name = _sanitize_name(
        f"shift_load_{table_name}_to_{effective_target}"
    )
    pipelines_dir = _build_dlt_pipelines_dir()

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        pipelines_dir=str(pipelines_dir),
        destination=destination,
        dataset_name=dataset_name,
    )

    dlt_write_disposition: Any = write_disposition
    if write_disposition == "merge" and merge_key:
        dlt_write_disposition = {
            "disposition": "merge",
            "strategy": "upsert",
            "merge_key": merge_key,
        }

    @dlt.resource(name=effective_target, write_disposition=dlt_write_disposition)
    def _source_data() -> Any:
        effective_query = query or f"SELECT * FROM {table_name}"
        yield from _read_source(source_connection, effective_query, chunk_size)

    load_info = pipeline.run(
        _source_data(),
        table_name=effective_target,
        write_disposition=dlt_write_disposition,
    )

    return {
        "loader": "dlt",
        "pipeline_name": pipeline.pipeline_name,
        "destination": str(load_info.destination_name),
        "dataset": load_info.dataset_name,
        "loads": [
            {"package_id": package_id}
            for package_id in load_info.loads_ids
        ],
    }


# ─── Merge helpers (compartilhados pelo loader SQLAlchemy source-to-dest) ────

def _execute_merge(
    conn: Any,
    engine: Any,
    table_obj: Any,
    rows: list[dict[str, Any]],
    columns: list[str],
    merge_key: list[str],
    chunk_size: int,
    schema: str | None,
    bare_table: str,
) -> int:
    """Executa UPSERT em lotes."""
    dialect = engine.dialect.name.lower()
    rows_loaded = 0
    batch: list[dict[str, Any]] = []

    for row in rows:
        filtered = {k: v for k, v in row.items() if k in columns}
        batch.append(filtered)
        if len(batch) >= chunk_size:
            _flush_merge_batch(
                conn=conn, dialect=dialect, table_obj=table_obj,
                batch=batch, merge_key=merge_key,
                schema=schema, bare_table=bare_table,
            )
            rows_loaded += len(batch)
            batch = []

    if batch:
        _flush_merge_batch(
            conn=conn, dialect=dialect, table_obj=table_obj,
            batch=batch, merge_key=merge_key,
            schema=schema, bare_table=bare_table,
        )
        rows_loaded += len(batch)

    return rows_loaded


def _flush_merge_batch(
    conn: Any,
    dialect: str,
    table_obj: Any,
    batch: list[dict[str, Any]],
    merge_key: list[str],
    schema: str | None,
    bare_table: str,
) -> None:
    if dialect in ("oracle", "firebird"):
        _merge_oracle(conn, table_obj, batch, merge_key, schema, bare_table)
    elif dialect in ("postgresql", "sqlite"):
        _merge_postgresql(conn, table_obj, batch, merge_key)
    else:
        _merge_generic(conn, table_obj, batch, merge_key)


def _merge_oracle(
    conn: Any,
    table_obj: Any,
    batch: list[dict[str, Any]],
    merge_key: list[str],
    schema: str | None,
    bare_table: str,
) -> None:
    if not batch:
        return

    sample = batch[0]
    all_cols = list(sample.keys())
    update_cols = [c for c in all_cols if c not in merge_key]
    target_ref = _quote_table(schema, bare_table)

    using_cols = ", ".join(f":{col} AS {col}" for col in all_cols)
    on_clause = " AND ".join(f"t.{col} = s.{col}" for col in merge_key)

    if update_cols:
        update_clause = (
            "WHEN MATCHED THEN UPDATE SET "
            + ", ".join(f"t.{col} = s.{col}" for col in update_cols)
        )
    else:
        update_clause = ""

    insert_cols = ", ".join(all_cols)
    insert_vals = ", ".join(f"s.{col}" for col in all_cols)
    insert_clause = (
        f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
    )

    merge_sql = f"""
        MERGE INTO {target_ref} t
        USING (SELECT {using_cols} FROM dual) s
        ON ({on_clause})
        {update_clause}
        {insert_clause}
    """

    for row in batch:
        conn.execute(sa.text(merge_sql), row)


def _merge_postgresql(
    conn: Any,
    table_obj: Any,
    batch: list[dict[str, Any]],
    merge_key: list[str],
) -> None:
    if not batch:
        return

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    sample = batch[0]
    update_cols = {c: sample[c] for c in sample if c not in merge_key}

    stmt = pg_insert(table_obj).values(batch)
    if update_cols:
        stmt = stmt.on_conflict_do_update(
            index_elements=merge_key,
            set_={col: stmt.excluded[col] for col in update_cols},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=merge_key)

    conn.execute(stmt)


def _merge_generic(
    conn: Any,
    table_obj: Any,
    batch: list[dict[str, Any]],
    merge_key: list[str],
) -> None:
    for row in batch:
        try:
            conn.execute(table_obj.insert(), row)
        except Exception:
            key_filter = sa.and_(
                *[table_obj.c[k] == row[k] for k in merge_key if k in row]
            )
            update_vals = {k: v for k, v in row.items() if k not in merge_key}
            if update_vals:
                conn.execute(
                    table_obj.update().where(key_filter).values(**update_vals)
                )


# ─── Helpers dlt ─────────────────────────────────────────────────────────────

def _build_dlt_destination(connection_string: str) -> Any:
    cs = connection_string.lower()

    if cs.startswith("duckdb"):
        db_path = (
            connection_string.split("///", 1)[-1]
            if "///" in connection_string
            else ":memory:"
        )
        return dlt.destinations.duckdb(credentials=db_path)

    if cs.startswith(("postgresql", "postgres")):
        return dlt.destinations.postgres(credentials=connection_string)

    if cs.startswith(("mssql", "sqlserver")):
        return dlt.destinations.mssql(credentials=connection_string)

    if cs.startswith(("mysql", "mariadb")):
        return dlt.destinations.mysql(credentials=connection_string)

    return dlt.destinations.sqlalchemy(credentials=connection_string)


def _resolve_dataset_and_table(
    connection_string: str,
    target_table: str,
) -> tuple[str, str]:
    if "." in target_table:
        schema, bare_table = target_table.split(".", 1)
        return schema, bare_table
    return "shift_data", target_table


def _quote_table(schema: str | None, table: str) -> str:
    if schema:
        return f'"{schema}"."{table}"'
    return f'"{table}"'


def _create_table_from_rows(
    engine: Any,
    meta: Any,
    schema: str | None,
    table_name: str,
    rows: list[dict[str, Any]],
    merge_key: list[str] | None = None,
) -> Any:
    cs = str(engine.url).lower()
    is_oracle = cs.startswith("oracle")
    effective_merge_key = merge_key or []

    sample = rows[0]
    columns: list[Any] = []
    for col_name, value in sample.items():
        if isinstance(value, bool):
            col_type: Any = sa.Boolean()
        elif isinstance(value, int):
            col_type = sa.BigInteger()
        elif isinstance(value, float):
            col_type = sa.Numeric(precision=38, scale=10)
        else:
            col_type = sa.VARCHAR(4000) if is_oracle else sa.Text()

        is_key = col_name in effective_merge_key
        columns.append(sa.Column(col_name, col_type, nullable=not is_key))

    table_args: list[Any] = columns[:]
    if effective_merge_key:
        table_args.append(
            sa.UniqueConstraint(*effective_merge_key, name=f"uq_{table_name}_merge_key")
        )

    table_obj = sa.Table(table_name, meta, *table_args, schema=schema)
    meta.create_all(engine)
    return table_obj


def _sanitize_name(value: str) -> str:
    sanitized = "".join(
        c if c.isalnum() or c == "_" else "_"
        for c in value.strip()
    )
    return sanitized.strip("_") or "shift_load_pipeline"


def _build_dlt_pipelines_dir() -> Path:
    base_dir = (
        Path(tempfile.gettempdir())
        / "shift"
        / "dlt"
        / "loads"
        / str(uuid4())
    )
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


# ─── Instancia singleton ────────────────────────────────────────────────────

load_service = LoadService()
