"""
Monitor de RAM do processo — evita que um workflow "voador" (ex.: grupo
mal dimensionado num loop) trave a instancia inteira.

Comportamento:

- Loop async que acorda a cada ``MEMORY_MONITOR_INTERVAL_SECONDS`` e le o
  RSS do processo atual via ``psutil``.
- Se o uso ficar acima de ``SHIFT_MAX_EXECUTION_MEMORY_MB`` por
  ``MEMORY_MONITOR_GRACE_TICKS`` leituras consecutivas, cancela a execucao
  mais antiga (via ``execution_registry.oldest_running``).
- Debounce apos cancelar: aguarda ``MEMORY_MONITOR_COOLDOWN_SECONDS``
  antes de eleger a proxima vitima — o GC leva tempo para devolver RAM
  ao SO apos um ``asyncio.CancelledError``.

Nao bloqueia o event loop: ``psutil.Process.memory_info()`` e nao
bloqueante na pratica (le /proc em Linux, Win32 API no Windows).

Starta/para via ``start_memory_monitor()``/``stop_memory_monitor()`` no
lifespan do FastAPI.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.services import execution_registry


logger = get_logger(__name__)

# Intervalo entre amostragens. Valor baixo demais torna o monitor ruidoso
# e pode cancelar picos transitorios de carregamento; alto demais deixa
# o servidor engasgar antes de reagir.
MEMORY_MONITOR_INTERVAL_SECONDS = 5.0

# Numero de amostras consecutivas acima do threshold necessarias para
# acionar cancelamento — evita falso positivo durante spikes de GC.
MEMORY_MONITOR_GRACE_TICKS = 3

# Apos cancelar, espera antes da proxima decisao. Da tempo para o Python
# liberar memoria (asyncio.CancelledError propaga, contextos de
# JsonlStreamer fecham, duckdb unmapea).
MEMORY_MONITOR_COOLDOWN_SECONDS = 30.0


_monitor_task: asyncio.Task | None = None


def _sample_rss_mb() -> float | None:
    """RSS do processo em MB, ou None se psutil indisponivel.

    Mantem isolado num helper para facilitar monkeypatch em testes.
    """
    try:
        import psutil  # noqa: PLC0415

        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        return None


async def _monitor_loop() -> None:
    threshold_mb = float(settings.SHIFT_MAX_EXECUTION_MEMORY_MB)
    if threshold_mb <= 0:
        logger.info("memory_monitor.disabled", reason="threshold<=0")
        return

    if _sample_rss_mb() is None:
        logger.warning(
            "memory_monitor.disabled",
            reason="psutil indisponivel — instale 'psutil' para ativar.",
        )
        return

    logger.info(
        "memory_monitor.started",
        threshold_mb=threshold_mb,
        interval_s=MEMORY_MONITOR_INTERVAL_SECONDS,
        grace_ticks=MEMORY_MONITOR_GRACE_TICKS,
    )

    consecutive_over = 0
    cooldown_until = 0.0

    try:
        while True:
            await asyncio.sleep(MEMORY_MONITOR_INTERVAL_SECONDS)

            rss_mb = _sample_rss_mb()
            if rss_mb is None:
                continue

            if rss_mb < threshold_mb:
                consecutive_over = 0
                continue

            consecutive_over += 1
            logger.warning(
                "memory_monitor.over_threshold",
                rss_mb=round(rss_mb, 1),
                threshold_mb=threshold_mb,
                consecutive=consecutive_over,
            )

            if consecutive_over < MEMORY_MONITOR_GRACE_TICKS:
                continue

            loop_now = asyncio.get_event_loop().time()
            if loop_now < cooldown_until:
                continue

            victim = execution_registry.oldest_running()
            if victim is None:
                # Nenhuma execucao registrada — o vazamento esta fora do
                # escopo do registry (ex.: request sincrono pesado). Nao
                # ha o que cancelar; so logamos.
                logger.error(
                    "memory_monitor.over_threshold_but_no_execution",
                    rss_mb=round(rss_mb, 1),
                )
                # Reseta contador para nao ficar em ruidoso eternamente.
                consecutive_over = 0
                continue

            cancelled = await execution_registry.cancel(victim)
            logger.error(
                "memory_monitor.cancelled_oldest",
                execution_id=str(victim),
                rss_mb=round(rss_mb, 1),
                threshold_mb=threshold_mb,
                cancelled=cancelled,
            )
            consecutive_over = 0
            cooldown_until = loop_now + MEMORY_MONITOR_COOLDOWN_SECONDS
    except asyncio.CancelledError:
        logger.info("memory_monitor.stopped")
        raise


def start_memory_monitor() -> None:
    """Inicia o loop de monitoramento (idempotente)."""
    global _monitor_task
    if _monitor_task is not None and not _monitor_task.done():
        return
    _monitor_task = asyncio.create_task(_monitor_loop(), name="memory-monitor")


async def stop_memory_monitor() -> None:
    """Para o loop e aguarda o termino (idempotente)."""
    global _monitor_task
    task = _monitor_task
    _monitor_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
