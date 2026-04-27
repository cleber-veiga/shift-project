"""
Testes do ``BoundedChunkQueue`` — bounded RAM + spillover em disco.

Cobre:
- Backpressure puro: producer rapido + consumer lento -> RAM nunca passa de
  ``maxsize``.
- Spillover preserva ordem FIFO mesmo com chunks indo/voltando do disco.
- ``cleanup`` apaga todos os arquivos de spill (sem leak).
- ``cleanup_execution_spill`` (modulo) limpa spill orfao por execution_id.
- Threshold de spill emite WARN apenas uma vez.
- Stress: muitos chunks, RAM bounded, spill controlado.
- API async funciona (wrapper sobre to_thread).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.services.streaming.bounded_chunk_queue import (
    BoundedChunkQueue,
    cleanup_execution_spill,
)


# ---------------------------------------------------------------------------
# Backpressure puro (sem spill_dir)
# ---------------------------------------------------------------------------


class TestBackpressurePure:
    def test_put_blocks_when_full_without_spill(self):
        q = BoundedChunkQueue(maxsize=2, execution_id="bp-pure")
        q.put_sync({"id": 1})
        q.put_sync({"id": 2})
        assert q.depth == 2

        # Terceiro put deve bloquear — verificamos via timeout curto.
        with pytest.raises(TimeoutError):
            q.put_sync({"id": 3}, timeout=0.05)

        # Apos consumir um, ha espaco e o put passa.
        first = q.get_sync()
        assert first == {"id": 1}
        q.put_sync({"id": 3}, timeout=0.05)
        assert q.depth == 2
        q.cleanup()

    def test_producer_fast_consumer_slow_keeps_ram_bounded(self):
        """RAM nunca passa de maxsize, independente da velocidade do consumer."""
        q = BoundedChunkQueue(maxsize=4, execution_id="bp-slow-cons")
        produced = list(range(200))
        consumed: list[int] = []

        def producer() -> None:
            for n in produced:
                q.put_sync({"n": n})
            q.put_eof_sync()

        peak = {"depth": 0}
        peak_lock = threading.Lock()

        def consumer() -> None:
            while True:
                # Atrasa o consumer para forcar fila a encher.
                time.sleep(0.001)
                item = q.get_sync()
                if item == BoundedChunkQueue.EOF:
                    return
                consumed.append(item["n"])
                with peak_lock:
                    peak["depth"] = max(peak["depth"], q.depth)

        # Sample a profundidade enquanto roda — uma terceira thread.
        sampler_stop = threading.Event()

        def sampler() -> None:
            while not sampler_stop.is_set():
                with peak_lock:
                    peak["depth"] = max(peak["depth"], q.depth)
                time.sleep(0.0005)

        t_p = threading.Thread(target=producer)
        t_c = threading.Thread(target=consumer)
        t_s = threading.Thread(target=sampler, daemon=True)
        t_s.start()
        t_p.start()
        t_c.start()
        t_p.join(timeout=10)
        t_c.join(timeout=10)
        sampler_stop.set()

        assert consumed == produced
        assert peak["depth"] <= 4, f"RAM passou de maxsize: {peak['depth']}"
        q.cleanup()


# ---------------------------------------------------------------------------
# Spillover
# ---------------------------------------------------------------------------


class TestSpillover:
    def test_spill_preserves_fifo_order(self, tmp_path: Path):
        q = BoundedChunkQueue(
            maxsize=2,
            execution_id="spill-order",
            spill_dir=tmp_path / "spill",
        )
        # Empilha 6 chunks com queue de 2 -> 4 vao para disco.
        for i in range(6):
            q.put_sync({"i": i})
        assert q.spilled_total == 4
        assert q.spill_active <= 4

        # Consome — deve sair na mesma ordem em que foi inserido.
        recovered = []
        for _ in range(6):
            recovered.append(q.get_sync())
        assert [c["i"] for c in recovered] == list(range(6))
        # Nao restou spill em disco apos consumir tudo.
        assert q.spill_active == 0
        q.cleanup()

    def test_cleanup_removes_spill_files(self, tmp_path: Path):
        spill_dir = tmp_path / "spill"
        q = BoundedChunkQueue(
            maxsize=1, execution_id="spill-clean", spill_dir=spill_dir,
        )
        for i in range(5):
            q.put_sync({"i": i})

        files_before = list(spill_dir.glob("*.spill"))
        assert len(files_before) >= 1, "spill deveria ter criado arquivos"

        q.cleanup()
        files_after = list(spill_dir.glob("*.spill"))
        assert files_after == [], f"sobrou {files_after} apos cleanup"

    def test_context_manager_runs_cleanup(self, tmp_path: Path):
        spill_dir = tmp_path / "spill"
        with BoundedChunkQueue(
            maxsize=1, execution_id="ctxmgr", spill_dir=spill_dir,
        ) as q:
            for i in range(3):
                q.put_sync({"i": i})
            assert q.spilled_total == 2
        # Saiu do with — cleanup roda.
        assert list(spill_dir.glob("*.spill")) == []

    def test_module_cleanup_helper_removes_orphans(self, tmp_path: Path):
        spill_dir = tmp_path / "spill"
        q = BoundedChunkQueue(
            maxsize=1, execution_id="orphan-1", spill_dir=spill_dir,
        )
        for i in range(3):
            q.put_sync({"i": i})
        # Simulamos crash do caller: nao chamamos cleanup.
        del q
        files_before = list(spill_dir.glob("chunk_orphan-1_*.spill"))
        assert len(files_before) >= 1

        removed = cleanup_execution_spill("orphan-1", spill_dir)
        assert removed >= 1
        assert list(spill_dir.glob("chunk_orphan-1_*.spill")) == []

    def test_spill_threshold_warns_once(self, tmp_path: Path, caplog):
        with caplog.at_level(logging.WARNING):
            q = BoundedChunkQueue(
                maxsize=1,
                execution_id="warn-once",
                spill_dir=tmp_path / "spill",
                spill_warn_threshold=3,
            )
            for i in range(10):
                q.put_sync({"i": i})
            q.cleanup()

        threshold_warnings = [
            r for r in caplog.records
            if "spill_threshold_exceeded" in r.message
        ]
        assert len(threshold_warnings) == 1, (
            f"esperado exatamente 1 warning, recebeu {len(threshold_warnings)}"
        )


# ---------------------------------------------------------------------------
# Cancelamento
# ---------------------------------------------------------------------------


class TestCancel:
    def test_close_destravels_pending_get(self):
        q = BoundedChunkQueue(maxsize=2, execution_id="close-get")

        result: dict[str, Any] = {}

        def consumer() -> None:
            try:
                result["chunk"] = q.get_sync(timeout=2.0)
            except (TimeoutError, RuntimeError) as exc:
                result["err"] = type(exc).__name__

        t = threading.Thread(target=consumer)
        t.start()
        time.sleep(0.05)
        q.close()
        t.join(timeout=2.0)
        assert result.get("err") == "RuntimeError"

    def test_close_destravels_pending_put_no_spill(self):
        q = BoundedChunkQueue(maxsize=1, execution_id="close-put")
        q.put_sync({"i": 0})  # enche

        result: dict[str, Any] = {}

        def producer() -> None:
            try:
                q.put_sync({"i": 1}, timeout=2.0)
                result["ok"] = True
            except (TimeoutError, RuntimeError) as exc:
                result["err"] = type(exc).__name__

        t = threading.Thread(target=producer)
        t.start()
        time.sleep(0.05)
        q.close()
        t.join(timeout=2.0)
        assert result.get("err") == "RuntimeError"

    def test_cleanup_after_cancel_removes_spill(self, tmp_path: Path):
        spill_dir = tmp_path / "spill"
        q = BoundedChunkQueue(
            maxsize=1, execution_id="cancel-leak", spill_dir=spill_dir,
        )
        for i in range(5):
            q.put_sync({"i": i})
        # Cancelamento simulado: close + cleanup nos paths success/fail/cancel.
        q.close()
        q.cleanup()
        assert list(spill_dir.glob("*.spill")) == []


# ---------------------------------------------------------------------------
# Async API
# ---------------------------------------------------------------------------


class TestAsyncApi:
    @pytest.mark.asyncio
    async def test_async_put_get_roundtrip(self):
        q = BoundedChunkQueue(maxsize=2, execution_id="async")
        await q.put({"x": 1})
        await q.put({"x": 2})
        a = await q.get()
        b = await q.get()
        assert (a["x"], b["x"]) == (1, 2)
        await asyncio.to_thread(q.cleanup)


# ---------------------------------------------------------------------------
# Stress — muitos chunks com RAM constante
# ---------------------------------------------------------------------------


class TestStress:
    def test_stress_thousand_chunks_with_low_ram(self, tmp_path: Path):
        """1k chunks de ~1KB cada, RAM = 4 chunks. Spill assume o resto."""
        q = BoundedChunkQueue(
            maxsize=4,
            execution_id="stress",
            spill_dir=tmp_path / "spill",
            spill_warn_threshold=10_000,  # silencia warning de threshold
        )
        N = 1_000
        chunk_payload = [{"key": "v" * 100} for _ in range(10)]  # ~1KB

        peak_ram = {"d": 0}
        lock = threading.Lock()

        def producer() -> None:
            for i in range(N):
                q.put_sync({"id": i, "rows": chunk_payload})
                with lock:
                    peak_ram["d"] = max(peak_ram["d"], q.depth)
            q.put_eof_sync()

        consumed: list[int] = []

        def consumer() -> None:
            while True:
                # Lento de proposito: forca acumulo.
                if len(consumed) % 100 == 0:
                    time.sleep(0.001)
                item = q.get_sync()
                if item == BoundedChunkQueue.EOF:
                    return
                consumed.append(item["id"])
                with lock:
                    peak_ram["d"] = max(peak_ram["d"], q.depth)

        t_p = threading.Thread(target=producer)
        t_c = threading.Thread(target=consumer)
        t_p.start()
        t_c.start()
        t_p.join(timeout=30)
        t_c.join(timeout=30)

        assert consumed == list(range(N)), "ordem global deve ser FIFO"
        assert peak_ram["d"] <= 4, (
            f"RAM passou de maxsize: peak={peak_ram['d']}"
        )
        # Como producer e mais rapido que consumer, esperamos pelo menos
        # alguns spills.
        assert q.spilled_total > 0
        q.cleanup()
