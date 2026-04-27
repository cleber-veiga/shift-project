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
    failed_alias: str | None = None


@dataclass
class PreparedLoadRow:
    """Linha preparada para insert, mantendo referencia da origem."""

    source_row_number: int
    values: dict[str, Any]


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
    successful_row_numbers: list[int] = field(default_factory=list)
    failed_row_numbers: list[int] = field(default_factory=list)

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
class CompositeTableStepResult:
    """Metricas por tabela dentro de uma carga composta."""
    alias: str
    table: str
    rows_written: int = 0


@dataclass
class CompositeResult:
    """Resultado de uma carga composta (multi-tabela, transacional)."""
    status: str = "success"
    rows_received: int = 0
    rows_written: int = 0  # linhas de entrada processadas com sucesso (linhas fonte)
    steps: list[CompositeTableStepResult] = field(default_factory=list)
    duration_ms: int = 0
    failed_at_alias: str | None = None
    failed_at_row_index: int | None = None
    error_message: str | None = None
    rejected_rows: list[RejectedRow] = field(default_factory=list)
    successful_row_numbers: list[int] = field(default_factory=list)
    failed_row_numbers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "rows_received": self.rows_received,
            "rows_written": self.rows_written,
            "steps": [
                {
                    "alias": s.alias,
                    "table": s.table,
                    "rows_written": s.rows_written,
                }
                for s in self.steps
            ],
        }
        if self.duration_ms:
            d["duration_ms"] = self.duration_ms
        if self.failed_at_alias:
            d["failed_at_alias"] = self.failed_at_alias
        if self.failed_at_row_index is not None:
            d["failed_at_row_index"] = self.failed_at_row_index
        if self.error_message:
            d["error_message"] = self.error_message
        if self.rejected_rows:
            d["rejected_count"] = len(self.rejected_rows)
            d["rejected_rows"] = [
                {k: v for k, v in rr.__dict__.items() if v is not None}
                for rr in self.rejected_rows[:10]
            ]
        if self.successful_row_numbers:
            d["succeeded_count"] = len(self.successful_row_numbers)
        if self.failed_row_numbers:
            d["failed_count"] = len(self.failed_row_numbers)
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
        load_strategy: str = "append_fast",
        workspace_id: str | None = None,
    ) -> LoadResult:
        """
        Insere dados na tabela destino.

        Estrategias de carga (``load_strategy``):
        - ``"append_fast"`` (padrao): comportamento atual — dlt para PG/MySQL/MSSQL,
          SQLAlchemy para Oracle/Firebird. Commit por chunk; sem rollback global.
        - ``"append_safe"``: SQLAlchemy com transacao unica. Rollback total em
          qualquer erro. Insercao atomica — ou tudo vai ou nada vai.
        - ``"upsert"``: INSERT ... ON CONFLICT DO UPDATE (PG) / MERGE (MSSQL/Oracle)
          / INSERT ... ON DUPLICATE KEY UPDATE (MySQL). Requer ``merge_key``.

        Matriz de comportamento por destino (em caso de falha no meio da carga):

        +-------------+----------------------+----------------------+----------------------+
        | Destino     | append_fast          | append_safe          | upsert               |
        +=============+======================+======================+======================+
        | PostgreSQL  | Commit por chunk via | Transacao unica.     | ON CONFLICT DO       |
        |             | dlt. Chunks ja       | Rollback total em    | UPDATE. Idempotente  |
        |             | commitados ficam no  | qualquer erro.       | por merge_key.       |
        |             | destino.             |                      |                      |
        +-------------+----------------------+----------------------+----------------------+
        | MySQL       | Commit por chunk via | Transacao unica em   | ON DUPLICATE KEY     |
        |             | dlt. Chunks          | engines InnoDB.      | UPDATE. Requer       |
        |             | commitados           | MyISAM nao suporta   | indice UNIQUE sobre  |
        |             | permanecem.          | rollback — use       | merge_key.           |
        |             |                      | append_safe so em    |                      |
        |             |                      | InnoDB.              |                      |
        +-------------+----------------------+----------------------+----------------------+
        | SQL Server  | Commit por chunk via | Transacao unica via  | MERGE statement.     |
        |             | dlt.                 | SQLAlchemy. Rollback | Requer merge_key.    |
        |             |                      | total.               |                      |
        +-------------+----------------------+----------------------+----------------------+
        | Oracle      | SQLAlchemy em batch, | Transacao unica.     | MERGE INTO.          |
        |             | commit por chunk     | Rollback total.      | Requer merge_key.    |
        |             | (dlt nao suportado). |                      |                      |
        +-------------+----------------------+----------------------+----------------------+
        | Firebird    | SQLAlchemy em batch, | Transacao unica.     | UPDATE OR INSERT.    |
        |             | commit por chunk.    | Rollback total.      | Requer merge_key.    |
        +-------------+----------------------+----------------------+----------------------+

        Recomendacao para migracao de dados cliente:
        - Volumes > 10M: ``append_fast`` (rollback total inviavel em Oracle/SQL Server
          por log de transacao). Carga em tabela staging + swap manual.
        - Volumes < 10M com destino critico: ``append_safe``.
        - Reexecucao incremental de mesmo dataset: ``upsert`` com ``merge_key`` = PK.

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

        engine = _create_engine(connection_string, conn_type, workspace_id=workspace_id)
        try:
            # Introspeccao dos tipos da tabela destino
            col_type_map = _introspect_columns(engine, target_table)

            # Aplica column_mapping e cast, preservando a numeracao das
            # linhas de origem para split success/on_error a jusante.
            prepared_rows, cast_warnings, cast_summary = _prepare_rows_for_insert(
                rows, column_mapping, col_type_map
            )

            if not prepared_rows:
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
                cols = list(prepared_rows[0].values.keys())

            for col in cols:
                if not _COLUMN_NAME_RE.match(col):
                    raise ValueError(f"Nome de coluna invalido para escrita: '{col}'")

            # ── Dedup baseado em unique_columns ─────────────────────────────
            duplicates_removed = 0
            duplicate_sample: list[dict[str, Any]] = []
            effective_unique = unique_columns or []

            if effective_unique:
                # Resolve nomes: unique_columns pode vir como nomes de
                # destino (target). Garante que existem nas linhas preparadas.
                available_cols = (
                    set(prepared_rows[0].values.keys()) if prepared_rows else set()
                )
                valid_unique = [c for c in effective_unique if c in available_cols]

                if valid_unique:
                    seen: set[tuple] = set()
                    deduped: list[PreparedLoadRow] = []
                    for prepared in prepared_rows:
                        key = tuple(prepared.values.get(c) for c in valid_unique)
                        if key in seen:
                            duplicates_removed += 1
                            if len(duplicate_sample) < 5:
                                duplicate_sample.append(
                                    {c: prepared.values.get(c) for c in valid_unique}
                                )
                            continue
                        seen.add(key)
                        deduped.append(prepared)
                    prepared_rows = deduped

            if not prepared_rows:
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
            if load_strategy == "upsert":
                if not merge_key:
                    raise ValueError(
                        "load_strategy='upsert' requer merge_key com ao menos uma coluna."
                    )
                result = _upsert_via_sqlalchemy(
                    engine=engine,
                    connection_string=connection_string,
                    conn_type=conn_type,
                    target_table=target_table,
                    prepared_rows=prepared_rows,
                    cols=cols,
                    merge_key=merge_key,
                    batch_size=batch_size,
                )
            elif load_strategy == "append_safe":
                result = _insert_via_sqlalchemy(
                    engine=engine,
                    target_table=target_table,
                    prepared_rows=prepared_rows,
                    cols=cols,
                    write_disposition=write_disposition,
                    merge_key=merge_key or [],
                    batch_size=batch_size,
                )
            else:
                # append_fast: dlt para PG/MySQL/MSSQL, SQLAlchemy para Oracle/Firebird
                loader = _choose_loader(connection_string)
                if loader == "dlt":
                    try:
                        result = _insert_via_dlt(
                            connection_string=connection_string,
                            target_table=target_table,
                            rows=[prepared.values for prepared in prepared_rows],
                            source_row_numbers=[
                                prepared.source_row_number for prepared in prepared_rows
                            ],
                            write_disposition=write_disposition,
                            merge_key=merge_key,
                            batch_size=batch_size,
                        )
                    except Exception:
                        # dlt nao devolve diagnostico por linha. Se falhar,
                        # recai no caminho SQLAlchemy para capturar split
                        # success/on_error sem abortar o workflow inteiro.
                        result = _insert_via_sqlalchemy(
                            engine=engine,
                            target_table=target_table,
                            prepared_rows=prepared_rows,
                            cols=cols,
                            write_disposition=write_disposition,
                            merge_key=merge_key or [],
                            batch_size=batch_size,
                        )
                else:
                    result = _insert_via_sqlalchemy(
                        engine=engine,
                        target_table=target_table,
                        prepared_rows=prepared_rows,
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
            # Engine eh compartilhado pelo engine_cache — NAO chamar dispose()
            # aqui (fecharia conexoes ainda em uso por outras requests).
            pass

    def insert_composite(
        self,
        connection_string: str,
        conn_type: str,
        blueprint: dict[str, Any],
        field_mapping: dict[str, str],
        rows: list[dict[str, Any]],
        *,
        workspace_id: str | None = None,
    ) -> CompositeResult:
        """
        Insercao composta em multiplas tabelas relacionadas, em UMA transacao.

        Para cada linha da entrada, percorre ``blueprint["tables"]`` na ordem:
          1. Monta a linha a inserir a partir de ``field_mapping`` (alias.col -> upstream_col).
          2. Injeta colunas FK com valores RETURNING capturados de tabelas pais.
          3. Executa INSERT com RETURNING das colunas declaradas em ``returning``.
          4. Captura os valores para uso por filhos.

        Garantias:
          - Transacao unica: falha em qualquer insert faz rollback de TUDO.
          - Phase 1 exige cardinalidade ``one`` por tabela.
          - Firebird e MySQL nao sao suportados (ausencia de RETURNING portavel).
        """
        import time as _time

        started_at = _time.monotonic()

        steps_spec = _validate_blueprint(blueprint)
        per_alias_map = _split_field_mapping(field_mapping)

        if conn_type == "firebird":
            raise ValueError("insert_composite nao suporta Firebird (sem RETURNING portavel).")
        if conn_type == "mysql":
            raise ValueError("insert_composite nao suporta MySQL no Phase 1 (sem RETURNING portavel).")

        rows_received = len(rows)
        step_results: dict[str, CompositeTableStepResult] = {
            s["alias"]: CompositeTableStepResult(alias=s["alias"], table=s["table"])
            for s in steps_spec
        }

        if rows_received == 0:
            return CompositeResult(
                status="skipped",
                rows_received=0,
                rows_written=0,
                steps=list(step_results.values()),
                duration_ms=int((_time.monotonic() - started_at) * 1000),
            )

        engine = _create_engine(connection_string, conn_type, workspace_id=workspace_id)
        try:
            meta = sa.MetaData()
            tables_by_alias: dict[str, sa.Table] = {}
            col_types_by_alias: dict[str, dict[str, str]] = {}

            for step in steps_spec:
                alias = step["alias"]
                tbl_name = step["table"]
                _validate_table_name(tbl_name)
                schema: str | None = None
                bare_name = tbl_name
                if "." in tbl_name:
                    schema, bare_name = tbl_name.split(".", 1)
                table_obj = sa.Table(
                    bare_name,
                    meta,
                    autoload_with=engine,
                    schema=schema,
                )
                tables_by_alias[alias] = table_obj
                col_types_by_alias[alias] = _introspect_columns(engine, tbl_name)

            rows_written_source = 0
            failed_alias: str | None = None
            failed_index: int | None = None
            error_msg: str | None = None
            rejected_rows: list[RejectedRow] = []
            successful_row_numbers: list[int] = []

            with engine.begin() as db_conn:
                for row_index, source_row in enumerate(rows):
                    row_aliases: list[str] = []
                    captured: dict[str, dict[str, Any]] = {}
                    alias = ""
                    savepoint = db_conn.begin_nested()
                    try:
                        for step in steps_spec:
                            alias = step["alias"]
                            table_obj = tables_by_alias[alias]
                            col_types = col_types_by_alias[alias]
                            step_conflict_mode = step.get("conflict_mode", "insert")

                            insert_values = _build_composite_row(
                                step=step,
                                source_row=source_row,
                                upstream_map=per_alias_map.get(alias, {}),
                                captured=captured,
                                col_types=col_types,
                            )

                            returning_names = [
                                col for col in step["returning"]
                                if col in table_obj.c
                            ]

                            if step_conflict_mode == "insert":
                                stmt = table_obj.insert().values(**insert_values)
                                if returning_names:
                                    stmt = stmt.returning(
                                        *[table_obj.c[col] for col in returning_names]
                                    )
                                    result = db_conn.execute(stmt)
                                    row_ret = result.fetchone()
                                    captured[alias] = (
                                        dict(row_ret._mapping) if row_ret is not None else {}
                                    )
                                else:
                                    db_conn.execute(stmt)
                                    captured[alias] = {}
                            else:
                                if conn_type not in _UPSERT_SUPPORTED_DIALECTS:
                                    raise ValueError(
                                        f"alias='{alias}' conflict_mode="
                                        f"'{step_conflict_mode}' nao suportado para "
                                        f"conn_type='{conn_type}'. Dialetos com upsert: "
                                        "postgres, sqlite, oracle."
                                    )
                                missing_keys = [
                                    k for k in step["conflict_keys"]
                                    if k not in insert_values
                                ]
                                if missing_keys:
                                    raise ValueError(
                                        f"alias='{alias}' conflict_keys {missing_keys} "
                                        "nao presentes nos valores do INSERT — "
                                        "confira field_mapping/fk_map."
                                    )
                                stmts = _build_upsert_sql(
                                    conn_type=conn_type,
                                    table=step["table"],
                                    columns=list(insert_values.keys()),
                                    conflict_mode=step_conflict_mode,
                                    conflict_keys=step["conflict_keys"],
                                    update_columns=step.get("update_columns"),
                                    returning=returning_names,
                                )
                                row_ret = None
                                if stmts.always_fetch:
                                    db_conn.execute(
                                        sa.text(stmts.primary), insert_values
                                    )
                                else:
                                    result = db_conn.execute(
                                        sa.text(stmts.primary), insert_values
                                    )
                                    if returning_names:
                                        row_ret = result.fetchone()

                                if (
                                    returning_names
                                    and row_ret is None
                                    and stmts.fetch_existing is not None
                                ):
                                    key_params = {
                                        f"__ck_{k}": insert_values[k]
                                        for k in step["conflict_keys"]
                                    }
                                    fetch_result = db_conn.execute(
                                        sa.text(stmts.fetch_existing), key_params
                                    )
                                    row_ret = fetch_result.fetchone()

                                captured[alias] = (
                                    dict(row_ret._mapping) if row_ret is not None else {}
                                )

                            row_aliases.append(alias)

                        savepoint.commit()
                        rows_written_source += 1
                        successful_row_numbers.append(row_index + 1)
                        for committed_alias in row_aliases:
                            step_results[committed_alias].rows_written += 1
                    except Exception as exc:
                        savepoint.rollback()
                        current_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                        if failed_alias is None:
                            failed_alias = alias or None
                            failed_index = row_index
                            error_msg = current_error
                        rejected_rows.append(
                            RejectedRow(
                                row_number=row_index + 1,
                                error=current_error,
                                failed_alias=alias or None,
                            )
                        )
                        # Rollback acontece automaticamente ao sair do with com excecao.
                        failed_alias = alias  # noqa: F821 — alias do step que falhou

            duration = int((_time.monotonic() - started_at) * 1000)
            failed_row_numbers = [row.row_number for row in rejected_rows]
            status = "success"
            if rejected_rows:
                status = "partial" if rows_written_source > 0 else "error"
            return CompositeResult(
                status=status,
                rows_received=rows_received,
                rows_written=rows_written_source,
                steps=list(step_results.values()),
                duration_ms=duration,
                failed_at_alias=failed_alias,
                failed_at_row_index=failed_index,
                error_message=error_msg,
                rejected_rows=rejected_rows,
                successful_row_numbers=successful_row_numbers,
                failed_row_numbers=failed_row_numbers,
            )

        except Exception as exc:
            return CompositeResult(
                status="error",
                rows_received=rows_received,
                rows_written=0,
                steps=[
                    CompositeTableStepResult(alias=s["alias"], table=s["table"])
                    for s in steps_spec
                ],
                duration_ms=int((_time.monotonic() - started_at) * 1000),
                failed_at_alias=failed_alias,
                failed_at_row_index=failed_index,
                error_message=error_msg or f"{type(exc).__name__}: {str(exc)[:300]}",
            )
        finally:
            # Engine eh compartilhado pelo engine_cache — NAO chamar dispose()
            # aqui (fecharia conexoes ainda em uso por outras requests).
            pass

    def truncate(
        self,
        connection_string: str,
        conn_type: str,
        target_table: str,
        *,
        mode: str = "truncate",
        where_clause: str | None = None,
        workspace_id: str | None = None,
    ) -> TruncateResult:
        """Limpa (TRUNCATE ou DELETE) uma tabela de destino."""
        _validate_table_name(target_table)

        engine = _create_engine(connection_string, conn_type, workspace_id=workspace_id)
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
            # Engine eh compartilhado pelo engine_cache — NAO chamar dispose()
            # aqui (fecharia conexoes ainda em uso por outras requests).
            pass

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


def _create_engine(
    connection_string: str,
    conn_type: str,
    *,
    workspace_id: str | None = None,
) -> sa.Engine:
    """Devolve um engine cacheado pelo ``engine_cache`` global.

    O engine retornado pode ser compartilhado entre callers — NAO chame
    ``dispose()`` no caller. O cache aplica perfis de pool por tipo de
    banco (Oracle: pool_size=5, PostgreSQL: 10, etc.) e isola pools por
    workspace.

    ``workspace_id`` deve vir do contexto da execucao (``context["workspace_id"]``).
    Quando ``None``, o cache cai em ``DEFAULT_SCOPE`` — isso ainda dedupe
    chamadas com a mesma URL no processo, mas perde o isolamento por
    tenant. Sempre passe o valor real em codigo de producao.
    """
    from app.services.db.engine_cache import get_engine_from_url

    connect_args: dict[str, Any] = {}
    if conn_type == "sqlserver":
        connect_args["TrustServerCertificate"] = "yes"

    return get_engine_from_url(
        workspace_id,
        connection_string,
        conn_type,
        connect_args=connect_args or None,
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
    Oracle, Firebird e SQLite -> sqlalchemy.
    Tudo mais -> dlt.
    """
    cs = connection_string.lower()
    if cs.startswith(("oracle", "firebird", "sqlite")):
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


def _prepare_rows_for_insert(
    rows: list[dict[str, Any]],
    column_mapping: list[dict[str, str]] | None,
    col_type_map: dict[str, str],
) -> tuple[list[PreparedLoadRow], list[str], dict[str, int]]:
    """
    Aplica column_mapping e cast de tipos.

    Retorna linhas prontas para insert, preservando a numeracao da origem.
    """
    valid_maps = None
    if column_mapping:
        valid_maps = [m for m in column_mapping if m.get("source") and m.get("target")]
        if not valid_maps:
            raise ValueError("Nenhum mapeamento de colunas valido encontrado.")

    prepared_rows: list[PreparedLoadRow] = []
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

        prepared_rows.append(
            PreparedLoadRow(
                source_row_number=row_idx + 1,
                values=mapped_row,
            )
        )

    return prepared_rows, cast_warnings, cast_summary


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
    prepared_rows: list[PreparedLoadRow],
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
    _ = merge_key
    col_names = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    insert_sql = sa.text(
        f'INSERT INTO {target_table} ({col_names}) VALUES ({placeholders})'
    )

    rows_written = 0
    rejected: list[RejectedRow] = []
    successful_row_numbers: list[int] = []
    batch_count = 0

    with engine.begin() as db_conn:
        # Limpa tabela se modo replace
        if write_disposition == "replace":
            dialect = engine.dialect.name.lower()
            if dialect == "sqlite":
                db_conn.execute(sa.text(f"DELETE FROM {target_table}"))
            else:
                db_conn.execute(sa.text(f"TRUNCATE TABLE {target_table}"))

        # Savepoint e suportado em todos os dialetos que usamos (incluindo
        # SQLite, desde que a conexao esteja dentro de uma transacao — como e
        # o caso aqui via ``engine.begin()``). Isso e essencial para partial
        # row capture: se um batch falha, rolbackeamos apenas o batch e
        # reinserimos linha a linha, sem deixar linhas fantasma.
        supports_savepoint = True

        # Insere em lotes com savepoint para rollback preciso
        for i in range(0, len(prepared_rows), batch_size):
            batch_prepared = prepared_rows[i:i + batch_size]
            batch = [prepared.values for prepared in batch_prepared]
            batch_count += 1

            if supports_savepoint:
                # SAVEPOINT antes do batch — se falhar, rollback limpo
                savepoint = db_conn.begin_nested()
                try:
                    db_conn.execute(insert_sql, batch)
                    savepoint.commit()
                    rows_written += len(batch)
                    successful_row_numbers.extend(
                        prepared.source_row_number for prepared in batch_prepared
                    )
                except Exception:
                    # Rollback do savepoint: DESFAZ linhas parciais do batch
                    savepoint.rollback()
                    # Agora reinsere linha a linha com savepoint individual
                    for prepared in batch_prepared:
                        single_row = prepared.values
                        sp_row = db_conn.begin_nested()
                        try:
                            db_conn.execute(insert_sql, [single_row])
                            sp_row.commit()
                            rows_written += 1
                            successful_row_numbers.append(prepared.source_row_number)
                        except Exception as row_exc:
                            sp_row.rollback()
                            col_hint, val_hint, type_hint = _diagnose_row_error(
                                single_row, str(row_exc)
                            )
                            rejected.append(RejectedRow(
                                row_number=prepared.source_row_number,
                                error=str(row_exc)[:300],
                                column=col_hint,
                                value=val_hint,
                                expected_type=type_hint,
                            ))
            else:
                # Fallback sem savepoint (SQLite)
                try:
                    db_conn.execute(insert_sql, batch)
                    rows_written += len(batch)
                    successful_row_numbers.extend(
                        prepared.source_row_number for prepared in batch_prepared
                    )
                except Exception:
                    for prepared in batch_prepared:
                        single_row = prepared.values
                        try:
                            db_conn.execute(insert_sql, [single_row])
                            rows_written += 1
                            successful_row_numbers.append(prepared.source_row_number)
                        except Exception as row_exc:
                            col_hint, val_hint, type_hint = _diagnose_row_error(
                                single_row, str(row_exc)
                            )
                            rejected.append(RejectedRow(
                                row_number=prepared.source_row_number,
                                error=str(row_exc)[:300],
                                column=col_hint,
                                value=val_hint,
                                expected_type=type_hint,
                            ))
    failed_row_numbers = [row.row_number for row in rejected]
    status = "success"
    if rejected:
        status = "partial" if rows_written > 0 else "error"

    return LoadResult(
        status=status,
        rows_written=rows_written,
        batches=batch_count,
        rejected_rows=rejected,
        successful_row_numbers=successful_row_numbers,
        failed_row_numbers=failed_row_numbers,
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


# ─── Upsert via SQLAlchemy (append_safe idempotente por chave) ───────────────

def _upsert_via_sqlalchemy(
    engine: sa.Engine,
    connection_string: str,
    conn_type: str,
    target_table: str,
    prepared_rows: list[PreparedLoadRow],
    cols: list[str],
    merge_key: list[str],
    batch_size: int,
) -> LoadResult:
    """Upsert idempotente por chave de idempotencia.

    Comportamento por dialeto:
    - PostgreSQL  : INSERT ... ON CONFLICT (key) DO UPDATE SET col = EXCLUDED.col
    - MySQL       : INSERT ... ON DUPLICATE KEY UPDATE col = VALUES(col)
    - MSSQL/Oracle: MERGE INTO target USING source ON match WHEN MATCHED UPDATE / WHEN NOT MATCHED INSERT
    - Outros      : fallback para _insert_via_sqlalchemy com write_disposition='merge'
      (nao e idempotente mas nao quebra o workflow).

    Todos os dialetos executam em transacao unica — rollback total em erro.
    """
    dialect = engine.dialect.name.lower()
    col_names = ", ".join(f'"{c}"' for c in cols)

    rows_written = 0
    rejected: list[RejectedRow] = []
    successful_row_numbers: list[int] = []
    batch_count = 0

    with engine.begin() as db_conn:
        for i in range(0, len(prepared_rows), batch_size):
            batch_prepared = prepared_rows[i:i + batch_size]
            batch_count += 1

            for prepared in batch_prepared:
                row = prepared.values
                placeholders = ", ".join(f":{c}" for c in cols)
                sp = db_conn.begin_nested()
                try:
                    if dialect == "postgresql":
                        set_clause = ", ".join(
                            f'"{c}" = EXCLUDED."{c}"'
                            for c in cols
                            if c not in merge_key
                        ) or f'"{cols[0]}" = EXCLUDED."{cols[0]}"'
                        key_cols = ", ".join(f'"{k}"' for k in merge_key)
                        stmt = sa.text(
                            f"INSERT INTO {target_table} ({col_names}) "
                            f"VALUES ({placeholders}) "
                            f"ON CONFLICT ({key_cols}) DO UPDATE SET {set_clause}"
                        )
                    elif dialect == "mysql":
                        set_clause = ", ".join(
                            f'`{c}` = VALUES(`{c}`)'
                            for c in cols
                            if c not in merge_key
                        ) or f'`{cols[0]}` = VALUES(`{cols[0]}`)'
                        mysql_cols = ", ".join(f'`{c}`' for c in cols)
                        mysql_ph = ", ".join(f":{c}" for c in cols)
                        stmt = sa.text(
                            f"INSERT INTO {target_table} ({mysql_cols}) "
                            f"VALUES ({mysql_ph}) "
                            f"ON DUPLICATE KEY UPDATE {set_clause}"
                        )
                    else:
                        # MSSQL / Oracle / outros: MERGE statement
                        match_cond = " AND ".join(
                            f'target."{k}" = source."{k}"' for k in merge_key
                        )
                        src_cols_alias = ", ".join(f":{c} AS \"{c}\"" for c in cols)
                        update_clause = ", ".join(
                            f'target."{c}" = source."{c}"'
                            for c in cols
                            if c not in merge_key
                        )
                        insert_clause = f"({col_names}) VALUES ({', '.join(f'source.\"{c}\"' for c in cols)})"
                        if update_clause:
                            merge_sql = (
                                f"MERGE INTO {target_table} AS target "
                                f"USING (SELECT {src_cols_alias}) AS source ON ({match_cond}) "
                                f"WHEN MATCHED THEN UPDATE SET {update_clause} "
                                f"WHEN NOT MATCHED THEN INSERT {insert_clause}"
                            )
                        else:
                            merge_sql = (
                                f"MERGE INTO {target_table} AS target "
                                f"USING (SELECT {src_cols_alias}) AS source ON ({match_cond}) "
                                f"WHEN NOT MATCHED THEN INSERT {insert_clause}"
                            )
                        stmt = sa.text(merge_sql)

                    db_conn.execute(stmt, row)
                    sp.commit()
                    rows_written += 1
                    successful_row_numbers.append(prepared.source_row_number)
                except Exception as row_exc:
                    sp.rollback()
                    col_hint, val_hint, type_hint = _diagnose_row_error(row, str(row_exc))
                    rejected.append(RejectedRow(
                        row_number=prepared.source_row_number,
                        error=str(row_exc)[:300],
                        column=col_hint,
                        value=val_hint,
                        expected_type=type_hint,
                    ))

    failed_row_numbers = [r.row_number for r in rejected]
    status = "success"
    if rejected:
        status = "partial" if rows_written > 0 else "error"

    return LoadResult(
        status=status,
        rows_written=rows_written,
        batches=batch_count,
        rejected_rows=rejected,
        successful_row_numbers=successful_row_numbers,
        failed_row_numbers=failed_row_numbers,
        loader="sqlalchemy",
        write_disposition="merge",
        unique_columns=merge_key,
    )


# ─── Insercao via dlt ────────────────────────────────────────────────────────

def _insert_via_dlt(
    connection_string: str,
    target_table: str,
    rows: list[dict[str, Any]],
    source_row_numbers: list[int],
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
        successful_row_numbers=source_row_numbers,
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
        # ``read_only=True`` removido — DuckDB nao tolera mistura de modes
        # para o mesmo arquivo no mesmo processo. Default RW e seguro para
        # leitura. Ver discussao no docstring do filter_node.
        conn = _duckdb.connect(db_path)
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


# ─── Upsert SQL builder (composite) ─────────────────────────────────────────

_UPSERT_SUPPORTED_DIALECTS = frozenset({"postgres", "sqlite", "oracle"})


@dataclass
class UpsertStatements:
    """SQL gerado para um passo de upsert/insert_or_ignore."""
    primary: str
    """INSERT ... ON CONFLICT / MERGE — SQL principal a executar."""
    fetch_existing: str | None
    """SELECT pelas conflict_keys — usado como fallback quando primary nao retorna."""
    always_fetch: bool
    """True para dialetos cujo primary nunca retorna rows (ex.: Oracle MERGE)."""


def _build_upsert_sql(
    *,
    conn_type: str,
    table: str,
    columns: list[str],
    conflict_mode: str,
    conflict_keys: list[str],
    update_columns: list[str] | None,
    returning: list[str],
) -> UpsertStatements:
    """Monta SQL de upsert para postgres/sqlite/oracle.

    ``columns`` deve conter TODAS as colunas que irao no INSERT (inclui FKs),
    na ordem em que os binds foram preparados pelo chamador. As conflict_keys
    sao validadas como subset desse conjunto; update_columns=None significa
    atualizar tudo exceto conflict_keys.
    """
    if conflict_mode not in ("upsert", "insert_or_ignore"):
        raise ValueError(
            f"_build_upsert_sql espera 'upsert' ou 'insert_or_ignore', "
            f"recebeu '{conflict_mode}'."
        )
    if conn_type not in _UPSERT_SUPPORTED_DIALECTS:
        raise ValueError(
            f"Upsert nao suportado para conn_type='{conn_type}'. "
            "Dialetos suportados: postgres, sqlite, oracle."
        )
    if not conflict_keys:
        raise ValueError("conflict_keys nao pode ser vazio.")
    col_set = set(columns)
    missing_keys = [k for k in conflict_keys if k not in col_set]
    if missing_keys:
        raise ValueError(
            f"conflict_keys {missing_keys} nao estao entre as colunas "
            f"do INSERT ({sorted(col_set)})."
        )

    schema: str | None = None
    bare = table
    if "." in table:
        schema, bare = table.split(".", 1)
    target = _quote_table(schema, bare)

    quoted_cols = [f'"{c}"' for c in columns]
    col_list = ", ".join(quoted_cols)
    placeholders = ", ".join(f":{c}" for c in columns)

    effective_update = (
        list(update_columns)
        if update_columns is not None
        else [c for c in columns if c not in conflict_keys]
    )

    fetch_existing: str | None = None
    if returning:
        returning_list_fetch = ", ".join(f'"{c}"' for c in returning)
        key_where = " AND ".join(f'"{k}" = :__ck_{k}' for k in conflict_keys)
        fetch_existing = (
            f"SELECT {returning_list_fetch} FROM {target} WHERE {key_where}"
        )

    if conn_type in ("postgres", "sqlite"):
        key_list = ", ".join(f'"{k}"' for k in conflict_keys)
        if conflict_mode == "upsert" and effective_update:
            set_clause = ", ".join(
                f'"{c}" = EXCLUDED."{c}"' for c in effective_update
            )
            conflict_action = (
                f"ON CONFLICT ({key_list}) DO UPDATE SET {set_clause}"
            )
        else:
            conflict_action = f"ON CONFLICT ({key_list}) DO NOTHING"

        returning_clause = (
            " RETURNING " + ", ".join(f'"{c}"' for c in returning)
            if returning else ""
        )
        primary = (
            f"INSERT INTO {target} ({col_list}) VALUES ({placeholders}) "
            f"{conflict_action}{returning_clause}"
        )
        always_fetch = False

    else:  # oracle
        using_cols = ", ".join(f':{c} AS "{c}"' for c in columns)
        on_clause = " AND ".join(f't."{k}" = s."{k}"' for k in conflict_keys)
        insert_vals = ", ".join(f's."{c}"' for c in columns)

        if conflict_mode == "upsert" and effective_update:
            update_clause = (
                "WHEN MATCHED THEN UPDATE SET "
                + ", ".join(f't."{c}" = s."{c}"' for c in effective_update)
                + " "
            )
        else:
            update_clause = ""

        insert_clause = (
            f"WHEN NOT MATCHED THEN INSERT ({col_list}) "
            f"VALUES ({insert_vals})"
        )
        primary = (
            f"MERGE INTO {target} t USING "
            f"(SELECT {using_cols} FROM dual) s "
            f"ON ({on_clause}) {update_clause}{insert_clause}"
        )
        # MERGE no Oracle nunca retorna rows por si — fetch obrigatorio quando
        # returning foi pedido.
        always_fetch = bool(returning)

    return UpsertStatements(
        primary=primary,
        fetch_existing=fetch_existing,
        always_fetch=always_fetch,
    )


# ─── Helpers do insert_composite ────────────────────────────────────────────

def _validate_blueprint(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Valida o blueprint e retorna a lista de steps normalizada.

    Checa: (a) tables nao-vazio; (b) aliases unicos; (c) filhos referenciam
    pais que aparecem antes no array; (d) fk_map.parent_returning existe
    em ``returning`` do pai. Levanta ValueError em qualquer violacao.
    """
    tables = blueprint.get("tables") if isinstance(blueprint, dict) else None
    if not isinstance(tables, list) or not tables:
        raise ValueError("blueprint.tables deve ser uma lista nao-vazia.")

    seen_aliases: set[str] = set()
    returning_by_alias: dict[str, set[str]] = {}
    normalized: list[dict[str, Any]] = []

    for idx, raw in enumerate(tables):
        if not isinstance(raw, dict):
            raise ValueError(f"blueprint.tables[{idx}] deve ser dict.")

        alias = str(raw.get("alias") or "").strip()
        table = str(raw.get("table") or "").strip()
        if not alias:
            raise ValueError(f"blueprint.tables[{idx}].alias obrigatorio.")
        if not table:
            raise ValueError(f"blueprint.tables[{idx}].table obrigatorio.")
        if alias in seen_aliases:
            raise ValueError(f"alias duplicado no blueprint: '{alias}'.")
        seen_aliases.add(alias)

        role = str(raw.get("role") or "header")
        parent_alias = raw.get("parent_alias")
        fk_map_raw = raw.get("fk_map") or []
        cardinality = str(raw.get("cardinality") or "one")
        columns = [str(c) for c in (raw.get("columns") or []) if c]
        returning = [str(c) for c in (raw.get("returning") or []) if c]
        conflict_mode = str(raw.get("conflict_mode") or "insert")
        conflict_keys = [str(c) for c in (raw.get("conflict_keys") or []) if c]
        update_columns_raw = raw.get("update_columns")
        update_columns: list[str] | None = (
            [str(c) for c in update_columns_raw if c]
            if isinstance(update_columns_raw, list)
            else None
        )

        if conflict_mode not in ("insert", "upsert", "insert_or_ignore"):
            raise ValueError(
                f"alias='{alias}' conflict_mode invalido: '{conflict_mode}'."
            )
        if conflict_mode != "insert" and not conflict_keys:
            raise ValueError(
                f"alias='{alias}' conflict_mode='{conflict_mode}' "
                "exige conflict_keys nao-vazio."
            )
        if update_columns is not None:
            for col in update_columns:
                if col not in columns:
                    raise ValueError(
                        f"alias='{alias}' update_columns contem '{col}' "
                        "que nao esta em columns."
                    )

        if cardinality != "one":
            raise ValueError(
                f"Phase 1 so suporta cardinality='one'. "
                f"alias='{alias}' declarou '{cardinality}'."
            )

        fk_map: list[dict[str, str]] = []
        if role == "child":
            if not parent_alias:
                raise ValueError(f"alias='{alias}' role='child' exige parent_alias.")
            if parent_alias not in seen_aliases or parent_alias == alias:
                raise ValueError(
                    f"alias='{alias}' referencia parent_alias='{parent_alias}' "
                    "que nao foi declarado antes no blueprint."
                )
            if not fk_map_raw:
                raise ValueError(f"alias='{alias}' role='child' exige fk_map nao-vazio.")

            parent_returning_set = returning_by_alias.get(parent_alias, set())
            for fk_idx, fk in enumerate(fk_map_raw):
                if not isinstance(fk, dict):
                    raise ValueError(
                        f"alias='{alias}' fk_map[{fk_idx}] deve ser dict."
                    )
                child_column = str(fk.get("child_column") or "").strip()
                parent_returning = str(fk.get("parent_returning") or "").strip()
                if not child_column or not parent_returning:
                    raise ValueError(
                        f"alias='{alias}' fk_map[{fk_idx}] exige "
                        "child_column e parent_returning."
                    )
                if parent_returning not in parent_returning_set:
                    raise ValueError(
                        f"alias='{alias}' fk_map aponta para "
                        f"'{parent_alias}.{parent_returning}' que nao esta em "
                        f"returning do pai."
                    )
                fk_map.append(
                    {"child_column": child_column, "parent_returning": parent_returning}
                )

        fk_child_cols = {fk["child_column"] for fk in fk_map}
        allowed_conflict_keys = set(columns) | fk_child_cols
        for key in conflict_keys:
            if key not in allowed_conflict_keys:
                raise ValueError(
                    f"alias='{alias}' conflict_keys contem '{key}' "
                    "que nao esta em columns nem em fk_map.child_column."
                )

        returning_by_alias[alias] = set(returning)
        normalized.append({
            "alias": alias,
            "table": table,
            "role": role,
            "parent_alias": parent_alias if role == "child" else None,
            "fk_map": fk_map,
            "cardinality": cardinality,
            "columns": columns,
            "returning": returning,
            "conflict_mode": conflict_mode,
            "conflict_keys": conflict_keys,
            "update_columns": update_columns,
        })

    return normalized


def _split_field_mapping(
    field_mapping: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Divide ``{'alias.col': 'upstream_col'}`` em ``{alias: {col: upstream_col}}``."""
    out: dict[str, dict[str, str]] = {}
    for key, upstream_col in (field_mapping or {}).items():
        if not isinstance(key, str) or "." not in key:
            continue
        alias, _, column = key.partition(".")
        alias = alias.strip()
        column = column.strip()
        if not alias or not column:
            continue
        out.setdefault(alias, {})[column] = str(upstream_col)
    return out


def _build_composite_row(
    *,
    step: dict[str, Any],
    source_row: dict[str, Any],
    upstream_map: dict[str, str],
    captured: dict[str, dict[str, Any]],
    col_types: dict[str, str],
) -> dict[str, Any]:
    """Monta valores do INSERT desta tabela (FKs do pai + campos do upstream)."""
    values: dict[str, Any] = {}

    # 1. FKs primeiro — vem de captured[parent_alias]
    parent_alias = step.get("parent_alias")
    for fk in step.get("fk_map") or []:
        parent_values = captured.get(parent_alias or "") or {}
        values[fk["child_column"]] = parent_values.get(fk["parent_returning"])

    # 2. Colunas declaradas, lidas do source_row via upstream_map
    for column in step["columns"]:
        upstream_key = upstream_map.get(column)
        if upstream_key is None:
            continue
        raw_value = source_row.get(upstream_key)
        db_type = col_types.get(column.upper(), "")
        try:
            values[column] = cast_for_db(raw_value, db_type)
        except (ValueError, TypeError):
            values[column] = raw_value

    return values


# ─── Instancia singleton ────────────────────────────────────────────────────

load_service = LoadService()
