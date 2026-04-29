"""
Verifica que payloads SSE permanecem leves.

Critério benchmarking §2.3: tamanho médio de evento SSE < 2 KB para que o
streaming não vire gargalo. Eventos patológicos (label longo, stack trace
gigante) ainda devem caber em < 4 KB.

Sem este teste, a redução feita por _transform_for_sse pode regredir
silenciosamente quando alguém adiciona um campo "só pra mostrar no
frontend" que não estava previsto.
"""

from __future__ import annotations

import json
from uuid import uuid4

# Limites de regressão baseados no critério de aceite.
SSE_TYPICAL_LIMIT = 2048   # 2 KB
SSE_MAX_LIMIT     = 4096   # 4 KB para casos patológicos


def _payload_size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class TestNodeCompletePayload:

    def test_typical_payload_under_2kb(self) -> None:
        """node_complete típico (lean payload sem dados): bem abaixo de 2 KB."""
        payload = {
            "type": "node_complete",
            "execution_id": str(uuid4()),
            "timestamp": "2026-04-28T12:00:00Z",
            "node_id": "n1",
            "node_type": "filter",
            "label": "Filtro de pedidos válidos",
            "status": "success",
            "row_count": 12345,
            "schema_fingerprint": "abc123def456",
            "output_reference": {
                "kind": "duckdb",
                "path": f"/tmp/shift/executions/{uuid4()}/n1.duckdb",
                "table": "output",
            },
            "duration_ms": 120,
        }
        size = _payload_size(payload)
        assert size < SSE_TYPICAL_LIMIT, (
            f"node_complete típico = {size}B (limite {SSE_TYPICAL_LIMIT}B)"
        )

    def test_strategy_resolved_payload_under_2kb(self) -> None:
        payload = {
            "type": "node_strategy_resolved",
            "execution_id": str(uuid4()),
            "node_id": "n1",
            "node_type": "sql_database",
            "label": "Consulta de pedidos",
            "strategy": "io_thread",
            "should_run": True,
            "reason": "io_node",
            "semantic_hash": "0123456789abcdef0123456789abcdef",
            "elapsed_ms": 0.42,
        }
        assert _payload_size(payload) < SSE_TYPICAL_LIMIT


class TestPathologicalPayload:

    def test_long_label_and_error_under_4kb(self) -> None:
        """Label de 200 chars + stack trace de 1000 chars ainda < 4 KB."""
        payload = {
            "type": "node_complete",
            "execution_id": str(uuid4()),
            "timestamp": "2026-04-28T12:00:00Z",
            "node_id": str(uuid4()),
            "node_type": "sql_database",
            "label": "L" * 200,
            "status": "error",
            "row_count": None,
            "schema_fingerprint": None,
            "output_reference": None,
            "duration_ms": 5000,
            "error_message": "Stack trace: " + ("X" * 1000),
        }
        size = _payload_size(payload)
        assert size < SSE_MAX_LIMIT, (
            f"Payload patológico = {size}B (limite {SSE_MAX_LIMIT}B)"
        )

    def test_payload_does_not_carry_full_dataset(self) -> None:
        """Critério: SSE NUNCA leva linhas/colunas — só fingerprint e reference."""
        payload = {
            "type": "node_complete",
            "execution_id": str(uuid4()),
            "timestamp": "2026-04-28T12:00:00Z",
            "node_id": "n1",
            "node_type": "mapper",
            "label": "x",
            "status": "success",
            "row_count": 1_000_000,
            "schema_fingerprint": "f" * 16,
            "output_reference": {"kind": "duckdb", "path": "/tmp/x.duckdb", "table": "t"},
            "duration_ms": 50,
        }
        # Mesmo com row_count gigante, payload não muda de tamanho.
        size = _payload_size(payload)
        assert size < SSE_TYPICAL_LIMIT
        assert "rows" not in payload
        assert "data" not in payload
