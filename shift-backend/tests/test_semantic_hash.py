"""
Testes para compute_semantic_hash (Fase 5).

Critério de aceite principal:
  100 runs idênticas → 1 hash distinto por nó (determinismo).
  Campos runtime-only não afetam o hash.
"""

from __future__ import annotations

import pytest

from app.services.workflow.semantic_hash import (
    RUNTIME_ONLY_FIELDS,
    compute_semantic_hash,
    fingerprint_schema,
)


# ─── Determinismo ─────────────────────────────────────────────────────────────

class TestDeterminism:

    def test_mesmo_config_mesmo_hash(self) -> None:
        cfg = {"query": "SELECT * FROM orders", "connection_id": "conn-1"}
        h1 = compute_semantic_hash(cfg, [], node_type="sql_database")
        h2 = compute_semantic_hash(cfg, [], node_type="sql_database")
        assert h1 == h2

    def test_100_runs_identicas_1_hash(self) -> None:
        cfg = {"query": "SELECT * FROM orders", "connection_id": "conn-1"}
        hashes = {
            compute_semantic_hash(cfg, ["fp1"], node_type="sql_database")
            for _ in range(100)
        }
        assert len(hashes) == 1

    def test_mesmo_hash_para_sql_database(self) -> None:
        cfg = {"connection_id": "abc", "query": "SELECT id FROM t"}
        hashes = {
            compute_semantic_hash(cfg, ["fp_upstream"], node_type="sql_database")
            for _ in range(10)
        }
        assert len(hashes) == 1

    def test_mesmo_hash_para_join(self) -> None:
        cfg = {"join_type": "inner", "conditions": [{"left_column": "id", "right_column": "id"}]}
        hashes = {
            compute_semantic_hash(cfg, ["fp_left", "fp_right"], node_type="join")
            for _ in range(10)
        }
        assert len(hashes) == 1

    def test_mesmo_hash_para_aggregator(self) -> None:
        cfg = {"group_by": ["category"], "aggregations": [{"column": "amount", "func": "sum"}]}
        hashes = {
            compute_semantic_hash(cfg, ["fp1"], node_type="aggregator")
            for _ in range(10)
        }
        assert len(hashes) == 1


# ─── Campos runtime-only ignorados ───────────────────────────────────────────

class TestRuntimeFieldsIgnored:

    def test_cache_enabled_nao_afeta_hash(self) -> None:
        cfg_base = {"query": "SELECT 1", "connection_id": "c1"}
        cfg_cached = {**cfg_base, "cache_enabled": True, "cache_ttl_seconds": 300}
        h_base = compute_semantic_hash(cfg_base, [], node_type="sql_database")
        h_cached = compute_semantic_hash(cfg_cached, [], node_type="sql_database")
        assert h_base == h_cached

    def test_force_refresh_nao_afeta_hash(self) -> None:
        cfg = {"query": "SELECT 1", "connection_id": "c1"}
        h1 = compute_semantic_hash({**cfg, "force_refresh": True}, [], node_type="sql_database")
        h2 = compute_semantic_hash({**cfg, "force_refresh": False}, [], node_type="sql_database")
        assert h1 == h2

    def test_timeout_seconds_nao_afeta_hash(self) -> None:
        cfg = {"condition": "amount > 100"}
        h1 = compute_semantic_hash({**cfg, "timeout_seconds": 30}, [], node_type="filter")
        h2 = compute_semantic_hash({**cfg, "timeout_seconds": 600}, [], node_type="filter")
        assert h1 == h2

    def test_label_nao_afeta_hash(self) -> None:
        cfg = {"condition": "amount > 100"}
        h1 = compute_semantic_hash({**cfg, "label": "Filtro A"}, [], node_type="filter")
        h2 = compute_semantic_hash({**cfg, "label": "Filtro B"}, [], node_type="filter")
        assert h1 == h2

    def test_todos_runtime_fields_ignorados(self) -> None:
        """Todos os campos em RUNTIME_ONLY_FIELDS devem ser transparentes ao hash."""
        base = {"condition": "x > 1"}
        h_base = compute_semantic_hash(base, [], node_type="filter")
        polluted = {**base, **{f: "runtime_value" for f in RUNTIME_ONLY_FIELDS}}
        h_polluted = compute_semantic_hash(polluted, [], node_type="filter")
        assert h_base == h_polluted


# ─── connection_string excluída, connection_id preservado ─────────────────────

class TestConnectionHandling:

    def test_connection_string_excluida(self) -> None:
        cfg_id = {"connection_id": "uuid-123", "query": "SELECT 1"}
        cfg_both = {**cfg_id, "connection_string": "postgresql://user:secret@host/db"}
        h_id = compute_semantic_hash(cfg_id, [], node_type="sql_database")
        h_both = compute_semantic_hash(cfg_both, [], node_type="sql_database")
        assert h_id == h_both, "connection_string não deve afetar o hash"

    def test_connection_id_diferente_hash_diferente(self) -> None:
        cfg1 = {"connection_id": "conn-1", "query": "SELECT 1"}
        cfg2 = {"connection_id": "conn-2", "query": "SELECT 1"}
        h1 = compute_semantic_hash(cfg1, [], node_type="sql_database")
        h2 = compute_semantic_hash(cfg2, [], node_type="sql_database")
        assert h1 != h2


# ─── input_fingerprints afetam hash ──────────────────────────────────────────

class TestInputFingerprints:

    def test_input_fingerprint_diferente_hash_diferente(self) -> None:
        cfg = {"condition": "amount > 100"}
        h1 = compute_semantic_hash(cfg, ["fp_v1"], node_type="filter")
        h2 = compute_semantic_hash(cfg, ["fp_v2"], node_type="filter")
        assert h1 != h2

    def test_sem_fingerprints(self) -> None:
        cfg = {"condition": "amount > 100"}
        h = compute_semantic_hash(cfg, [], node_type="filter")
        assert isinstance(h, str)
        assert len(h) == 32

    def test_fingerprints_ordem_canonica(self) -> None:
        """Ordem de input_fingerprints não importa (sorted internamente)."""
        cfg = {"join_type": "inner"}
        h1 = compute_semantic_hash(cfg, ["fp_a", "fp_b"], node_type="join")
        h2 = compute_semantic_hash(cfg, ["fp_b", "fp_a"], node_type="join")
        assert h1 == h2


# ─── algo_version invalida cache ─────────────────────────────────────────────

class TestAlgoVersion:

    def test_versao_diferente_hash_diferente(self) -> None:
        cfg = {"query": "SELECT 1", "connection_id": "c1"}
        h1 = compute_semantic_hash(cfg, [], algo_version=1, node_type="sql_database")
        h2 = compute_semantic_hash(cfg, [], algo_version=2, node_type="sql_database")
        assert h1 != h2


# ─── Mudança de config muda hash ─────────────────────────────────────────────

class TestConfigChanges:

    def test_query_diferente_hash_diferente(self) -> None:
        h1 = compute_semantic_hash({"query": "SELECT 1"}, [], node_type="sql_database")
        h2 = compute_semantic_hash({"query": "SELECT 2"}, [], node_type="sql_database")
        assert h1 != h2

    def test_node_type_diferente_hash_diferente(self) -> None:
        cfg = {"condition": "x > 1"}
        h1 = compute_semantic_hash(cfg, [], node_type="filter")
        h2 = compute_semantic_hash(cfg, [], node_type="mapper")
        assert h1 != h2

    def test_formato_hex_32_chars(self) -> None:
        h = compute_semantic_hash({"a": "b"}, [], node_type="filter")
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


# ─── fingerprint_schema ───────────────────────────────────────────────────────

class TestFingerprintSchema:

    def test_schema_identico_mesmo_fingerprint(self) -> None:
        schema = [{"name": "id", "data_type": "INTEGER"}, {"name": "name", "data_type": "VARCHAR"}]
        assert fingerprint_schema(schema) == fingerprint_schema(schema)

    def test_schema_diferente_fingerprint_diferente(self) -> None:
        s1 = [{"name": "id", "data_type": "INTEGER"}]
        s2 = [{"name": "id", "data_type": "VARCHAR"}]
        assert fingerprint_schema(s1) != fingerprint_schema(s2)

    def test_fingerprint_16_chars(self) -> None:
        fp = fingerprint_schema([{"name": "x", "data_type": "INTEGER"}])
        assert len(fp) == 16
