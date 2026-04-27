"""Cache global de engines SQLAlchemy por workspace + tipo de banco.

Motivacao
---------
Antes desta camada, cada chamada a ``sa.create_engine`` em ``load_service``,
``playground_service``, processadores de no, etc. criava um engine novo,
abria o pool, executava 1-2 queries e fazia ``dispose()``. Em escala isso
resulta em milhares de conexoes abertas/fechadas por minuto contra o banco
do cliente — tanto o pool do shift quanto o do banco de origem ficam
saturados.

Aqui mantemos um dicionario global indexado por
``(workspace_id, conn_type, host, port, database, username)`` que devolve
sempre o mesmo engine para a mesma combinacao. O pool e dimensionado de
acordo com o tipo de banco (Oracle mata sessoes ociosas; PostgreSQL
suporta pool maior; Firebird tem limites baixos por padrao).

Concorrencia
------------
A criacao de novos engines e protegida por um ``threading.RLock`` global
e por uma ``asyncio.Lock`` separada para callers async. Como a maioria
dos consumidores corre em threads de ``asyncio.to_thread``, o RLock e o
caminho principal; o async lock e oferecido como conveniencia para quem
quiser ``await``ar a criacao sem bloquear o event loop.

Quota
-----
Cada workspace pode ter no maximo ``DEFAULT_MAX_ENGINES_PER_WORKSPACE``
engines simultaneos no cache (configuravel por env). Quando o limite e
atingido, o engine menos recentemente usado do mesmo workspace e
descartado (LRU) para abrir espaco. Engines descartados sao
``dispose()``-ados de forma sincrona — o pool subjacente fecha as
conexoes ociosas.

Seguranca
---------
A ``password`` NAO entra na chave de cache nem em logs. Quando o admin
edita uma conexao (via ``ConnectionService.update``) ou apaga
(``delete``), o servico chama ``invalidate_engine`` para evitar que um
engine antigo continue valido com credenciais obsoletas.

Metricas Prometheus
-------------------
``db_pool_size`` (gauge), ``db_pool_checked_out`` (gauge),
``db_pool_overflow`` (gauge), todas com labels ``workspace_id`` e
``database_type``. As gauges sao atualizadas sob demanda via
``refresh_metrics`` e antes de cada coleta do endpoint /metrics
(``register_metric_callbacks``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID

import sqlalchemy as sa
from prometheus_client import Gauge


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuracao por tipo de banco
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PoolProfile:
    pool_size: int
    max_overflow: int
    pool_recycle: int  # segundos; -1 = sem reciclagem
    pool_pre_ping: bool


# Os profiles seguem o spec da Sprint:
#   Oracle    : pool_size=5,  max_overflow=10, pool_recycle=1800
#   Firebird  : pool_size=3,  max_overflow=5,  pool_pre_ping=True
#   PostgreSQL: pool_size=10, max_overflow=20, pool_pre_ping=True
#   MySQL     : pool_size=10, max_overflow=20, pool_recycle=3600
# SQL Server segue PostgreSQL (perfil generico transacional). SQLite e usado
# apenas em testes — pool minimo, sem pre-ping (banco em arquivo local).
_POOL_PROFILES: dict[str, _PoolProfile] = {
    "oracle": _PoolProfile(pool_size=5, max_overflow=10, pool_recycle=1800, pool_pre_ping=True),
    "firebird": _PoolProfile(pool_size=3, max_overflow=5, pool_recycle=-1, pool_pre_ping=True),
    "postgresql": _PoolProfile(pool_size=10, max_overflow=20, pool_recycle=-1, pool_pre_ping=True),
    "mysql": _PoolProfile(pool_size=10, max_overflow=20, pool_recycle=3600, pool_pre_ping=True),
    "sqlserver": _PoolProfile(pool_size=10, max_overflow=20, pool_recycle=-1, pool_pre_ping=True),
    "sqlite": _PoolProfile(pool_size=1, max_overflow=0, pool_recycle=-1, pool_pre_ping=False),
}

_DEFAULT_PROFILE = _PoolProfile(
    pool_size=5, max_overflow=10, pool_recycle=-1, pool_pre_ping=True,
)


def _profile_for(conn_type: str) -> _PoolProfile:
    return _POOL_PROFILES.get(conn_type.lower(), _DEFAULT_PROFILE)


def get_pool_capacity(conn_type: str) -> int:
    """Capacidade efetiva (pool_size + max_overflow) para o tipo de banco.

    Usada por consumidores que querem dimensionar workers paralelos sem
    estourar o pool — caso classico: extracao particionada que abre N
    conexoes simultaneas via ``partition_num``. SQLite retorna 1 (single
    thread)."""
    profile = _profile_for(conn_type)
    return max(1, profile.pool_size + profile.max_overflow)


# ---------------------------------------------------------------------------
# Quota por workspace
# ---------------------------------------------------------------------------


def _read_max_per_workspace_env() -> int:
    raw = os.getenv("SHIFT_DB_MAX_ENGINES_PER_WORKSPACE", "20")
    try:
        value = int(raw)
        return value if value > 0 else 20
    except ValueError:
        return 20


DEFAULT_MAX_ENGINES_PER_WORKSPACE = _read_max_per_workspace_env()

# Sentinela para callers que ainda nao threadam workspace_id. As entradas
# nesse "workspace" compartilham a mesma quota global e podem ser limpas via
# ``dispose_default_scope_engines()``.
DEFAULT_SCOPE = "__default__"


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineCacheKey:
    """Identidade do engine no cache.

    A senha e o ``extra_params`` NAO entram na chave porque podem variar
    entre revisoes da mesma conexao logica. Quem altera credencial deve
    chamar ``invalidate_engine`` para evitar que um engine obsoleto
    continue retornando.
    """

    workspace_id: str
    conn_type: str
    host: str
    port: int
    database: str
    username: str


@dataclass
class _CachedEngine:
    """Container interno: o engine + metadados de bookkeeping."""

    engine: sa.Engine
    conn_type: str
    workspace_id: str
    last_used_at: float = field(default_factory=lambda: _now())


def _now() -> float:
    # Indireto para facilitar mock em testes.
    import time
    return time.monotonic()


# ---------------------------------------------------------------------------
# Estado global
# ---------------------------------------------------------------------------


_CACHE: "OrderedDict[EngineCacheKey, _CachedEngine]" = OrderedDict()
_CACHE_LOCK = threading.RLock()
_ASYNC_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Metricas Prometheus
# ---------------------------------------------------------------------------


_LABEL_NAMES = ("workspace_id", "database_type")

_POOL_SIZE_GAUGE = Gauge(
    "db_pool_size",
    "Tamanho configurado do pool SQLAlchemy (pool_size).",
    _LABEL_NAMES,
)
_POOL_CHECKED_OUT_GAUGE = Gauge(
    "db_pool_checked_out",
    "Conexoes atualmente em uso (checked-out do pool).",
    _LABEL_NAMES,
)
_POOL_OVERFLOW_GAUGE = Gauge(
    "db_pool_overflow",
    "Conexoes alocadas alem de pool_size (em overflow).",
    _LABEL_NAMES,
)


def _safe_pool_metric(engine: sa.Engine, attr: str) -> int:
    """Le ``attr`` do pool sem propagar excecoes em pools nao-padrao
    (ex.: SQLite usa SingletonThreadPool, que nao tem ``checkedout``)."""
    pool = engine.pool
    fn = getattr(pool, attr, None)
    if fn is None:
        return 0
    try:
        return int(fn())
    except Exception:  # noqa: BLE001 — metrica nao pode quebrar a request
        return 0


def refresh_metrics() -> None:
    """Recalcula as gauges a partir do estado atual dos pools.

    Chamada antes do scrape (ver ``register_metric_callbacks``) para que
    os valores reflitam o que o pool reporta no momento — em vez do que
    foi visto no ultimo ``get_engine``.
    """
    with _CACHE_LOCK:
        _POOL_SIZE_GAUGE.clear()
        _POOL_CHECKED_OUT_GAUGE.clear()
        _POOL_OVERFLOW_GAUGE.clear()
        for key, cached in _CACHE.items():
            labels = (key.workspace_id, cached.conn_type)
            _POOL_SIZE_GAUGE.labels(*labels).set(
                _safe_pool_metric(cached.engine, "size")
            )
            _POOL_CHECKED_OUT_GAUGE.labels(*labels).set(
                _safe_pool_metric(cached.engine, "checkedout")
            )
            _POOL_OVERFLOW_GAUGE.labels(*labels).set(
                _safe_pool_metric(cached.engine, "overflow")
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize_workspace_id(workspace_id: UUID | str | None) -> str:
    if workspace_id is None:
        return DEFAULT_SCOPE
    return str(workspace_id)


def _build_engine(
    connection_string: str,
    conn_type: str,
    *,
    connect_args: Mapping[str, Any] | None = None,
) -> sa.Engine:
    profile = _profile_for(conn_type)
    kwargs: dict[str, Any] = {}
    # SQLite usa SingletonThreadPool por padrao, que NAO aceita pool_size /
    # max_overflow / pool_pre_ping. Os outros bancos usam QueuePool e
    # aceitam todos os parametros do profile.
    if conn_type.lower() != "sqlite":
        kwargs["pool_size"] = profile.pool_size
        kwargs["max_overflow"] = profile.max_overflow
        kwargs["pool_pre_ping"] = profile.pool_pre_ping
        if profile.pool_recycle > 0:
            kwargs["pool_recycle"] = profile.pool_recycle
    if connect_args:
        kwargs["connect_args"] = dict(connect_args)
    return sa.create_engine(connection_string, **kwargs)


def _evict_lru_for_workspace(workspace_id: str, max_engines: int) -> None:
    """Descarta o engine LRU do workspace quando a quota e atingida.

    Chamada com ``_CACHE_LOCK`` ja adquirido pelo invocador.
    """
    workspace_keys = [k for k in _CACHE.keys() if k.workspace_id == workspace_id]
    if len(workspace_keys) < max_engines:
        return
    workspace_keys.sort(key=lambda k: _CACHE[k].last_used_at)
    excess = len(workspace_keys) - max_engines + 1
    for victim in workspace_keys[:excess]:
        cached = _CACHE.pop(victim, None)
        if cached is not None:
            _dispose_engine_safely(cached.engine)
            logger.info(
                "db.engine_cache.evicted",
                extra={
                    "workspace_id": workspace_id,
                    "conn_type": cached.conn_type,
                    "reason": "lru_quota",
                },
            )


def _dispose_engine_safely(engine: sa.Engine) -> None:
    try:
        engine.dispose()
    except Exception:  # noqa: BLE001 — dispose nao pode quebrar a request
        logger.exception("db.engine_cache.dispose_failed")


def get_engine(
    workspace_id: UUID | str | None,
    *,
    conn_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    connection_string: str,
    connect_args: Mapping[str, Any] | None = None,
    max_engines_per_workspace: int | None = None,
) -> sa.Engine:
    """Devolve um engine cacheado para a chave informada.

    Cria um engine novo apenas se nao houver entrada equivalente. O engine
    eh compartilhado entre chamadores — NAO chame ``dispose()`` em codigo
    de aplicacao; isso quebraria outras requests.

    Para invalidar manualmente, use ``invalidate_engine`` (mudanca de
    credenciais) ou ``dispose_workspace_engines`` (logout/cleanup).
    """
    ws = _normalize_workspace_id(workspace_id)
    key = EngineCacheKey(
        workspace_id=ws,
        conn_type=conn_type.lower(),
        host=host,
        port=port,
        database=database,
        username=username,
    )

    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            cached.last_used_at = _now()
            _CACHE.move_to_end(key)
            return cached.engine

        # Aplica quota de workspace antes de criar o novo engine.
        quota = max_engines_per_workspace or DEFAULT_MAX_ENGINES_PER_WORKSPACE
        _evict_lru_for_workspace(ws, quota)

        engine = _build_engine(connection_string, conn_type, connect_args=connect_args)
        _CACHE[key] = _CachedEngine(
            engine=engine,
            conn_type=key.conn_type,
            workspace_id=ws,
        )
        logger.info(
            "db.engine_cache.created",
            extra={
                "workspace_id": ws,
                "conn_type": key.conn_type,
                "host": key.host,
                "database": key.database,
            },
        )
        return engine


async def get_engine_async(
    workspace_id: UUID | str | None,
    **kwargs: Any,
) -> sa.Engine:
    """Versao async — protege a criacao com ``asyncio.Lock``.

    ``sa.create_engine`` ainda eh sincrono; o lock garante apenas que
    duas corrotinas concorrentes na mesma chave nao criem dois engines
    se o primeiro acesso ainda esta em andamento.
    """
    async with _ASYNC_LOCK:
        return get_engine(workspace_id, **kwargs)


def invalidate_engine(
    workspace_id: UUID | str | None,
    *,
    conn_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
) -> bool:
    """Remove um engine especifico do cache e o descarta.

    Retorna ``True`` se havia entrada para a chave.
    """
    ws = _normalize_workspace_id(workspace_id)
    key = EngineCacheKey(
        workspace_id=ws,
        conn_type=conn_type.lower(),
        host=host,
        port=port,
        database=database,
        username=username,
    )
    with _CACHE_LOCK:
        cached = _CACHE.pop(key, None)
    if cached is None:
        return False
    _dispose_engine_safely(cached.engine)
    logger.info(
        "db.engine_cache.invalidated",
        extra={
            "workspace_id": ws,
            "conn_type": key.conn_type,
            "host": key.host,
            "database": key.database,
        },
    )
    return True


def dispose_workspace_engines(workspace_id: UUID | str | None) -> int:
    """Descarta todos os engines de um workspace. Retorna a contagem."""
    ws = _normalize_workspace_id(workspace_id)
    with _CACHE_LOCK:
        victims = [k for k in _CACHE.keys() if k.workspace_id == ws]
        cached_list = [_CACHE.pop(k) for k in victims]
    for cached in cached_list:
        _dispose_engine_safely(cached.engine)
    if cached_list:
        logger.info(
            "db.engine_cache.workspace_disposed",
            extra={"workspace_id": ws, "count": len(cached_list)},
        )
    return len(cached_list)


# Alias compativel com o nome usado no spec da tarefa. Mantem ``workspace_id``
# como sinonimo de ``tenant_id`` na nomenclatura externa do shift.
dispose_tenant_engines = dispose_workspace_engines


def dispose_all_engines() -> int:
    """Limpa todo o cache. Util para testes e shutdown da aplicacao."""
    with _CACHE_LOCK:
        cached_list = list(_CACHE.values())
        _CACHE.clear()
    for cached in cached_list:
        _dispose_engine_safely(cached.engine)
    return len(cached_list)


def cache_size() -> int:
    """Numero total de engines no cache (todos workspaces)."""
    with _CACHE_LOCK:
        return len(_CACHE)


def workspace_engine_count(workspace_id: UUID | str | None) -> int:
    """Numero de engines vivos para o workspace informado."""
    ws = _normalize_workspace_id(workspace_id)
    with _CACHE_LOCK:
        return sum(1 for k in _CACHE.keys() if k.workspace_id == ws)


# ---------------------------------------------------------------------------
# Conveniencias para o codigo legado que recebe um connection_string pronto
# e nao tem todos os campos separados (ex.: load_service, polling).
# ---------------------------------------------------------------------------


def get_engine_from_url(
    workspace_id: UUID | str | None,
    connection_string: str,
    conn_type: str,
    *,
    connect_args: Mapping[str, Any] | None = None,
) -> sa.Engine:
    """Variante minima usada por callers que so tem URL + tipo.

    A chave deriva do parsing da URL; se algum componente faltar, o cache
    cai para chaves com strings vazias, o que ainda eh seguro (mesmas
    URLs continuam batendo o mesmo engine).
    """
    parsed = sa.engine.url.make_url(connection_string)
    return get_engine(
        workspace_id,
        conn_type=conn_type,
        host=parsed.host or "",
        port=parsed.port or 0,
        database=parsed.database or "",
        username=parsed.username or "",
        connection_string=connection_string,
        connect_args=connect_args,
    )


# ---------------------------------------------------------------------------
# Hook de scrape Prometheus
# ---------------------------------------------------------------------------


def register_metric_callbacks(instrumentator: Any) -> None:
    """Anexa um callback que atualiza as gauges antes de cada coleta.

    Chamado no boot do FastAPI, depois de instanciar o ``Instrumentator``.
    Caso o instrumentator nao exponha esse hook (versoes antigas), apenas
    as gauges atualizadas em ``refresh_metrics()`` ficam visiveis quando
    o scrape de fato ocorre — o operador pode chamar manualmente em uma
    rota de saude se preferir.
    """
    add_hook = getattr(instrumentator, "add", None)
    if add_hook is None:  # versao incompativel, sem fail
        return

    def _before_scrape(_metrics_info: Any) -> None:
        refresh_metrics()

    try:
        instrumentator.add(_before_scrape)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — incompatibilidade nao pode quebrar boot
        logger.warning(
            "db.engine_cache.metric_hook_unavailable",
            exc_info=True,
        )
