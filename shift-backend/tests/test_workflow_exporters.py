"""
Testes dos exportadores SQL e Python (Fase 9).

Os exportadores sao funcoes puras — nao precisam de DB. Os testes verificam:
- structural assertions sobre o output (substrings esperadas);
- erro estruturado para nos nao-suportados;
- que o SQL gerado e parseavel pelo DuckDB (smoke test);
- que o Python gerado e sintaticamente valido (compile()).
"""

from __future__ import annotations

import ast
import re

import duckdb
import pytest

from app.services.workflow.exporters import (
    PythonExporter,
    SQLExporter,
    UnsupportedNodeError,
)


# ---------------------------------------------------------------------------
# Fixtures de workflows
# ---------------------------------------------------------------------------

def _wf_linear_pipeline() -> dict:
    """sql_database -> filter -> sort -> loadNode."""
    return {
        "id": "wf-linear",
        "name": "linear_pipeline",
        "nodes": [
            {"id": "extract", "type": "sql_database", "data": {
                "type": "sql_database",
                "connection_id": "11111111-2222-3333-4444-555555555555",
                "query": "SELECT * FROM orders WHERE created_at > '{{vars.CUTOFF_DATE}}'",
            }},
            {"id": "filter_recent", "type": "filter", "data": {
                "type": "filter",
                "conditions": [{"field": "amount", "operator": "gt", "value": 100}],
                "logic": "and",
            }},
            {"id": "top_n", "type": "sort", "data": {
                "type": "sort",
                "sort_columns": [{"column": "amount", "direction": "desc"}],
                "limit": 10,
            }},
            {"id": "load_top", "type": "loadNode", "data": {
                "type": "loadNode",
                "connection_id": "99999999-aaaa-bbbb-cccc-dddddddddddd",
                "target_table": "top_orders",
                "write_disposition": "replace",
            }},
        ],
        "edges": [
            {"id": "e1", "source": "extract", "target": "filter_recent"},
            {"id": "e2", "source": "filter_recent", "target": "top_n"},
            {"id": "e3", "source": "top_n", "target": "load_top"},
        ],
    }


def _wf_join_lookup() -> dict:
    """Inline data + join + lookup, sem connection externa."""
    return {
        "id": "wf-join",
        "name": "join_lookup",
        "nodes": [
            {"id": "orders", "type": "inline_data", "data": {
                "type": "inline_data",
                "data": [
                    {"order_id": 1, "customer_id": 10, "amount": 50.0},
                    {"order_id": 2, "customer_id": 11, "amount": 75.0},
                ],
            }},
            {"id": "customers", "type": "inline_data", "data": {
                "type": "inline_data",
                "data": [
                    {"id": 10, "name": "Alice"},
                    {"id": 11, "name": "Bob"},
                ],
            }},
            {"id": "regions", "type": "inline_data", "data": {
                "type": "inline_data",
                "data": [
                    {"customer_id": 10, "region": "South"},
                    {"customer_id": 11, "region": "North"},
                ],
            }},
            {"id": "orders_with_customer", "type": "join", "data": {
                "type": "join",
                "join_type": "inner",
                "conditions": [{"left_column": "customer_id", "right_column": "id"}],
            }},
            {"id": "with_region", "type": "lookup", "data": {
                "type": "lookup",
                "lookup_key": "customer_id",
                "dictionary_key": "customer_id",
                "return_columns": ["region"],
            }},
        ],
        "edges": [
            {"id": "e1", "source": "orders", "target": "orders_with_customer", "targetHandle": "left"},
            {"id": "e2", "source": "customers", "target": "orders_with_customer", "targetHandle": "right"},
            {"id": "e3", "source": "orders_with_customer", "target": "with_region", "targetHandle": "primary"},
            {"id": "e4", "source": "regions", "target": "with_region", "targetHandle": "dictionary"},
        ],
    }


def _wf_aggregator_dedup() -> dict:
    """Inline data -> aggregator -> deduplication."""
    return {
        "id": "wf-agg",
        "name": "aggregator_dedup",
        "nodes": [
            {"id": "src", "type": "inline_data", "data": {
                "type": "inline_data",
                "data": [
                    {"category": "A", "amount": 10.0},
                    {"category": "A", "amount": 20.0},
                    {"category": "B", "amount": 5.0},
                    {"category": "B", "amount": 5.0},
                ],
            }},
            {"id": "totals", "type": "aggregator", "data": {
                "type": "aggregator",
                "group_by": ["category"],
                "aggregations": [
                    {"column": "amount", "operation": "sum", "alias": "total_amount"},
                    {"operation": "count", "alias": "n_orders"},
                ],
            }},
            {"id": "deduped", "type": "deduplication", "data": {
                "type": "deduplication",
                "partition_by": ["category"],
                "order_by": "total_amount",
                "keep": "last",
            }},
        ],
        "edges": [
            {"id": "e1", "source": "src", "target": "totals"},
            {"id": "e2", "source": "totals", "target": "deduped"},
        ],
    }


def _wf_pivot_unpivot() -> dict:
    """inline_data -> pivot -> unpivot."""
    return {
        "id": "wf-pivot",
        "name": "pivot_unpivot",
        "nodes": [
            {"id": "src", "type": "inline_data", "data": {
                "type": "inline_data",
                "data": [
                    {"month": "Jan", "product": "X", "qty": 10},
                    {"month": "Jan", "product": "Y", "qty": 5},
                    {"month": "Feb", "product": "X", "qty": 8},
                    {"month": "Feb", "product": "Y", "qty": 3},
                ],
            }},
            {"id": "wide", "type": "pivot", "data": {
                "type": "pivot",
                "index_columns": ["month"],
                "pivot_column": "product",
                "value_column": "qty",
                "aggregations": ["sum"],
            }},
            {"id": "long_again", "type": "unpivot", "data": {
                "type": "unpivot",
                "index_columns": ["month"],
                # PIVOT do DuckDB com USING SUM(qty) AS sum gera colunas X_sum, Y_sum.
                "value_columns": ["X_sum", "Y_sum"],
                "variable_column_name": "product",
                "value_column_name": "qty",
            }},
        ],
        "edges": [
            {"id": "e1", "source": "src", "target": "wide"},
            {"id": "e2", "source": "wide", "target": "long_again"},
        ],
    }


def _wf_unsupported() -> dict:
    """Inclui dois nos nao suportados em V1."""
    return {
        "id": "wf-bad",
        "name": "with_unsupported",
        "nodes": [
            {"id": "src", "type": "inline_data", "data": {
                "type": "inline_data", "data": [{"a": 1}],
            }},
            {"id": "ai", "type": "code", "data": {
                "type": "code", "code": "x = 1",
            }},
            {"id": "http", "type": "http_request", "data": {
                "type": "http_request", "url": "http://example.com",
            }},
        ],
        "edges": [
            {"id": "e1", "source": "src", "target": "ai"},
            {"id": "e2", "source": "ai", "target": "http"},
        ],
    }


# ---------------------------------------------------------------------------
# SQL exporter — testes
# ---------------------------------------------------------------------------

class TestSQLExporter:
    def test_linear_pipeline_contains_each_node(self):
        sql = SQLExporter().export(_wf_linear_pipeline())

        # Cabecalho com metadados e variaveis declaradas.
        assert "Workflow: linear_pipeline" in sql
        assert "${CUTOFF_DATE}" in sql
        assert "conn_11111111" in sql

        # Cada no aparece como TEMP TABLE (exceto loadNode).
        assert 'CREATE OR REPLACE TEMPORARY TABLE "extract"' in sql
        assert 'CREATE OR REPLACE TEMPORARY TABLE "filter_recent"' in sql
        assert 'CREATE OR REPLACE TEMPORARY TABLE "top_n"' in sql
        assert 'CREATE OR REPLACE TEMPORARY TABLE "load_top"' not in sql

        # loadNode aparece como bloco de comentario com TODO.
        assert "TODO: write" in sql
        assert "target_table: top_orders" in sql

        # Final: SELECT do upstream do loadNode.
        assert 'SELECT * FROM "top_n";' in sql

    def test_join_lookup_uses_handles(self):
        sql = SQLExporter().export(_wf_join_lookup())

        # Join referencia 'orders' como l e 'customers' como r.
        assert re.search(r'FROM "orders" l\s+INNER JOIN "customers" r', sql), sql

        # Lookup usa primary/dictionary.
        assert 'FROM "orders_with_customer" p' in sql
        assert 'LEFT JOIN "regions" d ON' in sql

    def test_aggregator_renders_group_by(self):
        sql = SQLExporter().export(_wf_aggregator_dedup())
        assert 'SUM("amount") AS "total_amount"' in sql
        assert 'COUNT(*) AS "n_orders"' in sql
        assert 'GROUP BY "category"' in sql

    def test_deduplication_uses_row_number(self):
        sql = SQLExporter().export(_wf_aggregator_dedup())
        # keep="last" -> ORDER BY DESC.
        assert 'ROW_NUMBER() OVER (PARTITION BY "category" ORDER BY "total_amount" DESC)' in sql

    def test_pivot_uses_native_pivot(self):
        sql = SQLExporter().export(_wf_pivot_unpivot())
        assert "PIVOT" in sql
        assert "USING SUM" in sql
        assert "UNPIVOT INCLUDE NULLS" in sql

    def test_unsupported_raises(self):
        with pytest.raises(UnsupportedNodeError) as excinfo:
            SQLExporter().export(_wf_unsupported())
        unsupported = excinfo.value.unsupported
        types = sorted(item["node_type"] for item in unsupported)
        assert types == ["code", "http_request"]
        for item in unsupported:
            assert item["reason"]
            assert item["node_id"]

    def test_unsupported_reason_for_control_node(self):
        wf = {
            "id": "wf-ctrl",
            "name": "with_control",
            "nodes": [
                {"id": "src", "type": "inline_data", "data": {
                    "type": "inline_data", "data": [{"a": 1}],
                }},
                {"id": "branch", "type": "if_node", "data": {"type": "if_node"}},
            ],
            "edges": [{"id": "e1", "source": "src", "target": "branch"}],
        }
        with pytest.raises(UnsupportedNodeError) as excinfo:
            SQLExporter().export(wf)
        reasons = [u["reason"] for u in excinfo.value.unsupported]
        assert any("controle de fluxo" in r for r in reasons)


# ---------------------------------------------------------------------------
# DuckDB parse smoke test
# ---------------------------------------------------------------------------

class TestDuckDBExecutable:
    """Confere que o SQL exportado roda no DuckDB para fixtures sem fontes externas."""

    def test_join_lookup_runs_end_to_end(self):
        sql = SQLExporter().export(_wf_join_lookup())
        con = duckdb.connect(":memory:")
        con.execute(sql.split("-- ── Node:")[0])  # header (no-op SQL apenas comentario)
        # Executa cada bloco de TEMP TABLE.
        con.execute(sql)
        rows = con.execute('SELECT order_id, region FROM "with_region" ORDER BY order_id').fetchall()
        assert rows == [(1, "South"), (2, "North")]

    def test_aggregator_dedup_runs_end_to_end(self):
        sql = SQLExporter().export(_wf_aggregator_dedup())
        con = duckdb.connect(":memory:")
        con.execute(sql)
        rows = con.execute('SELECT * FROM "deduped" ORDER BY category').fetchall()
        # Para cada category mantemos exatamente 1 linha (deduplication).
        assert len(rows) == 2

    def test_pivot_unpivot_runs(self):
        sql = SQLExporter().export(_wf_pivot_unpivot())
        con = duckdb.connect(":memory:")
        con.execute(sql)
        # Resultado final: 4 linhas (2 meses x 2 produtos), colunas month/product/qty.
        rows = con.execute(
            'SELECT month, product, qty FROM "long_again" ORDER BY month, product'
        ).fetchall()
        assert rows == [
            ("Feb", "X_sum", 8), ("Feb", "Y_sum", 3),
            ("Jan", "X_sum", 10), ("Jan", "Y_sum", 5),
        ]


# ---------------------------------------------------------------------------
# Python exporter
# ---------------------------------------------------------------------------

class TestPythonExporter:
    def test_linear_pipeline_compiles(self):
        py = PythonExporter().export(_wf_linear_pipeline())
        # Sintaxe valida.
        ast.parse(py)
        # Variaveis e conexoes na frente.
        assert "CUTOFF_DATE = os.environ['CUTOFF_DATE']" in py
        assert "CONN_11111111_URL" in py
        # Body dentro de main().
        assert "def main() -> None:" in py
        assert "con.execute(" in py

    def test_unsupported_raises(self):
        with pytest.raises(UnsupportedNodeError):
            PythonExporter().export(_wf_unsupported())

    def test_no_connections_no_sqlalchemy_import(self):
        py = PythonExporter().export(_wf_aggregator_dedup())
        ast.parse(py)
        # Workflow sem connection_id nao deve importar sqlalchemy.
        assert "from sqlalchemy" not in py
        assert "create_engine" not in py
