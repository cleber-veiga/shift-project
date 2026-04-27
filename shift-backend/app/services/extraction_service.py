"""
Servico unificado de extracao de dados.

Centraliza toda leitura de fontes SQL (incluindo Firebird via driver direto),
com streaming, paginacao e serializacao automatica de tipos.

Usado tanto pelo modo teste (workflow_test_service) quanto pelo modo
producao (workflow/nodes/sql_database).
"""

from __future__ import annotations

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import dlt
import sqlalchemy as sa

from app.core.logging import get_logger
from app.data_pipelines.duckdb_storage import (
    JsonlStreamer,
    sanitize_name as _sanitize_jsonl,
)
from app.services.db.engine_cache import (
    get_engine_from_url,
    get_pool_capacity,
)
from app.services.streaming import BoundedChunkQueue

logger = get_logger(__name__)


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

    def extract_sql_partitioned_to_duckdb(
        self,
        connection_string: str,
        conn_type: str,
        query: str,
        execution_id: str,
        resource_name: str,
        *,
        partition_on: str | None,
        partition_num: int = 1,
        chunk_size: int = 50_000,
        max_rows: int | None = None,
        workspace_id: Any = None,
        cancel_event: threading.Event | None = None,
    ) -> "DuckDbExtractionResult":
        """Extracao SQL com leitura paralela particionada e streaming.

        Quando ``partition_on`` e ``partition_num > 1``:
            - Roda uma query auxiliar para obter MIN/MAX/has_null da coluna.
            - Rejeita coluna nullable (sem CASE NULL handling) — proteger
              integridade de range scan.
            - Divide o intervalo em ``partition_num`` ranges iguais.
            - Cada range vira um producer em ThreadPool com cursor server-side
              do SQLAlchemy (``stream_results=True`` + ``fetchmany``).
            - Producers empilham listas de linhas em uma ``queue.Queue(maxsize=4)``
              para backpressure natural.
            - Um consumer drena a queue e escreve incrementalmente em JSONL,
              que vira tabela DuckDB no fim via ``CREATE TABLE AS SELECT``.

        Quando ``partition_on`` e ``None`` ou ``partition_num <= 1``:
            - Cai no fallback single-connection com o mesmo streaming.

        ``cancel_event`` permite cancelamento cooperativo: producers e
        consumer checam o flag entre chunks e abortam fechando seus cursores
        — necessario para honrar ``execution_registry.cancel()`` do runner.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size deve ser > 0")
        if partition_num < 1:
            raise ValueError("partition_num deve ser >= 1")

        # Cap explicito: nunca exceder a capacidade do pool — abrir N conexoes
        # simultaneas com N maior que o pool gera contention/timeout no
        # checkout. O cap e por engine (conn_type-specifico).
        max_workers = min(partition_num, get_pool_capacity(conn_type))
        if max_workers != partition_num:
            logger.warning(
                "extraction.partition_num_capped",
                requested=partition_num,
                effective=max_workers,
                conn_type=conn_type,
                reason="pool_capacity",
            )

        normalized_url = _normalize_connection_url(connection_string)
        engine = get_engine_from_url(workspace_id, normalized_url, conn_type)
        # ``cancel_event`` (externo) representa cancelamento explicito
        # solicitado pelo runner. Producers tambem checam ``stop_event``
        # — setado por cancelamento OU por max_rows atingido. Isso permite
        # distinguir "abort do usuario" (CancelledError) de "alcancou
        # max_rows" (resultado normal).
        external_cancel = cancel_event or threading.Event()
        cancel_event = external_cancel  # producers usam o sinal de stop unificado

        # Decide o particionamento:
        partitions: list[tuple[Any, Any, bool]] = []
        if partition_on and max_workers > 1:
            try:
                partitions = _compute_partitions(
                    engine, query, partition_on, max_workers
                )
            except _PartitionAborted as exc:
                logger.info(
                    "extraction.partition_fallback_single",
                    reason=str(exc),
                )
                partitions = []

        if not partitions:
            # Fallback: single producer cobrindo todo o range.
            partitions = [(None, None, True)]

        # Materializacao via JsonlStreamer — escreve incrementalmente, so
        # toca DuckDB no fim. Mantem RAM ~ 1 chunk por vez.
        # A queue e a BoundedChunkQueue do Prompt 1.2: backpressure puro
        # em RAM com spillover opcional para disco quando o consumer for
        # mais lento que o producer (ver settings.STREAMING_*).
        from app.core.config import settings as _settings
        from app.services.streaming.bounded_chunk_queue import default_spill_dir

        spill_dir = (
            Path(_settings.STREAMING_SPILL_DIR)
            if _settings.STREAMING_SPILL_DIR
            else default_spill_dir()
        )
        max_inmem = max(1, _settings.STREAMING_MAX_IN_MEMORY_CHUNKS)

        streamer = JsonlStreamer(execution_id, _sanitize_jsonl(resource_name))
        with streamer:
            shared_queue = BoundedChunkQueue(
                max_inmem,
                execution_id=execution_id,
                spill_dir=spill_dir,
                spill_when_exceeded=_settings.STREAMING_SPILL_WHEN_EXCEEDED,
                spill_warn_threshold=_settings.STREAMING_SPILL_WARN_THRESHOLD,
            )
            rows_written_total = threading.Lock()
            counters: dict[str, Any] = {"written": 0, "max_rows_reached": False}

            consumer_done = threading.Event()
            producer_errors: list[BaseException] = []

            def _consumer() -> None:
                """Drena ``shared_queue``; escreve no JSONL ate todos producers EOF."""
                eofs_received = 0
                expected_eofs = len(partitions)
                while eofs_received < expected_eofs:
                    item = shared_queue.get_sync()
                    if item == BoundedChunkQueue.EOF:
                        eofs_received += 1
                        continue
                    if cancel_event.is_set():
                        # Continua drenando para destravar producers, mas nao escreve.
                        continue
                    if max_rows is not None:
                        with rows_written_total:
                            remaining = max_rows - counters["written"]
                        if remaining <= 0:
                            counters["max_rows_reached"] = True
                            cancel_event.set()
                            continue
                        if len(item) > remaining:
                            item = item[:remaining]
                    streamer.write_batch(item)
                    with rows_written_total:
                        counters["written"] += len(item)
                consumer_done.set()

            consumer_thread = threading.Thread(
                target=_consumer, name="sql-extract-consumer", daemon=True
            )
            consumer_thread.start()

            # Producers: cada particao abre uma conexao do pool cacheado.
            try:
                with ThreadPoolExecutor(
                    max_workers=max(1, len(partitions)),
                    thread_name_prefix="sql-extract-producer",
                ) as pool:
                    futures = [
                        pool.submit(
                            _producer_partition,
                            engine,
                            query,
                            partition_on,
                            lo,
                            hi,
                            inclusive_max,
                            chunk_size,
                            shared_queue,
                            cancel_event,
                            conn_type,
                        )
                        for (lo, hi, inclusive_max) in partitions
                    ]
                    for fut in futures:
                        try:
                            fut.result()
                        except BaseException as exc:  # noqa: BLE001
                            producer_errors.append(exc)
                            cancel_event.set()
            finally:
                # Garante que o consumer destrave mesmo em caso de erro:
                # envia 1 EOF por particao mais um close de seguranca.
                # ``put_eof_sync`` usa o spill quando a queue esta cheia,
                # entao nunca bloqueia indefinidamente aqui.
                for _ in range(len(partitions)):
                    try:
                        shared_queue.put_eof_sync()
                    except RuntimeError:
                        break  # ja fechada
                consumer_done.wait(timeout=30.0)
                # Limpa arquivos de spill criados durante esta extracao —
                # cobre os 4 caminhos: success, fail, cancel, max_rows.
                shared_queue.cleanup()

            if producer_errors:
                raise producer_errors[0]
            # cancel_event set SEM erros e SEM max_rows: cancelamento real do usuario.
            if (
                cancel_event.is_set()
                and not counters.get("max_rows_reached")
            ):
                import asyncio
                raise asyncio.CancelledError("Extracao SQL cancelada pelo usuario.")

        if streamer.reference is None:
            # Nada foi extraido — devolve um result vazio mas valido.
            return DuckDbExtractionResult(
                pipeline_name=f"shift_extract_{execution_id}_{resource_name}",
                dataset_name="",
                resource_name=_sanitize_jsonl(resource_name),
                table_name=_sanitize_jsonl(resource_name),
                database_path="",
                load_ids=[],
                destination_name="duckdb",
            )

        ref = streamer.reference
        return DuckDbExtractionResult(
            pipeline_name=f"shift_extract_{execution_id}_{resource_name}",
            dataset_name="",  # tabela vai na raiz do DB (sem dataset dlt)
            resource_name=_sanitize_jsonl(resource_name),
            table_name=str(ref["table_name"]),
            database_path=str(ref["database_path"]),
            load_ids=[],
            destination_name="duckdb",
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


# ─── Helpers driver-specific de streaming ────────────────────────────────────


def _server_side_execution_options(conn_type: str, chunk_size: int) -> dict[str, Any]:
    """Devolve as ``execution_options`` para um cursor server-side do driver.

    Compromisso por driver:

    - **postgresql** (psycopg2): ``stream_results=True`` faz o SQLAlchemy abrir
      um *named server-side cursor* — o servidor mantem o cursor e o cliente
      puxa N linhas por fetchmany sem materializar tudo no client side.
    - **oracle** (oracledb/cx_Oracle): ``stream_results=True`` ja roteia para
      ``cursor.fetchmany``; alem disso passamos ``max_row_buffer`` para o
      driver setar ``cursor.arraysize`` no nivel do dialect.
    - **mysql** (pymysql/mysqlclient): ``stream_results=True`` ativa
      ``SSCursor`` (server-side cursor) automaticamente — cliente nao
      buffera o resultado inteiro.
    - **mssql** (pyodbc): ``stream_results=True`` faz fetchmany via cursor
      mas o driver pyodbc nao tem cursor verdadeiramente server-side; ainda
      melhor que default.
    - **firebird**, **sqlite** (e fallback): nao ha cursor server-side
      portavel — devolvemos apenas ``stream_results`` que SQLAlchemy
      transparente em fetchmany.

    O parametro extra ``max_row_buffer`` e usado pelo SA para ajustar
    o ``cursor.arraysize`` no Oracle e o tamanho de buffer interno
    de outros driver_dialects.
    """
    options: dict[str, Any] = {"stream_results": True}
    # ``max_row_buffer`` controla quantas linhas o driver pega por chamada
    # ao banco — bate com nosso chunk_size para evitar trips RTT extras.
    options["max_row_buffer"] = max(1000, chunk_size)
    return options


def _apply_driver_specific_cursor_tweaks(
    raw_cursor: Any,
    conn_type: str,
    chunk_size: int,
) -> None:
    """Tweaks pos-execute que dependem do cursor real do driver.

    - Oracle: ``arraysize`` e ``prefetchrows`` ditam quantas linhas o driver
      busca por roundtrip. Default e 100 — para extracao em massa, queremos
      o tamanho do nosso chunk para minimizar latencia rede.
    - Postgres/MySQL: ``arraysize`` afeta ``fetchmany()`` quando chamado sem
      argumento; nao critico aqui (nos passamos ``chunk_size`` explicitamente)
      mas seta-lo nao machuca.

    Falha silenciosa: se o cursor nao expoe o atributo, ignora — a
    propriedade so existe nos drivers oracledb/cx_Oracle.
    """
    target = max(1000, chunk_size)
    for attr in ("arraysize", "prefetchrows"):
        try:
            current = getattr(raw_cursor, attr, None)
            if current is not None:
                setattr(raw_cursor, attr, target)
        except Exception:  # noqa: BLE001
            pass


# ─── Helpers de particionamento ──────────────────────────────────────────────


class _PartitionAborted(Exception):
    """Sinaliza que o particionamento nao pode ser feito — caller cai
    para single-connection. Erros operacionais reais (driver, sintaxe) se
    propagam normalmente.
    """


def _compute_partitions(
    engine: sa.Engine,
    query: str,
    partition_on: str,
    partition_num: int,
) -> list[tuple[Any, Any, bool]]:
    """Retorna lista de (lo, hi, inclusive_max) cobrindo o intervalo total.

    Faz uma query auxiliar ``SELECT MIN, MAX, COUNT_NULLS FROM (orig) sub``.
    Rejeita coluna nullable — range scan + nulls geram linhas perdidas.

    Tipos suportados: numerico (int/float/Decimal) e temporal (date/datetime).
    Para qualquer outro tipo, levanta ``_PartitionAborted`` para o caller
    cair em single-connection.

    Garantia: as faixas cobrem MIN..MAX sem sobreposicao. A ultima faixa
    usa comparacao inclusiva (``<=``); as anteriores usam ``<``.
    """
    if partition_num < 2:
        return []

    # ``query`` pode terminar com ; — remove para evitar erro de sintaxe.
    base_query = query.rstrip().rstrip(";")
    quoted_col = f'"{partition_on}"'
    bounds_sql = (
        f"SELECT MIN({quoted_col}) AS lo, "
        f"MAX({quoted_col}) AS hi, "
        f"COUNT(*) - COUNT({quoted_col}) AS null_count "
        f"FROM ({base_query}) AS shift_partition_subq"
    )

    with engine.connect() as conn:
        row = conn.execute(sa.text(bounds_sql)).mappings().one()

    lo = row["lo"]
    hi = row["hi"]
    null_count = int(row["null_count"] or 0)

    if lo is None or hi is None:
        raise _PartitionAborted("intervalo vazio")
    if null_count > 0:
        raise _PartitionAborted(
            f"coluna '{partition_on}' contem {null_count} valores NULL — "
            "particionamento exige coluna NOT NULL"
        )

    # Numerico
    if isinstance(lo, (int, float, Decimal)) and isinstance(hi, (int, float, Decimal)):
        return _numeric_ranges(lo, hi, partition_num)

    # Temporal — datetime ou date
    if isinstance(lo, (datetime, date)) and isinstance(hi, (datetime, date)):
        return _temporal_ranges(lo, hi, partition_num)

    raise _PartitionAborted(
        f"tipo nao suportado para particao: {type(lo).__name__} / {type(hi).__name__}"
    )


def _numeric_ranges(
    lo: Any, hi: Any, n: int
) -> list[tuple[Any, Any, bool]]:
    """Divide ``[lo, hi]`` em ``n`` ranges contiguos.

    Devolve ``(start, end, inclusive_end)``. O ultimo range tem
    ``inclusive_end=True`` para incluir o valor exato de ``hi``.
    """
    lo_f = float(lo)
    hi_f = float(hi)
    if hi_f <= lo_f:
        # Range degenerado — usa apenas uma particao inclusiva.
        return [(lo, hi, True)]

    span = hi_f - lo_f
    step = span / n
    ranges: list[tuple[Any, Any, bool]] = []
    for i in range(n):
        a = lo_f + step * i
        b = lo_f + step * (i + 1) if i < n - 1 else hi_f
        # Preserva o tipo numerico original quando possivel.
        if isinstance(lo, int) and isinstance(hi, int):
            a_v: Any = int(a) if i > 0 else int(lo)
            b_v: Any = int(b) if i < n - 1 else int(hi)
        elif isinstance(lo, Decimal) and isinstance(hi, Decimal):
            a_v = Decimal(str(a))
            b_v = Decimal(str(b))
        else:
            a_v = a
            b_v = b
        ranges.append((a_v, b_v, i == n - 1))
    return ranges


def _temporal_ranges(
    lo: Any, hi: Any, n: int
) -> list[tuple[Any, Any, bool]]:
    """Divide um intervalo temporal em ``n`` faixas iguais."""
    if hi <= lo:
        return [(lo, hi, True)]

    span: timedelta = hi - lo
    step = span / n
    ranges: list[tuple[Any, Any, bool]] = []
    for i in range(n):
        a = lo + step * i
        b = lo + step * (i + 1) if i < n - 1 else hi
        ranges.append((a, b, i == n - 1))
    return ranges


def _producer_partition(
    engine: sa.Engine,
    query: str,
    partition_on: str | None,
    lo: Any,
    hi: Any,
    inclusive_max: bool,
    chunk_size: int,
    out_queue: "BoundedChunkQueue",
    cancel_event: threading.Event,
    conn_type: str = "unknown",
) -> None:
    """Worker de uma particao: abre cursor server-side, faz fetchmany e
    empilha listas de dicts em ``out_queue``.

    Sinaliza fim com ``BoundedChunkQueue.EOF`` no final (mesmo em caso de
    erro, para destravar o consumer — o erro se propaga ao caller via
    ``.result()`` do future).
    """
    try:
        # ``lo is None`` sinaliza o caminho fallback (single-connection).
        # Mesmo quando o caller passou ``partition_on``, o caller pode ter
        # caido no fallback (ex: pool capacity=1) — nesse caso a query
        # original e usada sem WHERE adicional.
        if partition_on is None or lo is None or hi is None:
            partition_query = query
            params: dict[str, Any] = {}
        else:
            base = query.rstrip().rstrip(";")
            op_max = "<=" if inclusive_max else "<"
            partition_query = (
                f"SELECT * FROM ({base}) AS shift_partition_sub "
                f'WHERE "{partition_on}" >= :shift_p_lo '
                f'AND "{partition_on}" {op_max} :shift_p_hi'
            )
            params = {"shift_p_lo": lo, "shift_p_hi": hi}

        # Cursor server-side por driver (Tarefa 3): postgres usa named cursor,
        # oracle ajusta arraysize/prefetchrows, mysql ativa SSCursor. Sem isso
        # ``streaming`` e nome — o driver puxa tudo para RAM antes do primeiro
        # chunk em tabelas multi-milhao.
        exec_opts = _server_side_execution_options(conn_type, chunk_size)
        with engine.connect().execution_options(**exec_opts) as conn:
            result = conn.execute(sa.text(partition_query), params)
            # Ajusta o cursor cru do driver (Oracle: arraysize/prefetchrows).
            try:
                raw_cursor = result.cursor
            except AttributeError:
                raw_cursor = None
            if raw_cursor is not None:
                _apply_driver_specific_cursor_tweaks(
                    raw_cursor, conn_type, chunk_size,
                )
            columns = list(result.keys())
            while True:
                if cancel_event.is_set():
                    # Fecha o cursor explicitamente para liberar a conexao
                    # do pool no Oracle/Postgres ao cancelar.
                    result.close()
                    return
                rows_raw = result.fetchmany(chunk_size)
                if not rows_raw:
                    return
                batch = [
                    {col: _serialize_value(val) for col, val in zip(columns, row)}
                    for row in rows_raw
                ]
                # ``put_sync`` no BoundedChunkQueue: bloqueia em backpressure
                # puro (sem spill_dir) ou faz spill em disco (com spill_dir).
                # Em ambos os casos, nunca trava o producer indefinidamente.
                while True:
                    try:
                        out_queue.put_sync(batch, timeout=1.0)
                        break
                    except TimeoutError:
                        if cancel_event.is_set():
                            return
                        continue
                    except RuntimeError:
                        # Queue ja foi fechada — caller cancelou. Encerra.
                        return
    finally:
        # Sempre sinaliza EOF para o consumer (nao quebra se queue fechada).
        try:
            out_queue.put_eof_sync()
        except (RuntimeError, TimeoutError):
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
