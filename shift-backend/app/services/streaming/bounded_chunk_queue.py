"""Bounded chunk queue com spillover opcional em disco.

Motivacao
---------
Ate o Prompt 1.1 a extracao SQL usava ``queue.Queue(maxsize=4)`` cru. Se o
destino (load_node) e mais lento que a origem (sql_database), o producer
fica bloqueado no put — bom para RAM, ruim quando precisamos um colchao
um pouco maior. Por outro lado, deixar a queue ilimitada estoura RAM em
extracoes de 50M+ linhas.

Esta classe oferece o melhor dos dois mundos:

- Quando ``spill_dir`` esta desligado: queue rigida com ``maxsize`` slots.
  ``put`` bloqueia em queue cheia — backpressure puro.
- Quando ``spill_dir`` esta ligado: ``maxsize`` chunks em RAM ao mesmo
  tempo. Ao receber um chunk com a RAM cheia, o EXCESSO vai para um
  arquivo binario em ``spill_dir`` e so um ponteiro fica numa lista
  paralela. ``get`` reabastece RAM lendo de volta o ponteiro mais antigo.
  RAM permanece em ``maxsize`` chunks; disco cresce conforme o gap entre
  produtor/consumidor.

API
---
Funcionam tanto em codigo sincrono (threads — caminho atual da extracao
particionada) quanto em codigo asyncio (futuros consumidores em
processadores async). Os pares sao espelhos:

  - ``put_sync(chunk, timeout=None)`` / ``put(chunk)`` (async)
  - ``get_sync(timeout=None)`` / ``get()`` (async)

A async-API delega para a sync via ``asyncio.to_thread`` para nao
bloquear o event loop.

Formato de spill
----------------
Por padrao usa pickle (stdlib, rapido para list[dict]). Quando ``pyarrow``
esta disponivel e os chunks sao listas homogeneas de dicts, o caller pode
trocar para Arrow IPC via ``serializer="arrow"`` no construtor — mas isso
e opcional; o default cobre 100% dos formatos usados pelos producers
atuais (rows como dict[str, Any]).

Cleanup
-------
- ``cleanup()``: remove todos os arquivos de spill criados por esta queue.
  Idempotente. Chame em todos os caminhos de saida (success/fail/cancel).
- ``cleanup_execution_spill(execution_id)``: util do modulo — apaga o
  diretorio inteiro de spill da execucao (chamada pelo runner no
  ``finally``, alinhada ao ``cleanup_execution_storage``).

Metricas Prometheus
-------------------
- ``streaming_queue_depth`` (Gauge): numero de chunks em RAM.
- ``streaming_spilled_chunks_total`` (Counter): total de chunks que ja
  foram para disco.
- ``streaming_spill_files_active`` (Gauge): arquivos de spill ainda nao
  consumidos (e portanto ocupando disco).

Todas com label ``execution_id`` para rastreamento por run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Any
from uuid import uuid4

from prometheus_client import Counter, Gauge


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinela publico
# ---------------------------------------------------------------------------


class _Sentinel:
    """Marca de fim de stream. Padrao do BoundedChunkQueue.EOF.

    ``__eq__`` baseado em tipo (e nao em identity) garante que a EOF
    sobrevive ao roundtrip de pickle quando passa pelo spill em disco —
    ``pickle`` reconstroi uma instancia nova, perdendo o ``is`` mas
    preservando a igualdade por classe.
    """

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sentinel)

    def __hash__(self) -> int:
        return 0

    def __repr__(self) -> str:  # pragma: no cover — diagnostic only
        return "<BoundedChunkQueue.EOF>"


# ---------------------------------------------------------------------------
# Metricas Prometheus
# ---------------------------------------------------------------------------


_QUEUE_DEPTH = Gauge(
    "streaming_queue_depth",
    "Chunks atualmente em RAM em uma BoundedChunkQueue.",
    ("execution_id",),
)
_SPILLED_CHUNKS = Counter(
    "streaming_spilled_chunks_total",
    "Total de chunks que foram serializados para disco (spill).",
    ("execution_id",),
)
_SPILL_ACTIVE = Gauge(
    "streaming_spill_files_active",
    "Arquivos de spill nao consumidos (ocupando disco).",
    ("execution_id",),
)


# ---------------------------------------------------------------------------
# Implementacao
# ---------------------------------------------------------------------------


# Default warn threshold pode ser sobrescrito pelo caller; quando o numero
# de chunks que migraram para disco em uma unica queue ultrapassa este
# valor, emitimos um WARN com o execution_id para investigacao posterior.
_DEFAULT_SPILL_WARN_THRESHOLD = 50


class BoundedChunkQueue:
    """Queue bounded em RAM com spillover opcional para disco.

    Parametros
    ----------
    maxsize:
        Maximo de chunks em RAM simultaneamente. Ao ultrapassar e com
        ``spill_dir`` setado, o EXCESSO vai para disco; sem ``spill_dir``,
        ``put`` bloqueia (backpressure puro).
    execution_id:
        Tag de rastreamento usada nas metricas Prometheus e no nome dos
        arquivos de spill. Pode ser ``None`` em testes — usa um UUID.
    spill_dir:
        Diretorio para escrever arquivos de spill. ``None`` desliga o spill.
    spill_when_exceeded:
        Atalho ergonomico: ``False`` forca backpressure puro mesmo se
        ``spill_dir`` foi setado.
    spill_warn_threshold:
        Numero de chunks spilados em uma mesma queue acima do qual o
        modulo emite WARN. Default 50 — visa indicar pipeline maldimensionado.
    """

    EOF: _Sentinel = _Sentinel()

    def __init__(
        self,
        maxsize: int,
        *,
        execution_id: str | None = None,
        spill_dir: Path | str | None = None,
        spill_when_exceeded: bool = True,
        spill_warn_threshold: int = _DEFAULT_SPILL_WARN_THRESHOLD,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize deve ser >= 1")

        self._maxsize = maxsize
        self._execution_id = execution_id or f"anon-{uuid4().hex[:8]}"
        self._spill_warn_threshold = spill_warn_threshold

        self._spill_dir: Path | None
        if spill_dir is not None and spill_when_exceeded:
            self._spill_dir = Path(spill_dir)
            self._spill_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._spill_dir = None

        # Buffer em RAM e fila de ponteiros para arquivos de spill.
        self._inmem: deque[Any] = deque()
        self._spill: deque[Path] = deque()

        self._lock = threading.Lock()
        # ``not_empty`` libera ``get`` quando ha algo para consumir.
        # ``not_full`` libera ``put`` quando spill desligado e RAM tem espaco.
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)

        self._spilled_total = 0
        self._closed = False
        self._warned_threshold = False

        # Inicializa metricas com label desta queue (evita primeira-coleta vazia).
        _QUEUE_DEPTH.labels(self._execution_id).set(0)
        _SPILL_ACTIVE.labels(self._execution_id).set(0)

    # ------------------------------------------------------------------
    # Sync API — usada pelos producers/consumers em threads
    # ------------------------------------------------------------------

    def put_sync(self, chunk: Any, timeout: float | None = None) -> None:
        """Insere ``chunk`` na queue.

        Em modo backpressure puro (sem spill), bloqueia ate ter espaco
        em RAM ou ``timeout`` expirar. Com spill ligado, escreve em disco
        e retorna sem bloquear.

        Levanta ``RuntimeError`` se a queue ja foi fechada via ``close()``.
        Levanta ``TimeoutError`` quando ``timeout`` e atingido sem espaco.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("BoundedChunkQueue ja foi fechada")

            if len(self._inmem) < self._maxsize:
                self._inmem.append(chunk)
                self._update_metrics_locked()
                self._not_empty.notify()
                return

            # Sem espaco em RAM. Decide entre spill ou bloquear.
            if self._spill_dir is not None:
                self._spill_chunk_locked(chunk)
                self._not_empty.notify()
                return

            # Backpressure puro — espera espaco.
            if not self._not_full.wait_for(
                lambda: self._closed or len(self._inmem) < self._maxsize,
                timeout=timeout,
            ):
                raise TimeoutError(
                    f"BoundedChunkQueue.put_sync: timeout apos {timeout}s "
                    f"com queue cheia (maxsize={self._maxsize})"
                )
            if self._closed:
                raise RuntimeError("BoundedChunkQueue ja foi fechada")
            self._inmem.append(chunk)
            self._update_metrics_locked()
            self._not_empty.notify()

    def get_sync(self, timeout: float | None = None) -> Any:
        """Devolve o proximo chunk. Bloqueia se queue vazia.

        Levanta ``TimeoutError`` quando ``timeout`` e atingido sem dados.
        Apos consumir um chunk, recarrega o slot lendo o spill mais antigo
        (se houver), mantendo invariante: ``len(self._inmem) <= maxsize``.
        """
        with self._lock:
            if not self._not_empty.wait_for(
                lambda: self._inmem or self._spill or self._closed,
                timeout=timeout,
            ):
                raise TimeoutError(
                    f"BoundedChunkQueue.get_sync: timeout apos {timeout}s "
                    "com queue vazia"
                )
            if not self._inmem and not self._spill:
                # Queue fechada e drenada — caller deve interpretar como EOF.
                raise RuntimeError("BoundedChunkQueue fechada e drenada")

            chunk = self._inmem.popleft() if self._inmem else self._load_spill_locked()

            # Reabastece RAM com o spill mais antigo (FIFO global).
            while self._spill and len(self._inmem) < self._maxsize:
                self._inmem.append(self._load_spill_locked())

            self._update_metrics_locked()
            self._not_full.notify()
            return chunk

    def put_eof_sync(self) -> None:
        """Sinaliza fim do stream. Consumidores recebem ``BoundedChunkQueue.EOF``."""
        self.put_sync(self.EOF)

    # ------------------------------------------------------------------
    # Async API — wrappers em ``asyncio.to_thread``
    # ------------------------------------------------------------------

    async def put(self, chunk: Any) -> None:
        """Versao async de ``put_sync`` — nao bloqueia o event loop."""
        await asyncio.to_thread(self.put_sync, chunk)

    async def get(self) -> Any:
        """Versao async de ``get_sync`` — nao bloqueia o event loop."""
        return await asyncio.to_thread(self.get_sync)

    async def put_eof(self) -> None:
        await asyncio.to_thread(self.put_eof_sync)

    # ------------------------------------------------------------------
    # Estado e cleanup
    # ------------------------------------------------------------------

    @property
    def depth(self) -> int:
        """Chunks em RAM no momento."""
        with self._lock:
            return len(self._inmem)

    @property
    def spilled_total(self) -> int:
        """Total de chunks que ja foram para disco (cumulativo)."""
        with self._lock:
            return self._spilled_total

    @property
    def spill_active(self) -> int:
        """Arquivos de spill ainda nao consumidos."""
        with self._lock:
            return len(self._spill)

    def close(self) -> None:
        """Marca a queue como fechada — destrava puts/gets pendentes."""
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()
            self._not_full.notify_all()

    def cleanup(self) -> int:
        """Remove arquivos de spill criados por esta queue. Idempotente.

        Retorna o numero de arquivos efetivamente removidos. Seguro de
        chamar mais de uma vez (ex: caller no finally + tear-down do
        runner) e em qualquer estado (drenada, parcial, com erro).
        """
        with self._lock:
            paths = list(self._spill)
            self._spill.clear()
            self._update_metrics_locked()
        removed = 0
        for path in paths:
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
            except Exception:  # noqa: BLE001 — cleanup nao pode propagar
                logger.warning(
                    "streaming.spill_cleanup_failed",
                    extra={"path": str(path), "execution_id": self._execution_id},
                )
        # Apaga as gauges associadas — evita "vazar" series para
        # execution_ids que ja terminaram.
        try:
            _QUEUE_DEPTH.remove(self._execution_id)
            _SPILL_ACTIVE.remove(self._execution_id)
        except KeyError:
            pass
        return removed

    # ------------------------------------------------------------------
    # Context managers — pareiam cleanup com saida de escopo
    # ------------------------------------------------------------------

    def __enter__(self) -> "BoundedChunkQueue":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
        self.cleanup()

    async def __aenter__(self) -> "BoundedChunkQueue":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.close()
        await asyncio.to_thread(self.cleanup)

    # ------------------------------------------------------------------
    # Helpers internos (chamados com lock adquirido)
    # ------------------------------------------------------------------

    def _spill_chunk_locked(self, chunk: Any) -> None:
        """Serializa ``chunk`` em ``spill_dir`` e enfileira o ponteiro."""
        assert self._spill_dir is not None
        # Nome unico estavel: contagem cumulativa garante ordem por filename
        # quando o sistema de arquivos preserva a ordem de criacao no listdir.
        idx = self._spilled_total
        path = self._spill_dir / f"chunk_{self._execution_id}_{idx:010d}.spill"
        try:
            with path.open("wb") as fh:
                pickle.dump(chunk, fh, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError as exc:
            # Falha de disco (cheio, sem permissao). Como fallback, BLOQUEIA
            # como se spill estivesse desligado — preserva backpressure
            # quando o disco estaria estourando tambem.
            logger.error(
                "streaming.spill_write_failed",
                extra={
                    "execution_id": self._execution_id,
                    "path": str(path),
                    "error": str(exc),
                },
            )
            raise

        self._spill.append(path)
        self._spilled_total += 1
        _SPILLED_CHUNKS.labels(self._execution_id).inc()
        _SPILL_ACTIVE.labels(self._execution_id).set(len(self._spill))

        if (
            self._spilled_total >= self._spill_warn_threshold
            and not self._warned_threshold
        ):
            self._warned_threshold = True
            logger.warning(
                "streaming.spill_threshold_exceeded",
                extra={
                    "execution_id": self._execution_id,
                    "spilled_chunks": self._spilled_total,
                    "threshold": self._spill_warn_threshold,
                    "hint": (
                        "Producer mais rapido que consumer — considere "
                        "reduzir partition_num ou aumentar concorrencia "
                        "do node de carga."
                    ),
                },
            )

    def _load_spill_locked(self) -> Any:
        """Recupera o spill mais antigo, le e remove do disco."""
        path = self._spill.popleft()
        try:
            with path.open("rb") as fh:
                chunk = pickle.load(fh)
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        _SPILL_ACTIVE.labels(self._execution_id).set(len(self._spill))
        return chunk

    def _update_metrics_locked(self) -> None:
        _QUEUE_DEPTH.labels(self._execution_id).set(len(self._inmem))


# ---------------------------------------------------------------------------
# Helpers de modulo
# ---------------------------------------------------------------------------


def cleanup_execution_spill(execution_id: str, base_dir: Path | str | None = None) -> int:
    """Apaga todos os arquivos de spill associados a uma execucao.

    Util para o runner chamar no ``finally`` global, alinhado ao
    ``cleanup_execution_storage`` que ja existe. Aceita um diretorio
    base — caso contrario usa o default ``<tempdir>/shift/spill``.

    Retorna o numero de arquivos removidos.
    """
    if base_dir is None:
        base_dir = default_spill_dir()
    base_dir = Path(base_dir)
    if not base_dir.exists():
        return 0
    removed = 0
    pattern = f"chunk_{execution_id}_*.spill"
    for path in base_dir.glob(pattern):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def default_spill_dir() -> Path:
    """Resolve o diretorio padrao de spill a partir das settings.

    Mantido como funcao para evitar import circular com ``app.core.config``.
    """
    from app.core.config import settings  # local import: lazy

    raw = getattr(settings, "STREAMING_SPILL_DIR", None)
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / "shift" / "spill"
