"""
Testes de cursor server-side por driver (Tarefa 3 do prompt de fechamento).

Cobre
-----
- ``_server_side_execution_options(conn_type, chunk_size)`` retorna
  ``stream_results=True`` + ``max_row_buffer`` adequado para todos os
  dialetos suportados.
- ``_apply_driver_specific_cursor_tweaks`` seta ``arraysize`` e
  ``prefetchrows`` quando o cursor cru do driver os suporta (Oracle); no-op
  silencioso para drivers que nao expoem (Postgres/MySQL).
- ``_producer_partition`` chama ``execution_options`` com o conjunto correto
  por driver, e aplica os tweaks no cursor.
- Streaming nao pre-buffera o resultado completo: usando um Connection
  fake que devolve um *generator lazy*, validamos que apos N
  ``fetchmany(chunk_size)`` chamadas, apenas N*chunk_size linhas foram
  consumidas do generator — o resto permanece "no servidor" (lazy).

A integracao real (Postgres/Oracle/MySQL) esta na suite ``@pytest.mark.postgres``
quando rodada contra DB; aqui, isolamos a logica de driver-specific via mocks.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.extraction_service import (
    _apply_driver_specific_cursor_tweaks,
    _producer_partition,
    _server_side_execution_options,
)
from app.services.streaming.bounded_chunk_queue import BoundedChunkQueue


# ---------------------------------------------------------------------------
# _server_side_execution_options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "conn_type",
    ["postgresql", "oracle", "mysql", "sqlserver", "firebird", "sqlite", "unknown"],
)
def test_execution_options_always_set_stream_results(conn_type: str):
    opts = _server_side_execution_options(conn_type, chunk_size=50_000)
    assert opts["stream_results"] is True
    # max_row_buffer e propagado ao dialect (afeta Oracle arraysize, etc).
    assert opts["max_row_buffer"] >= 50_000


def test_execution_options_min_buffer_1000():
    """Mesmo chunk_size pequeno, max_row_buffer nao desce de 1000 — driver
    com arraysize=10 default deixaria a leitura inutilmente lenta."""
    opts = _server_side_execution_options("oracle", chunk_size=10)
    assert opts["max_row_buffer"] >= 1000


# ---------------------------------------------------------------------------
# _apply_driver_specific_cursor_tweaks
# ---------------------------------------------------------------------------


class TestCursorTweaks:
    def test_oracle_cursor_gets_arraysize_and_prefetchrows(self):
        """Cursor com ``arraysize`` e ``prefetchrows`` (oracledb / cx_Oracle)
        e atualizado para max(1000, chunk_size)."""
        cur = MagicMock()
        # Define os atributos nao-None — getattr ira retorna-los.
        cur.arraysize = 100
        cur.prefetchrows = 0
        _apply_driver_specific_cursor_tweaks(cur, "oracle", chunk_size=50_000)
        assert cur.arraysize == 50_000
        assert cur.prefetchrows == 50_000

    def test_postgres_cursor_no_arraysize_attr_is_no_op(self):
        """Cursor sem ``arraysize`` (alguns wrappers do psycopg) ou com None
        nao quebra — getattr devolve None e o helper pula."""
        # MagicMock auto-cria atributos; precisamos forcar AttributeError
        # com spec=[]
        cur = MagicMock(spec=[])
        # Nao deve levantar.
        _apply_driver_specific_cursor_tweaks(cur, "postgresql", chunk_size=10_000)

    def test_mysql_arraysize_set_when_present(self):
        cur = MagicMock()
        cur.arraysize = 1
        # mysqlclient nao tem prefetchrows — simula
        del cur.prefetchrows
        _apply_driver_specific_cursor_tweaks(cur, "mysql", chunk_size=10_000)
        assert cur.arraysize == 10_000


# ---------------------------------------------------------------------------
# _producer_partition: integra o helper de execution_options + cursor tweaks
# ---------------------------------------------------------------------------


def _build_fake_engine(*, fetch_chunks: list[list[tuple]], cursor: MagicMock):
    """Constroi engine + connect-context-manager fake.

    ``fetch_chunks`` define o que ``result.fetchmany`` devolvera em chamadas
    sucessivas — ultima entrada deve ser ``[]`` (EOF).
    """
    result = MagicMock()
    result.keys.return_value = ["id", "name"]
    result.cursor = cursor
    result.fetchmany.side_effect = fetch_chunks + [[]]
    result.close.return_value = None

    conn = MagicMock()
    conn.execute.return_value = result
    conn.execution_options.return_value = conn

    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = None

    engine = MagicMock()
    engine.connect.return_value.execution_options.return_value = cm
    return engine, conn, result


@pytest.mark.parametrize("conn_type", ["postgresql", "oracle", "mysql"])
def test_producer_uses_stream_results_per_driver(conn_type: str):
    """Para cada driver, ``execution_options(stream_results=True, max_row_buffer=...)``
    e chamada antes do execute. Isso prova que o producer nao usa o
    fluxo bufferizado default."""
    cursor = MagicMock(arraysize=10, prefetchrows=0)
    engine, conn, _result = _build_fake_engine(
        fetch_chunks=[[(1, "a"), (2, "b")]],
        cursor=cursor,
    )

    q = BoundedChunkQueue(maxsize=4, execution_id=f"prod-{conn_type}")
    cancel = threading.Event()
    try:
        _producer_partition(
            engine=engine,
            query="SELECT id, name FROM t",
            partition_on=None,
            lo=None,
            hi=None,
            inclusive_max=True,
            chunk_size=50_000,
            out_queue=q,
            cancel_event=cancel,
            conn_type=conn_type,
        )
    finally:
        q.cleanup()

    # Verifica que execution_options foi chamada com stream_results=True.
    # Precisa olhar nas chamadas em engine.connect().execution_options(...)
    call_args_list = engine.connect.return_value.execution_options.call_args_list
    assert len(call_args_list) >= 1
    kwargs = call_args_list[0].kwargs or {}
    assert kwargs.get("stream_results") is True
    assert kwargs.get("max_row_buffer", 0) >= 50_000


def test_producer_applies_oracle_cursor_tweaks():
    """No driver Oracle, o cursor recebe arraysize = chunk_size apos o execute."""
    cursor = MagicMock()
    cursor.arraysize = 100
    cursor.prefetchrows = 0
    engine, _conn, _result = _build_fake_engine(
        fetch_chunks=[[(1,)]],
        cursor=cursor,
    )

    q = BoundedChunkQueue(maxsize=4, execution_id="prod-oracle-tweak")
    try:
        _producer_partition(
            engine=engine,
            query="SELECT 1 FROM dual",
            partition_on=None,
            lo=None,
            hi=None,
            inclusive_max=True,
            chunk_size=20_000,
            out_queue=q,
            cancel_event=threading.Event(),
            conn_type="oracle",
        )
    finally:
        q.cleanup()

    assert cursor.arraysize == 20_000
    assert cursor.prefetchrows == 20_000


# ---------------------------------------------------------------------------
# Nao-buferizacao: lazy generator
# ---------------------------------------------------------------------------


def test_streaming_does_not_consume_generator_eagerly():
    """Validames que o producer chama ``fetchmany(chunk_size)`` repetidamente
    em vez de pedir tudo de uma vez.

    Implementamos um ``result.fetchmany`` que conta quantas linhas foram
    realmente puxadas de um generator de 1M. Apos consumir 3 chunks de
    50k, devem ter sido puxadas exatamente 3*50k linhas — nao 1M.
    """
    LARGE = 1_000_000
    CHUNK = 50_000
    consumed_count = {"n": 0}

    def gen() -> Any:
        for i in range(LARGE):
            yield (i, f"row_{i}")

    g = gen()

    def fetchmany(n: int) -> list[tuple]:
        rows: list[tuple] = []
        for _ in range(n):
            try:
                rows.append(next(g))
                consumed_count["n"] += 1
            except StopIteration:
                break
        return rows

    cursor = MagicMock()
    cursor.arraysize = CHUNK
    cursor.prefetchrows = CHUNK
    result = MagicMock()
    result.keys.return_value = ["id", "name"]
    result.cursor = cursor
    result.fetchmany.side_effect = fetchmany

    conn = MagicMock()
    conn.execute.return_value = result
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = None
    engine = MagicMock()
    engine.connect.return_value.execution_options.return_value = cm

    q = BoundedChunkQueue(maxsize=4, execution_id="lazy", spill_dir=None)
    cancel = threading.Event()

    # Roda em thread; consumer cancela apos 3 chunks.
    t = threading.Thread(
        target=_producer_partition,
        args=(
            engine, "SELECT 1", None, None, None, True, CHUNK,
            q, cancel, "postgresql",
        ),
        daemon=True,
    )
    t.start()

    chunks_seen = 0
    while chunks_seen < 3:
        item = q.get_sync(timeout=5.0)
        if item == BoundedChunkQueue.EOF:
            break
        chunks_seen += 1
    cancel.set()
    t.join(timeout=5.0)
    q.cleanup()

    # Apos 3 chunks consumidos, o generator NAO deve ter sido esgotado.
    # O numero de linhas puxadas e proximo de 3*CHUNK (pode haver +CHUNK
    # em flight no producer dentro do put bloqueado).
    assert consumed_count["n"] < LARGE, (
        f"generator esgotado ({consumed_count['n']} de {LARGE}) — "
        "fetchmany puxou tudo de uma vez (sem streaming)."
    )
    assert consumed_count["n"] >= 3 * CHUNK
    assert consumed_count["n"] <= 5 * CHUNK, (
        f"buffer alem do esperado ({consumed_count['n']}) — backpressure "
        "nao esta funcionando."
    )
