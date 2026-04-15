"""
Modulo de carga de dados.

Responsabilidade unica: carregar dados de uma fonte SQL (incluindo DuckDB
de staging) para um destino SQL, com suporte a diferentes estrategias de
escrita (append, replace, merge).

Estrategia de carga por tipo de destino:
  - Oracle / Firebird: SQLAlchemy direto (o dlt tem bug ORA-00932 com CLOB
    nas tabelas de controle _dlt_pipeline_state quando o destino e Oracle).
  - Demais bancos (PostgreSQL, DuckDB, MSSQL, MySQL): dlt nativo.

Estrategias de escrita suportadas no loader SQLAlchemy:
  - append:  INSERT INTO sem verificacao de duplicatas.
  - replace: TRUNCATE + INSERT INTO.
  - merge:   UPSERT — INSERT quando a chave nao existe, UPDATE quando existe.
             Requer o parametro merge_key com a lista de colunas-chave.
             Usa MERGE INTO (Oracle/Firebird) ou INSERT ... ON CONFLICT (PostgreSQL/SQLite).

As transformacoes sao responsabilidade dos nos individuais do workflow,
que materializam seus resultados em DuckDB antes de passar para o proximo no.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

import dlt


# ---------------------------------------------------------------------------
# Ponto de entrada principal
# ---------------------------------------------------------------------------

def run_migration_pipeline(
    source_connection: str,
    destination_connection: str,
    table_name: str,
    target_table: str,
    query: str | None = None,
    chunk_size: int = 1000,
    write_disposition: str = "append",
    merge_key: list[str] | None = None,
) -> dict[str, Any]:
    """
    Carrega dados de uma fonte para um destino.

    Detecta automaticamente o tipo de destino e escolhe a estrategia
    de carga mais adequada:
      - Oracle/Firebird: SQLAlchemy direto (evita bug CLOB do dlt).
      - Demais bancos: dlt nativo.

    Args:
        source_connection:     Connection string da fonte (pode ser duckdb:///...).
        destination_connection: Connection string do destino.
        table_name:            Nome da tabela de origem (ou alias para a query).
        target_table:          Nome da tabela de destino.
        query:                 Query SQL customizada para leitura da fonte (opcional).
        chunk_size:            Tamanho do lote de leitura em streaming.
        write_disposition:     Estrategia de escrita (append, replace, merge).
        merge_key:             Colunas que identificam unicamente um registro.
                               Obrigatorio quando write_disposition='merge'.
    """
    cs = destination_connection.lower()

    if cs.startswith(("oracle", "firebird")):
        return _load_via_sqlalchemy(
            source_connection=source_connection,
            destination_connection=destination_connection,
            target_table=target_table,
            query=query or f"SELECT * FROM {table_name}",  # noqa: S608
            chunk_size=chunk_size,
            write_disposition=write_disposition,
            merge_key=merge_key or [],
        )

    return _load_via_dlt(
        source_connection=source_connection,
        destination_connection=destination_connection,
        table_name=table_name,
        target_table=target_table,
        query=query,
        chunk_size=chunk_size,
        write_disposition=write_disposition,
        merge_key=merge_key or [],
    )


# ---------------------------------------------------------------------------
# Loader SQLAlchemy direto — usado para Oracle e Firebird
# ---------------------------------------------------------------------------

def _load_via_sqlalchemy(
    source_connection: str,
    destination_connection: str,
    target_table: str,
    query: str,
    chunk_size: int,
    write_disposition: str,
    merge_key: list[str],
) -> dict[str, Any]:
    """
    Carrega dados usando SQLAlchemy puro, sem dlt.

    Suporta write_disposition:
      - append:  INSERT INTO.
      - replace: TRUNCATE + INSERT INTO.
      - merge:   UPSERT via MERGE INTO (Oracle/Firebird) ou
                 INSERT ... ON CONFLICT DO UPDATE (PostgreSQL/SQLite).
                 Requer merge_key nao vazio.
    """
    import sqlalchemy as sa

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
            f"write_disposition='merge' requer merge_key com ao menos uma coluna. "
            f"Tabela de destino: {target_table}"
        )

    # Resolve schema e nome da tabela
    schema: str | None = None
    bare_table = target_table
    if "." in target_table:
        schema, bare_table = target_table.split(".", 1)

    normalized = destination_connection.replace("+asyncpg", "+psycopg2")
    engine = sa.create_engine(normalized)

    try:
        meta = sa.MetaData(schema=schema)

        # Tenta carregar a tabela existente via autoload.
        # Se nao existir, table_obj fica None e a tabela sera criada.
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
                # SQLite nao suporta TRUNCATE — usa DELETE FROM
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
    """
    Executa UPSERT linha a linha em lotes.

    Estrategia por dialeto:
      - Oracle / Firebird: MERGE INTO ... USING dual ON (...) WHEN MATCHED THEN UPDATE
                           WHEN NOT MATCHED THEN INSERT
      - PostgreSQL / SQLite: INSERT INTO ... ON CONFLICT (...) DO UPDATE SET ...
      - Demais: INSERT INTO com fallback para UPDATE quando viola PK/UK
    """
    import sqlalchemy as sa

    dialect = engine.dialect.name.lower()
    rows_loaded = 0
    batch: list[dict[str, Any]] = []

    for row in rows:
        filtered = {k: v for k, v in row.items() if k in columns}
        batch.append(filtered)
        if len(batch) >= chunk_size:
            _flush_merge_batch(
                conn=conn,
                dialect=dialect,
                table_obj=table_obj,
                batch=batch,
                merge_key=merge_key,
                schema=schema,
                bare_table=bare_table,
            )
            rows_loaded += len(batch)
            batch = []

    if batch:
        _flush_merge_batch(
            conn=conn,
            dialect=dialect,
            table_obj=table_obj,
            batch=batch,
            merge_key=merge_key,
            schema=schema,
            bare_table=bare_table,
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
    """Executa o UPSERT de um lote de linhas."""
    import sqlalchemy as sa

    if dialect in ("oracle", "firebird"):
        _merge_oracle(conn, table_obj, batch, merge_key, schema, bare_table)
    elif dialect in ("postgresql", "sqlite"):
        _merge_postgresql(conn, table_obj, batch, merge_key)
    else:
        # Fallback generico: tenta INSERT, se violar constraint faz UPDATE
        _merge_generic(conn, table_obj, batch, merge_key)


def _merge_oracle(
    conn: Any,
    table_obj: Any,
    batch: list[dict[str, Any]],
    merge_key: list[str],
    schema: str | None,
    bare_table: str,
) -> None:
    """
    MERGE INTO para Oracle e Firebird.

    Sintaxe:
        MERGE INTO target t
        USING (SELECT :col1 col1, :col2 col2, ... FROM dual) s
        ON (t.key1 = s.key1 AND t.key2 = s.key2)
        WHEN MATCHED THEN UPDATE SET t.col = s.col, ...
        WHEN NOT MATCHED THEN INSERT (col1, col2, ...) VALUES (s.col1, s.col2, ...)
    """
    import sqlalchemy as sa

    if not batch:
        return

    sample = batch[0]
    all_cols = list(sample.keys())
    update_cols = [c for c in all_cols if c not in merge_key]
    target_ref = _quote_table(schema, bare_table)

    # Monta o SELECT da clausula USING com parametros nomeados
    using_cols = ", ".join(
        f":{col} AS {col}" for col in all_cols
    )
    on_clause = " AND ".join(
        f"t.{col} = s.{col}" for col in merge_key
    )

    if update_cols:
        update_clause = (
            "WHEN MATCHED THEN UPDATE SET "
            + ", ".join(f"t.{col} = s.{col}" for col in update_cols)
        )
    else:
        # Todas as colunas sao chave — nao ha nada para atualizar
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
    """
    INSERT ... ON CONFLICT DO UPDATE para PostgreSQL e SQLite.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not batch:
        return

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
    """
    Fallback de merge para bancos sem suporte a MERGE INTO ou ON CONFLICT.
    Tenta INSERT; se falhar por violacao de constraint, faz UPDATE.
    """
    import sqlalchemy as sa

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


def _quote_table(schema: str | None, table: str) -> str:
    """Monta referencia qualificada da tabela para SQL."""
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
    """
    Cria a tabela de destino inferindo tipos das primeiras linhas.

    Quando merge_key e informado, cria uma constraint UNIQUE nas colunas-chave
    para que o ON CONFLICT / MERGE INTO funcione corretamente.

    Usa VARCHAR2(4000) para strings no Oracle, TEXT para outros bancos.
    """
    import sqlalchemy as sa

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


# ---------------------------------------------------------------------------
# Loader dlt — usado para PostgreSQL, DuckDB, MSSQL, MySQL
# ---------------------------------------------------------------------------

def _load_via_dlt(
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

    pipeline_name = _sanitize_pipeline_name(
        f"shift_load_{table_name}_to_{effective_target}"
    )
    pipelines_dir = _build_dlt_pipelines_dir()

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        pipelines_dir=str(pipelines_dir),
        destination=destination,
        dataset_name=dataset_name,
    )

    # O dlt suporta merge nativo quando merge_key e informado
    dlt_write_disposition: Any = write_disposition
    if write_disposition == "merge" and merge_key:
        dlt_write_disposition = {
            "disposition": "merge",
            "strategy": "upsert",
            "merge_key": merge_key,
        }

    @dlt.resource(name=effective_target, write_disposition=dlt_write_disposition)
    def _source_data() -> Any:
        effective_query = query or f"SELECT * FROM {table_name}"  # noqa: S608
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


# ---------------------------------------------------------------------------
# Leitura da fonte — compartilhada por ambos os loaders
# ---------------------------------------------------------------------------

def _read_source(
    source_connection: str,
    query: str,
    chunk_size: int,
) -> Any:
    """
    Gera linhas da fonte em streaming.
    Suporta DuckDB (nativo) e qualquer banco SQLAlchemy.
    """
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

    import sqlalchemy as sa

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


# ---------------------------------------------------------------------------
# Helpers dlt
# ---------------------------------------------------------------------------

def _build_dlt_destination(connection_string: str) -> Any:
    """Retorna o destino dlt correspondente ao tipo de banco."""
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
    """Resolve dataset_name e nome efetivo da tabela para o dlt."""
    if "." in target_table:
        schema, bare_table = target_table.split(".", 1)
        return schema, bare_table
    return "shift_data", target_table


def _sanitize_pipeline_name(value: str) -> str:
    """Normaliza nomes de pipeline para um formato aceito pelo dlt."""
    sanitized = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in value.strip()
    )
    return sanitized.strip("_") or "shift_load_pipeline"


def _build_dlt_pipelines_dir() -> Path:
    """Cria um workspace temporario isolado para o dlt."""
    base_dir = (
        Path(tempfile.gettempdir())
        / "shift"
        / "dlt"
        / "loads"
        / str(uuid4())
    )
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir
