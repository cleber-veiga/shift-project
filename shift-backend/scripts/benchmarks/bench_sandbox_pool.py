"""Benchmark de latencia de execucao de code_node (Fase 2.2).

Critério de aceitação da Fase 2.2: cold start ~2s, warm hit < 200ms.

Uso
---
::

    cd kernel-runtime && docker build -t shift-kernel-runtime:latest .
    cd ../shift-backend
    python scripts/benchmarks/bench_sandbox_pool.py

Configuracoes
-------------
- Cenario A — pool DESLIGADO: ``run_user_code(use_pool=False)`` em loop.
  Cada chamada paga ``create + start + python init + import duckdb``.
- Cenario B — pool LIGADO (target_idle=2): ``acquire`` retorna container
  ja inicializado; latencia dominada por ``stdin write + wait + extract``.

Ambos cenarios executam 100 vezes o mesmo codigo trivial:
``print('hello'); result = []`` (sem input parquet).

Reporta p50, p95, p99 de cada cenario. Skipped se daemon Docker indisponivel.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import Iterable


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


async def _bench_cold(n: int) -> list[float]:
    from app.services.sandbox import SandboxLimits, run_user_code

    samples: list[float] = []
    for i in range(n):
        t0 = time.perf_counter()
        result = await run_user_code(
            code="print('hello'); result = []",
            input_table=None,
            limits=SandboxLimits(timeout_s=30),
            execution_id=f"bench-cold-{i}",
            use_pool=False,
        )
        elapsed = time.perf_counter() - t0
        if not result.success:
            print(f"  iteration {i}: failed — {result.stderr[:200]}")
        samples.append(elapsed)
        print(f"  cold {i+1}/{n}: {elapsed*1000:.0f}ms", flush=True)
    return samples


async def _bench_warm(n: int) -> list[float]:
    from app.services.sandbox import SandboxLimits, run_user_code
    from app.services.sandbox.pool import init_default_pool, stop_all_pools

    # Forca settings para garantir pool ligado
    pool = init_default_pool()
    if pool is None:
        # init_default_pool retorna None quando SANDBOX_ENABLED=False; em
        # bench, criamos manualmente.
        from app.services.sandbox.pool import SandboxPool
        pool = SandboxPool(
            "shift-kernel-runtime:latest",
            target_idle=2, max_size=4,
        )
        pool.start()
        from app.services.sandbox.pool import _pools, _pools_lock
        with _pools_lock:
            _pools["shift-kernel-runtime:latest"] = pool

    try:
        samples: list[float] = []
        for i in range(n):
            t0 = time.perf_counter()
            result = await run_user_code(
                code="print('hello'); result = []",
                input_table=None,
                limits=SandboxLimits(timeout_s=30),
                execution_id=f"bench-warm-{i}",
                use_pool=True,
            )
            elapsed = time.perf_counter() - t0
            if not result.success:
                print(f"  iteration {i}: failed — {result.stderr[:200]}")
            samples.append(elapsed)
            print(f"  warm {i+1}/{n}: {elapsed*1000:.0f}ms", flush=True)
        return samples
    finally:
        stop_all_pools()


def _summarize(label: str, samples: list[float]) -> None:
    if not samples:
        print(f"{label}: nao houve amostras.")
        return
    ms = [s * 1000 for s in samples]
    print(f"\n{label}:")
    print(f"  count : {len(ms)}")
    print(f"  p50   : {_percentile(ms, 0.50):.0f}ms")
    print(f"  p95   : {_percentile(ms, 0.95):.0f}ms")
    print(f"  p99   : {_percentile(ms, 0.99):.0f}ms")
    print(f"  min   : {min(ms):.0f}ms")
    print(f"  max   : {max(ms):.0f}ms")
    print(f"  mean  : {statistics.mean(ms):.0f}ms")


async def _amain(n: int) -> None:
    print(f"=== Cenario A — pool DESLIGADO ({n} iteracoes) ===")
    cold = await _bench_cold(n)
    _summarize("COLD", cold)

    print(f"\n=== Cenario B — pool LIGADO ({n} iteracoes) ===")
    warm = await _bench_warm(n)
    _summarize("WARM", warm)

    if cold and warm:
        ratio = statistics.median(cold) / statistics.median(warm)
        print(f"\nSpeedup mediano (cold/warm): {ratio:.1f}x")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    args = parser.parse_args()

    try:
        import docker
        client = docker.from_env()
        client.ping()
        client.images.get("shift-kernel-runtime:latest")
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP: docker indisponivel ou imagem ausente — {exc}")
        return

    asyncio.run(_amain(args.n))


if __name__ == "__main__":
    main()
