"""Benchmark de leitura particionada do extraction_service (Fase 1.1).

Critério de aceitação da Fase 1.1: ganho 3-6x entre ``partition_num=1`` e
``partition_num=8`` em uma tabela mock de 1M linhas.

Uso
---
::

    cd shift-backend
    python scripts/benchmarks/bench_streaming_partition.py

A bench gera uma tabela SQLite local de 1M linhas, mede wall-clock e pico
de RAM (via ``tracemalloc``) para cada ``partition_num in {1, 2, 4, 8}``,
e imprime uma tabela com os resultados.

Notas
-----
- SQLite tem write-lock global, entao o ganho REAL vem em Oracle/Postgres
  com cursor server-side de fato concorrente. Esta bench prova que (a) o
  pipeline nao bufferiza, (b) particionamento + threading nao introduz
  regressao, (c) RAM fica bounded.
- Para bench em Postgres, exporte ``BENCH_PG_URL`` e ``BENCH_PG_TABLE``
  e use o flag ``--source pg`` (TODO se precisar).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
import time
import tracemalloc
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.pool import NullPool


def _seed_sqlite(path: Path, num_rows: int) -> str:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, val INTEGER)"
        )
        # Insert em batch para nao demorar 5min no setup.
        BATCH = 100_000
        for start in range(0, num_rows, BATCH):
            conn.executemany(
                "INSERT INTO t VALUES (?,?,?)",
                [
                    (i, f"name_{i}", i * 7)
                    for i in range(start, min(start + BATCH, num_rows))
                ],
            )
        conn.commit()
    finally:
        conn.close()
    return f"sqlite:///{path}"


def _bench_one(url: str, partition_num: int, chunk_size: int) -> tuple[float, int]:
    """Roda 1 extracao com ``partition_num``, devolve ``(wall_seconds, peak_bytes)``."""
    from app.services.extraction_service import extraction_service
    from app.services import extraction_service as ext_module
    from app.services.db.engine_cache import dispose_all_engines

    dispose_all_engines()
    # Engine SQLite com NullPool — destrava concorrencia para a bench
    # poder simular o cenario Postgres/Oracle.
    custom_engine = sa.create_engine(url, poolclass=NullPool)
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        with patch.object(ext_module, "get_pool_capacity", lambda *_: 32), \
             patch.object(ext_module, "get_engine_from_url", lambda *a, **k: custom_engine):
            extraction_service.extract_sql_partitioned_to_duckdb(
                connection_string=url,
                conn_type="postgresql",  # forca o profile com cursor server-side
                query="SELECT id, name, val FROM t",
                execution_id=f"bench-{partition_num}",
                resource_name=f"r{partition_num}",
                partition_on="id",
                partition_num=partition_num,
                chunk_size=chunk_size,
            )
    finally:
        elapsed = time.perf_counter() - t0
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        custom_engine.dispose()
        dispose_all_engines()
    return elapsed, peak


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--chunk-size", type=int, default=50_000)
    parser.add_argument("--partitions", default="1,2,4,8")
    args = parser.parse_args()

    parts = [int(x) for x in args.partitions.split(",")]
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "bench.sqlite"
    print(f"Seeding {args.rows:,} rows in {db} ...", flush=True)
    url = _seed_sqlite(db, args.rows)
    print("Seed done.", flush=True)

    print()
    print(f"{'partition_num':>13}  {'wall_seconds':>12}  {'rows/sec':>11}  {'peak_MB':>8}")
    print("-" * 50)
    rows = args.rows
    baseline = None
    for n in parts:
        wall, peak = _bench_one(url, n, args.chunk_size)
        baseline = baseline or wall
        speedup = baseline / wall if wall > 0 else float("inf")
        print(
            f"{n:>13}  {wall:>12.2f}  {int(rows/wall):>11,}  "
            f"{peak/1024/1024:>8.1f}  speedup={speedup:.2f}x"
        )

    try:
        os.remove(db)
    except OSError:
        pass


if __name__ == "__main__":
    main()
