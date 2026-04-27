"""
Testes do cache global de engines SQLAlchemy.

Cobre:
- Hit do cache para o mesmo (workspace, conn) — concorrencia inclusa.
- Isolamento entre workspaces.
- ``dispose_workspace_engines`` fecha conexoes e remove do cache.
- ``invalidate_engine`` evicta apenas a chave informada.
- Quota LRU por workspace.
- Metricas Prometheus expostas com os nomes esperados.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app.services.db import engine_cache as ec


@pytest.fixture(autouse=True)
def _clean_cache_between_tests() -> Any:
    """Garante isolamento — cada teste comeca com cache vazio."""
    ec.dispose_all_engines()
    yield
    ec.dispose_all_engines()


# ---------------------------------------------------------------------------
# Hit / miss / isolamento
# ---------------------------------------------------------------------------


class TestCacheLookup:
    def test_same_workspace_and_conn_returns_same_engine(self):
        ws = uuid4()
        e1 = ec.get_engine_from_url(ws, "sqlite:///:memory:", "sqlite")
        e2 = ec.get_engine_from_url(ws, "sqlite:///:memory:", "sqlite")
        assert e1 is e2
        assert ec.cache_size() == 1

    def test_different_workspaces_do_not_share_engines(self):
        ws_a, ws_b = uuid4(), uuid4()
        e_a = ec.get_engine_from_url(ws_a, "sqlite:///:memory:", "sqlite")
        e_b = ec.get_engine_from_url(ws_b, "sqlite:///:memory:", "sqlite")
        assert e_a is not e_b
        assert ec.workspace_engine_count(ws_a) == 1
        assert ec.workspace_engine_count(ws_b) == 1

    def test_different_databases_get_distinct_engines(self):
        ws = uuid4()
        e1 = ec.get_engine(
            ws,
            conn_type="sqlite",
            host="",
            port=0,
            database="db_a",
            username="",
            connection_string="sqlite:///:memory:",
        )
        e2 = ec.get_engine(
            ws,
            conn_type="sqlite",
            host="",
            port=0,
            database="db_b",
            username="",
            connection_string="sqlite:///:memory:",
        )
        assert e1 is not e2
        assert ec.workspace_engine_count(ws) == 2

    def test_concurrent_calls_return_same_engine(self):
        """Chamadas paralelas para a mesma chave nao devem criar engines
        duplicados — o lock global garante a deduplicacao."""
        ws = uuid4()
        engines: list[sa.Engine] = []
        lock = threading.Lock()

        def _fetch() -> None:
            engine = ec.get_engine_from_url(ws, "sqlite:///:memory:", "sqlite")
            with lock:
                engines.append(engine)

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(_fetch) for _ in range(64)]
            for f in futures:
                f.result()

        assert len(engines) == 64
        assert all(e is engines[0] for e in engines)
        assert ec.cache_size() == 1


# ---------------------------------------------------------------------------
# Dispose / invalidate
# ---------------------------------------------------------------------------


class TestDispose:
    def test_dispose_workspace_removes_only_that_workspace(self):
        ws_a, ws_b = uuid4(), uuid4()
        ec.get_engine_from_url(ws_a, "sqlite:///:memory:", "sqlite")
        ec.get_engine_from_url(ws_b, "sqlite:///:memory:", "sqlite")
        assert ec.cache_size() == 2

        removed = ec.dispose_workspace_engines(ws_a)
        assert removed == 1
        assert ec.workspace_engine_count(ws_a) == 0
        assert ec.workspace_engine_count(ws_b) == 1

    def test_dispose_tenant_engines_alias_works(self):
        ws = uuid4()
        ec.get_engine_from_url(ws, "sqlite:///:memory:", "sqlite")
        # ``dispose_tenant_engines`` e o alias publico citado no spec.
        removed = ec.dispose_tenant_engines(ws)
        assert removed == 1

    def test_dispose_actually_calls_dispose_on_engine(self, monkeypatch):
        """Verifica que o engine cacheado realmente recebe ``dispose()``
        quando o workspace e descartado — protege contra leak de pool."""
        ws = uuid4()
        engine = ec.get_engine_from_url(ws, "sqlite:///:memory:", "sqlite")

        called = {"count": 0}
        original_dispose = engine.dispose

        def _spy_dispose(*args, **kwargs):
            called["count"] += 1
            return original_dispose(*args, **kwargs)

        monkeypatch.setattr(engine, "dispose", _spy_dispose)
        ec.dispose_workspace_engines(ws)
        assert called["count"] == 1

    def test_invalidate_removes_specific_key_only(self):
        ws = uuid4()
        ec.get_engine(
            ws,
            conn_type="sqlite",
            host="", port=0, database="db_a", username="",
            connection_string="sqlite:///:memory:",
        )
        ec.get_engine(
            ws,
            conn_type="sqlite",
            host="", port=0, database="db_b", username="",
            connection_string="sqlite:///:memory:",
        )

        ok = ec.invalidate_engine(
            ws,
            conn_type="sqlite",
            host="", port=0, database="db_a", username="",
        )
        assert ok is True
        assert ec.workspace_engine_count(ws) == 1

    def test_invalidate_returns_false_for_unknown_key(self):
        ok = ec.invalidate_engine(
            uuid4(),
            conn_type="sqlite",
            host="absent", port=0, database="x", username="",
        )
        assert ok is False


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


class TestQuota:
    def test_lru_eviction_when_workspace_quota_exceeded(self):
        """Ao atingir o limite, o engine menos recentemente usado e descartado."""
        ws = uuid4()
        common = dict(
            conn_type="sqlite",
            host="", port=0, username="",
            connection_string="sqlite:///:memory:",
            max_engines_per_workspace=2,
        )
        e1 = ec.get_engine(ws, database="db1", **common)
        ec.get_engine(ws, database="db2", **common)
        ec.get_engine(ws, database="db3", **common)
        assert ec.workspace_engine_count(ws) == 2
        # Reusar a chave de e1 cria um engine novo (o anterior foi evitado).
        e1_recreated = ec.get_engine(ws, database="db1", **common)
        assert e1_recreated is not e1


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_metric_names_are_present_in_default_registry(self):
        """As gauges db_pool_* sao registradas no boot do modulo — antes
        mesmo do primeiro engine ser criado."""
        from prometheus_client import REGISTRY

        names = {
            metric.name
            for metric in REGISTRY.collect()
        }
        assert "db_pool_size" in names
        assert "db_pool_checked_out" in names
        assert "db_pool_overflow" in names

    def test_refresh_metrics_emits_one_series_per_engine(self):
        ws_a, ws_b = uuid4(), uuid4()
        ec.get_engine_from_url(ws_a, "sqlite:///:memory:", "sqlite")
        ec.get_engine_from_url(ws_b, "sqlite:///:memory:", "sqlite")
        ec.refresh_metrics()

        # Le os samples emitidos pela gauge db_pool_size — esperamos 2 series
        # (uma por workspace), com label database_type=sqlite.
        labels_seen = set()
        for sample in ec._POOL_SIZE_GAUGE.collect()[0].samples:
            labels_seen.add(
                (sample.labels.get("workspace_id"), sample.labels.get("database_type"))
            )

        assert (str(ws_a), "sqlite") in labels_seen
        assert (str(ws_b), "sqlite") in labels_seen
