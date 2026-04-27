"""
Testes do ``SandboxPool`` — pool de containers Docker pre-aquecidos.

Estrategia
----------
Mockamos ``docker_sandbox.create_warm_container`` para que cada chamada
devolva um ``WarmContainer`` *fake* sem realmente lancar Docker. Os testes
focam em:

- pool nunca reusa container entre acquires (release sempre destroi);
- container morto e substituido pelo healthcheck;
- pre-warm cria N containers idle no start();
- max_size respeitado quando o uso pico esta acima do target;
- metricas (idle/busy gauges + acquire counter) atualizadas;
- bench: warm hit eh ~ordens-de-grandeza mais rapido que cold (mock).

Os criterios de aceitacao do spec que dependem de Docker real (latencia
< 200ms apos warm-up de codigo trivial) sao verificados na suite de
integracao em ``test_docker_sandbox.py`` quando a imagem esta disponivel.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.sandbox import docker_sandbox as ds
from app.services.sandbox.docker_sandbox import SandboxLimits, WarmContainer
from app.services.sandbox.pool import SandboxPool, reset_pools_for_tests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_warm_container(
    image: str = "fake-image:latest",
    *,
    running: bool = True,
) -> WarmContainer:
    """Constroi um WarmContainer fake — usado nos mocks de create."""
    container = MagicMock(name="Container")
    container.id = f"fake-{uuid4().hex[:12]}"
    state = {"Status": "running" if running else "exited"}
    container.attrs = {"State": state}

    def _reload():
        # No fake, o estado nao muda — caso real, container.reload() fala com daemon.
        return None

    container.reload.side_effect = _reload
    container.kill.return_value = None
    container.remove.return_value = None
    socket = MagicMock(name="AttachSocket")
    return WarmContainer(
        container=container,
        socket=socket,
        image=image,
        host_workdir=Path(f"/tmp/fake/{container.id}"),
        host_input_dir=Path(f"/tmp/fake/{container.id}/input"),
    )


@pytest.fixture(autouse=True)
def _reset_pools() -> Any:
    reset_pools_for_tests()
    yield
    reset_pools_for_tests()


# ---------------------------------------------------------------------------
# Pre-warm + acquire/release lifecycle
# ---------------------------------------------------------------------------


class TestPoolLifecycle:
    def test_start_prewarms_target_idle_containers(self):
        with patch(
            "app.services.sandbox.pool.create_warm_container",
            side_effect=lambda *a, **kw: _make_fake_warm_container(),
        ) as mock_create:
            pool = SandboxPool("img:1", target_idle=3, max_size=5)
            pool.start()
            try:
                assert mock_create.call_count == 3
                assert pool.idle_count == 3
                assert pool.busy_count == 0
            finally:
                pool.stop()

    def test_acquire_returns_warm_container(self):
        with patch(
            "app.services.sandbox.pool.create_warm_container",
            side_effect=lambda *a, **kw: _make_fake_warm_container(),
        ):
            pool = SandboxPool("img:1", target_idle=2, max_size=4)
            pool.start()
            try:
                wc = pool.acquire(timeout=1.0)
                assert wc is not None
                assert pool.idle_count == 1
                assert pool.busy_count == 1
                pool.release(wc)
                # release dispara replenishment async — pode levar um instante.
                deadline = time.time() + 2.0
                while pool.idle_count < 2 and time.time() < deadline:
                    time.sleep(0.02)
                assert pool.busy_count == 0
            finally:
                pool.stop()

    def test_release_destroys_and_replenishes(self):
        created: list[WarmContainer] = []
        destroyed: list[str] = []

        def fake_create(*_a, **_kw):
            wc = _make_fake_warm_container()
            created.append(wc)
            return wc

        def fake_destroy(wc):
            destroyed.append(wc.container_id)

        with (
            patch("app.services.sandbox.pool.create_warm_container", side_effect=fake_create),
            patch("app.services.sandbox.pool.destroy_warm_container", side_effect=fake_destroy),
        ):
            pool = SandboxPool("img:1", target_idle=2, max_size=4)
            pool.start()
            try:
                first = pool.acquire(timeout=1.0)
                assert first is not None
                pool.release(first)

                # Aguarda o replenishment.
                deadline = time.time() + 2.0
                while pool.idle_count < 2 and time.time() < deadline:
                    time.sleep(0.02)

                # 1) container retornado foi destruido
                assert first.container_id in destroyed
                # 2) novo container substituto foi criado (3 totais: 2 warm + 1 reposto)
                assert len(created) >= 3
            finally:
                pool.stop()


# ---------------------------------------------------------------------------
# Sem reuso entre execucoes
# ---------------------------------------------------------------------------


class TestNoReuse:
    def test_acquire_release_acquire_returns_different_containers(self):
        """Mesmo apos release, o proximo acquire NAO devolve o mesmo container."""
        with patch(
            "app.services.sandbox.pool.create_warm_container",
            side_effect=lambda *a, **kw: _make_fake_warm_container(),
        ):
            pool = SandboxPool("img:1", target_idle=2, max_size=4)
            pool.start()
            try:
                wc1 = pool.acquire(timeout=1.0)
                assert wc1 is not None
                first_id = wc1.container_id
                pool.release(wc1)

                # Aguarda replenishment para garantir que o pool tem um novo.
                deadline = time.time() + 2.0
                while pool.idle_count < 2 and time.time() < deadline:
                    time.sleep(0.02)

                wc2 = pool.acquire(timeout=1.0)
                assert wc2 is not None
                pool.release(wc2)

                # Mesmo nao reusado: id diferente.
                assert wc2.container_id != first_id
            finally:
                pool.stop()


# ---------------------------------------------------------------------------
# Healthcheck substitui container morto
# ---------------------------------------------------------------------------


class TestHealthcheck:
    def test_dead_idle_container_replaced(self):
        """Container que reporta state.exited e substituido por um vivo."""
        # Dois containers warm: um vivo, um morto.
        live_wc = _make_fake_warm_container(running=True)
        dead_wc = _make_fake_warm_container(running=False)
        replacement_wc = _make_fake_warm_container(running=True)

        creates = iter([live_wc, dead_wc, replacement_wc])

        def fake_create(*_a, **_kw):
            return next(creates)

        destroyed_ids: list[str] = []

        def fake_destroy(wc):
            destroyed_ids.append(wc.container_id)

        with (
            patch("app.services.sandbox.pool.create_warm_container", side_effect=fake_create),
            patch("app.services.sandbox.pool.destroy_warm_container", side_effect=fake_destroy),
        ):
            # Healthcheck rapido para tornar o teste deterministico.
            pool = SandboxPool(
                "img:1",
                target_idle=2,
                max_size=4,
                healthcheck_interval_s=0.05,
            )
            pool.start()
            try:
                # Aguarda o healthcheck rodar pelo menos uma vez.
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    time.sleep(0.05)
                    if dead_wc.container_id in destroyed_ids:
                        break
                assert dead_wc.container_id in destroyed_ids, (
                    "healthcheck deveria ter detectado e destruido o container morto"
                )
                # O pool deve ter substituido — idle volta para >= 2 ou
                # tem o replacement_wc na lista.
                assert pool.idle_count >= 1
            finally:
                pool.stop()


# ---------------------------------------------------------------------------
# Max size + bench mock
# ---------------------------------------------------------------------------


class TestMaxSize:
    def test_acquire_creates_on_demand_up_to_max_size(self):
        """Quando idle vazio mas total < max_size, acquire cria on-demand."""
        with patch(
            "app.services.sandbox.pool.create_warm_container",
            side_effect=lambda *a, **kw: _make_fake_warm_container(),
        ) as mock_create:
            pool = SandboxPool("img:1", target_idle=1, max_size=3)
            pool.start()  # cria 1 idle
            try:
                wc1 = pool.acquire(timeout=1.0)
                wc2 = pool.acquire(timeout=1.0)
                wc3 = pool.acquire(timeout=1.0)
                assert all(w is not None for w in (wc1, wc2, wc3))
                # 1 pre-warm + 2 on-demand = 3 creates totais
                assert mock_create.call_count == 3
                # 4o acquire bloqueia (timeout) porque max_size atingido.
                wc4 = pool.acquire(timeout=0.1)
                assert wc4 is None
            finally:
                if wc1: pool.release(wc1)
                if wc2: pool.release(wc2)
                if wc3: pool.release(wc3)
                pool.stop()


class TestBenchWarmVsCold:
    def test_warm_hit_is_faster_than_cold_create(self):
        """Cold create simula 200ms de latencia; warm hit deve ser <50ms.

        Esta e a essencia do beneficio do pool: a latencia de acquire
        e dominada pelo create no caminho cold e desprezivel no warm.
        """
        cold_latency_ms = 200

        def slow_create(*_a, **_kw):
            time.sleep(cold_latency_ms / 1000.0)
            return _make_fake_warm_container()

        with patch(
            "app.services.sandbox.pool.create_warm_container",
            side_effect=slow_create,
        ):
            pool = SandboxPool("img:1", target_idle=1, max_size=2)
            pool.start()  # paga 200ms de pre-warm
            try:
                # Hit warm: idle ja existe, acquire devolve sem create.
                t0 = time.perf_counter()
                wc = pool.acquire(timeout=2.0)
                warm_ms = (time.perf_counter() - t0) * 1000
                pool.release(wc)
                # Aguarda replenishment.
                deadline = time.time() + 2.0
                while pool.idle_count < 1 and time.time() < deadline:
                    time.sleep(0.01)

                # Bench: warm hit muito menor que o create simulado.
                assert warm_ms < cold_latency_ms / 4, (
                    f"warm hit demorou {warm_ms:.1f}ms — mais que 1/4 do cold"
                )
            finally:
                pool.stop()


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_idle_busy_gauges_track_state(self):
        from app.services.sandbox.pool import _POOL_BUSY, _POOL_IDLE

        with patch(
            "app.services.sandbox.pool.create_warm_container",
            side_effect=lambda *a, **kw: _make_fake_warm_container(),
        ):
            pool = SandboxPool("metrics:1", target_idle=2, max_size=4)
            pool.start()
            try:
                # Apos prewarm: idle=2, busy=0.
                assert _POOL_IDLE.labels("metrics:1")._value.get() == 2
                assert _POOL_BUSY.labels("metrics:1")._value.get() == 0
                wc = pool.acquire(timeout=1.0)
                assert _POOL_IDLE.labels("metrics:1")._value.get() == 1
                assert _POOL_BUSY.labels("metrics:1")._value.get() == 1
                pool.release(wc)
                # Apos release + replenishment: idle volta para 2.
                deadline = time.time() + 2.0
                while (
                    _POOL_IDLE.labels("metrics:1")._value.get() < 2
                    and time.time() < deadline
                ):
                    time.sleep(0.02)
                assert _POOL_IDLE.labels("metrics:1")._value.get() == 2
                assert _POOL_BUSY.labels("metrics:1")._value.get() == 0
            finally:
                pool.stop()

    def test_acquire_outcome_counter_increments(self):
        from app.services.sandbox.pool import _ACQUIRE_RESULT

        with patch(
            "app.services.sandbox.pool.create_warm_container",
            side_effect=lambda *a, **kw: _make_fake_warm_container(),
        ):
            pool = SandboxPool("count:1", target_idle=1, max_size=2)
            pool.start()
            try:
                before_warm = _ACQUIRE_RESULT.labels("count:1", "warm_hit")._value.get()
                wc = pool.acquire(timeout=1.0)
                after_warm = _ACQUIRE_RESULT.labels("count:1", "warm_hit")._value.get()
                assert after_warm == before_warm + 1
                pool.release(wc)
            finally:
                pool.stop()
