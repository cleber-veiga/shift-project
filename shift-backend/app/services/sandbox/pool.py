"""Pool de containers Docker pre-aquecidos para reduzir cold start.

Motivacao
---------
Lancar um container do zero (``create`` + ``start`` + Python interpreter
boot + ``import duckdb``) leva 1-3s. Workflows com muitos ``code_node``
ou alto throughput pagam essa latencia em cada execucao. O pool mantem
N containers idle pre-criados — ``acquire`` devolve um deles e
``release`` o destroi imediatamente, recriando outro warm em background.

Garantia critica de seguranca
-----------------------------
Containers NUNCA sao reusados entre execucoes — release sempre destroi
o container e seu workdir do host. Pool so encurta a latencia de
"create + start"; o isolamento de tenant continua sendo "1 execucao =
1 container descartavel". Isso evita contaminacao via:

- estado em /tmp ou /output (tmpfs do container morre com o container);
- arquivos baixados pelo runner durante uma execucao;
- variaveis no namespace do interpretador (cada container tem o seu).

Limites
-------
O pool so estoca containers com os defaults configurados em
``settings.SANDBOX_DEFAULT_*``. Execucoes que pedem cpu/mem/timeout
diferente caem no cold path (``run_user_code`` cria one-shot). Se a
maioria das chamadas usa defaults, o ganho e proximo de 100%.

Lifecycle
---------
- ``start()``: spawn de N containers warm em paralelo (pre-warm).
- ``acquire(timeout)``: pop do deque idle; se vazio, cria on-demand
  ate ``max_size``; se nao, espera ``timeout`` ou retorna None.
- ``release(wc)``: kill+remove o container, rmtree do workdir, e agenda
  spawn de um substituto se idle < target.
- ``stop()``: kill+remove tudo, mata thread de healthcheck.

Health check
------------
Thread de fundo que a cada ``healthcheck_interval_s`` segundos varre o
deque idle, descarta containers em estado ``exited``/``dead`` e os
substitui. Sem isso, um warm container que crashou (OOM externo, daemon
restart) ficaria no pool ate alguem tentar usar.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Optional

from prometheus_client import Counter, Gauge, Histogram

from app.services.sandbox.docker_sandbox import (
    SandboxLimits,
    WarmContainer,
    create_warm_container,
    destroy_warm_container,
)


logger = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------


_POOL_IDLE = Gauge(
    "sandbox_pool_idle",
    "Containers warm prontos para acquire.",
    ("image",),
)
_POOL_BUSY = Gauge(
    "sandbox_pool_busy",
    "Containers warm em uso (acquired e nao released).",
    ("image",),
)
_ACQUIRE_WAIT_MS = Histogram(
    "sandbox_acquire_wait_ms",
    "Latencia de ``acquire`` em milissegundos (warm hit + miss).",
    ("image",),
    # buckets: 0–1ms (hit warm), 10–100ms, 200ms+ (cold create), 1s+
    buckets=(1, 10, 50, 100, 200, 500, 1000, 2000, 5000),
)
_ACQUIRE_RESULT = Counter(
    "sandbox_acquire_total",
    "Tentativas de acquire categorizadas por resultado.",
    ("image", "outcome"),  # outcome: warm_hit | cold_create | timeout
)
_REPLACED_DEAD = Counter(
    "sandbox_pool_replaced_dead_total",
    "Containers descartados pelo healthcheck por estarem mortos.",
    ("image",),
)


# ---------------------------------------------------------------------------
# Implementacao do pool
# ---------------------------------------------------------------------------


class SandboxPool:
    """Pool warm para uma imagem especifica.

    Threadsafe — todas as operacoes adquirem ``self._lock``. Spawns de
    containers acontecem em workers daemon para nao bloquear acquire.
    """

    def __init__(
        self,
        image: str,
        *,
        target_idle: int = 2,
        max_size: int = 8,
        limits: SandboxLimits | None = None,
        healthcheck_interval_s: float = 30.0,
    ) -> None:
        if target_idle < 0:
            raise ValueError("target_idle deve ser >= 0")
        if max_size < target_idle:
            raise ValueError("max_size deve ser >= target_idle")

        self._image = image
        self._target_idle = target_idle
        self._max_size = max_size
        self._limits = limits or SandboxLimits()
        self._healthcheck_interval_s = healthcheck_interval_s

        self._idle: deque[WarmContainer] = deque()
        self._busy_ids: set[str] = set()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._healthcheck_thread: Optional[threading.Thread] = None
        self._spawning = 0  # contador de containers sendo criados em background

        # Inicializa series para que /metrics ja exiba a label desta imagem.
        _POOL_IDLE.labels(self._image).set(0)
        _POOL_BUSY.labels(self._image).set(0)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Pre-warm + inicia o thread de healthcheck.

        Pre-warm e sincrono so para os primeiros containers, em paralelo
        (cada um e criado em uma thread separada para nao bloquear o boot
        em sequencia ao tempo de start de cada container).
        """
        if self._stop_event.is_set():
            self._stop_event.clear()

        threads: list[threading.Thread] = []
        for _ in range(self._target_idle):
            t = threading.Thread(target=self._spawn_one_safe, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        if self._healthcheck_thread is None or not self._healthcheck_thread.is_alive():
            self._healthcheck_thread = threading.Thread(
                target=self._healthcheck_loop,
                name=f"sandbox-pool-hc-{self._image}",
                daemon=True,
            )
            self._healthcheck_thread.start()

    def stop(self) -> None:
        """Mata todos os containers e para o healthcheck."""
        self._stop_event.set()
        with self._lock:
            self._cond.notify_all()
            idle_snapshot = list(self._idle)
            self._idle.clear()
        for wc in idle_snapshot:
            destroy_warm_container(wc)
        # Threads de spawn em andamento sao deixadas terminar — elas
        # checam ``_stop_event`` antes de inserir no deque.
        if self._healthcheck_thread is not None:
            self._healthcheck_thread.join(timeout=2.0)
            self._healthcheck_thread = None
        _POOL_IDLE.labels(self._image).set(0)
        _POOL_BUSY.labels(self._image).set(0)

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    def acquire(self, timeout: float = 5.0) -> WarmContainer | None:
        """Devolve um container warm pronto para receber stdin.

        Politica:
        1. Se ha um idle, pega imediatamente. ``warm_hit``.
        2. Se total < ``max_size``, cria um on-demand. ``cold_create``.
        3. Caso contrario, espera por release de outra request, ate ``timeout``.

        Retorna ``None`` apos timeout ou se o pool foi parado.
        """
        started = time.perf_counter()
        outcome = "warm_hit"
        try:
            with self._lock:
                while True:
                    if self._stop_event.is_set():
                        return None

                    if self._idle:
                        wc = self._idle.popleft()
                        self._busy_ids.add(wc.container_id)
                        self._refresh_metrics_locked()
                        return wc

                    total = (
                        len(self._idle) + len(self._busy_ids) + self._spawning
                    )
                    if total < self._max_size:
                        # Sai do lock para criar (operacao demorada) e re-entra.
                        self._spawning += 1
                        outcome = "cold_create"
                        self._refresh_metrics_locked()
                        break

                    # Espera por release.
                    if not self._cond.wait(timeout=timeout):
                        outcome = "timeout"
                        return None

            # Cria on-demand (fora do lock).
            try:
                wc = create_warm_container(self._image, self._limits)
            except Exception:  # noqa: BLE001
                with self._lock:
                    self._spawning -= 1
                    self._refresh_metrics_locked()
                raise

            with self._lock:
                self._spawning -= 1
                self._busy_ids.add(wc.container_id)
                self._refresh_metrics_locked()
            return wc
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            _ACQUIRE_WAIT_MS.labels(self._image).observe(elapsed_ms)
            _ACQUIRE_RESULT.labels(self._image, outcome).inc()

    def release(self, wc: WarmContainer) -> None:
        """Destroi o container e dispara replenishment em background."""
        with self._lock:
            self._busy_ids.discard(wc.container_id)
            self._refresh_metrics_locked()

        # Destroy fora do lock — chamada bloqueante.
        destroy_warm_container(wc)

        # Replenishment ate target. Spawns concorrentes sao raros porque
        # apenas N (target) acoes de release simultaneas vao caber sob o
        # contador ``_spawning``.
        if not self._stop_event.is_set():
            with self._lock:
                deficit = self._target_idle - (len(self._idle) + self._spawning)
                if deficit > 0:
                    self._spawning += 1
                    self._refresh_metrics_locked()
                    spawn = True
                else:
                    spawn = False
            if spawn:
                t = threading.Thread(
                    target=self._spawn_replenish,
                    name=f"sandbox-pool-replenish-{self._image}",
                    daemon=True,
                )
                t.start()

    @property
    def idle_count(self) -> int:
        with self._lock:
            return len(self._idle)

    @property
    def busy_count(self) -> int:
        with self._lock:
            return len(self._busy_ids)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refresh_metrics_locked(self) -> None:
        _POOL_IDLE.labels(self._image).set(len(self._idle))
        _POOL_BUSY.labels(self._image).set(len(self._busy_ids))

    def _spawn_one_safe(self) -> None:
        """Versao silenciosa do create — usada no pre-warm."""
        if self._stop_event.is_set():
            return
        try:
            wc = create_warm_container(self._image, self._limits)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sandbox.pool.prewarm_failed",
                extra={"image": self._image, "error": str(exc)},
            )
            return
        with self._lock:
            if self._stop_event.is_set():
                # Pool foi parado durante o spawn — destroi e sai.
                destroy_warm_container(wc)
                return
            self._idle.append(wc)
            self._refresh_metrics_locked()
            self._cond.notify()

    def _spawn_replenish(self) -> None:
        """Cria 1 container em background apos um release; respeita stop()."""
        try:
            wc = create_warm_container(self._image, self._limits)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sandbox.pool.replenish_failed",
                extra={"image": self._image, "error": str(exc)},
            )
            with self._lock:
                self._spawning -= 1
                self._refresh_metrics_locked()
            return
        with self._lock:
            self._spawning -= 1
            if self._stop_event.is_set():
                destroy_warm_container(wc)
                self._refresh_metrics_locked()
                return
            self._idle.append(wc)
            self._refresh_metrics_locked()
            self._cond.notify()

    def _healthcheck_loop(self) -> None:
        """Periodicamente: descarta idle morto e repoe."""
        while not self._stop_event.wait(self._healthcheck_interval_s):
            try:
                self._healthcheck_once()
            except Exception:  # noqa: BLE001
                logger.exception("sandbox.pool.healthcheck_iteration_failed")

    def _healthcheck_once(self) -> None:
        with self._lock:
            current_idle = list(self._idle)

        dead: list[WarmContainer] = []
        for wc in current_idle:
            if not _is_running(wc):
                dead.append(wc)

        if not dead:
            return

        with self._lock:
            for wc in dead:
                try:
                    self._idle.remove(wc)
                except ValueError:
                    pass
            self._refresh_metrics_locked()

        for wc in dead:
            _REPLACED_DEAD.labels(self._image).inc()
            destroy_warm_container(wc)
            # Reposicao sincrona aqui — healthcheck e periodico,
            # nao precisa pular para outra thread.
            with self._lock:
                if self._stop_event.is_set():
                    return
                # Conta apenas idle + spawning para nao ultrapassar target.
                if len(self._idle) + self._spawning >= self._target_idle:
                    continue
                self._spawning += 1
            try:
                replacement = create_warm_container(self._image, self._limits)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "sandbox.pool.healthcheck_spawn_failed",
                    extra={"image": self._image},
                )
                with self._lock:
                    self._spawning -= 1
                    self._refresh_metrics_locked()
                continue
            with self._lock:
                self._spawning -= 1
                if self._stop_event.is_set():
                    destroy_warm_container(replacement)
                    self._refresh_metrics_locked()
                    return
                self._idle.append(replacement)
                self._refresh_metrics_locked()
                self._cond.notify()


def _is_running(wc: WarmContainer) -> bool:
    """Verifica se o container ainda esta em estado ``running``."""
    try:
        wc.container.reload()
        status = (wc.container.attrs or {}).get("State", {}).get("Status", "")
        return status == "running"
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Singleton por imagem (registro global)
# ---------------------------------------------------------------------------


_pools_lock = threading.Lock()
_pools: dict[str, SandboxPool] = {}


def get_pool(image: str) -> SandboxPool | None:
    """Devolve o pool da imagem se ja registrado, senao ``None``.

    Esta funcao NAO cria pool sob demanda — quem cria e ``init_default_pool``
    no boot do servico. Falhar silenciosamente aqui evita penalizar a
    primeira execucao com a inicializacao do pool.
    """
    with _pools_lock:
        return _pools.get(image)


def init_default_pool() -> SandboxPool | None:
    """Inicializa o pool padrao a partir das settings.

    Chamado no lifespan do FastAPI. Quando ``SANDBOX_ENABLED=False`` ou
    docker indisponivel, retorna None sem propagar excecao.
    """
    from app.core.config import settings

    if not getattr(settings, "SANDBOX_ENABLED", False):
        return None
    if not getattr(settings, "SANDBOX_POOL_ENABLED", True):
        return None

    image = settings.SANDBOX_IMAGE
    target_idle = getattr(settings, "SANDBOX_POOL_TARGET_IDLE", 2)
    max_size = getattr(settings, "SANDBOX_POOL_MAX_SIZE", 8)
    healthcheck_s = getattr(settings, "SANDBOX_POOL_HEALTHCHECK_INTERVAL_S", 30.0)

    pool = SandboxPool(
        image,
        target_idle=target_idle,
        max_size=max_size,
        healthcheck_interval_s=healthcheck_s,
    )
    try:
        pool.start()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sandbox.pool.init_failed",
            extra={"image": image, "error": str(exc)},
        )
        return None

    with _pools_lock:
        _pools[image] = pool
    return pool


def stop_all_pools() -> None:
    """Mata todos os pools registrados — chamado no shutdown."""
    with _pools_lock:
        snapshot = list(_pools.values())
        _pools.clear()
    for pool in snapshot:
        try:
            pool.stop()
        except Exception:  # noqa: BLE001
            logger.exception("sandbox.pool.stop_failed")


def reset_pools_for_tests() -> None:
    """Reseta o registro global — util em test fixtures."""
    with _pools_lock:
        snapshot = list(_pools.values())
        _pools.clear()
    for pool in snapshot:
        try:
            pool.stop()
        except Exception:  # noqa: BLE001
            pass
