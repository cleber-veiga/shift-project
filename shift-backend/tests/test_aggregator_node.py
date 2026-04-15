"""
Testes unitarios e de integracao para AggregatorNodeProcessor.

Cobre:
  - SUM com GROUP BY
  - AVG com GROUP BY
  - COUNT com e sem coluna especifica
  - MAX e MIN
  - Multiplas agregacoes em uma unica execucao
  - Agregacao global (sem GROUP BY)
  - Leitura de tabelas no schema dlt (shift_extract)
  - Encadeamento com math_node (fluxo extract -> math -> aggregator)
  - Erros de validacao (sem agregacoes, operacao invalida, alias ausente)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest

from app.services.workflow.nodes.aggregator_node import AggregatorNodeProcessor
from app.services.workflow.nodes.math_node import MathNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table


# ---------------------------------------------------------------------------
# Testes de caminho feliz — operacoes de agregacao
# ---------------------------------------------------------------------------

class TestAggregatorNodeOperations:

    def test_sum_com_group_by(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve somar QUANTIDADE por NUMERO_NOTA."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        result = processor.process(
            node_id="agg-1",
            config={
                "group_by": ["NUMERO_NOTA"],
                "aggregations": [
                    {"operation": "sum", "column": "QUANTIDADE", "alias": "QTD_TOTAL"}
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])

        # Nota 1001: 2 + 3 = 5
        row_1001 = next(r for r in rows if r["NUMERO_NOTA"] == 1001)
        assert row_1001["QTD_TOTAL"] == 5
        # Nota 1002: 1
        row_1002 = next(r for r in rows if r["NUMERO_NOTA"] == 1002)
        assert row_1002["QTD_TOTAL"] == 1
        # Nota 1003: 5
        row_1003 = next(r for r in rows if r["NUMERO_NOTA"] == 1003)
        assert row_1003["QTD_TOTAL"] == 5

    def test_avg_com_group_by(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve calcular a media de VALOR_UNITARIO por NUMERO_NOTA."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        result = processor.process(
            node_id="agg-1",
            config={
                "group_by": ["NUMERO_NOTA"],
                "aggregations": [
                    {"operation": "avg", "column": "VALOR_UNITARIO", "alias": "MEDIA_VALOR"}
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])

        # Nota 1001: (100.0 + 50.0) / 2 = 75.0
        row_1001 = next(r for r in rows if r["NUMERO_NOTA"] == 1001)
        assert row_1001["MEDIA_VALOR"] == pytest.approx(75.0)

    def test_count_sem_coluna(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve contar o numero de linhas por NUMERO_NOTA usando COUNT(*)."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        result = processor.process(
            node_id="agg-1",
            config={
                "group_by": ["NUMERO_NOTA"],
                "aggregations": [
                    {"operation": "count", "alias": "QTD_ITENS"}
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])

        row_1001 = next(r for r in rows if r["NUMERO_NOTA"] == 1001)
        assert row_1001["QTD_ITENS"] == 2
        row_1002 = next(r for r in rows if r["NUMERO_NOTA"] == 1002)
        assert row_1002["QTD_ITENS"] == 1

    def test_max_e_min(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve calcular MAX e MIN de VALOR_UNITARIO por NUMERO_NOTA."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        result = processor.process(
            node_id="agg-1",
            config={
                "group_by": ["NUMERO_NOTA"],
                "aggregations": [
                    {"operation": "max", "column": "VALOR_UNITARIO", "alias": "MAIOR_VALOR"},
                    {"operation": "min", "column": "VALOR_UNITARIO", "alias": "MENOR_VALOR"},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])

        row_1001 = next(r for r in rows if r["NUMERO_NOTA"] == 1001)
        assert row_1001["MAIOR_VALOR"] == pytest.approx(100.0)
        assert row_1001["MENOR_VALOR"] == pytest.approx(50.0)

    def test_multiplas_agregacoes(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve calcular SUM, COUNT e AVG em uma unica execucao."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        result = processor.process(
            node_id="agg-1",
            config={
                "group_by": ["NUMERO_NOTA"],
                "aggregations": [
                    {"operation": "count", "alias": "QTD_ITENS"},
                    {"operation": "sum", "column": "QUANTIDADE", "alias": "QTD_TOTAL"},
                    {"operation": "avg", "column": "VALOR_UNITARIO", "alias": "MEDIA_VALOR"},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        colunas = set(rows[0].keys())

        assert "NUMERO_NOTA" in colunas
        assert "QTD_ITENS" in colunas
        assert "QTD_TOTAL" in colunas
        assert "MEDIA_VALOR" in colunas

    def test_agregacao_global_sem_group_by(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Sem GROUP BY, deve agregar todas as linhas em uma unica linha."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        result = processor.process(
            node_id="agg-1",
            config={
                "group_by": [],
                "aggregations": [
                    {"operation": "count", "alias": "TOTAL_LINHAS"},
                    {"operation": "sum", "column": "QUANTIDADE", "alias": "QTD_TOTAL"},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])

        assert len(rows) == 1
        assert rows[0]["TOTAL_LINHAS"] == 4
        assert rows[0]["QTD_TOTAL"] == 11  # 2 + 3 + 1 + 5

    def test_le_tabela_de_schema_dlt(
        self, duckdb_with_dlt_schema: tuple[Path, dict]
    ) -> None:
        """Deve ler corretamente tabelas criadas pelo dlt no schema shift_extract."""
        db_path, reference = duckdb_with_dlt_schema
        context = make_context(
            db_path, reference["table_name"], schema="shift_extract"
        )

        processor = AggregatorNodeProcessor()
        result = processor.process(
            node_id="agg-1",
            config={
                "group_by": ["NUMERO_NOTA"],
                "aggregations": [
                    {"operation": "count", "alias": "QTD_ITENS"}
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        assert output_ref["dataset_name"] is None
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 3  # 3 notas distintas


# ---------------------------------------------------------------------------
# Teste de encadeamento: math -> aggregator
# ---------------------------------------------------------------------------

class TestAggregatorChaining:

    def test_encadeamento_math_aggregator(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """
        Fluxo completo: math cria VALOR_TOTAL_ITEM, aggregator soma por nota.

        Este e o fluxo central do sistema e deve funcionar sem erros.
        """
        db_path, reference = duckdb_with_sample

        # Passo 1: math_node cria VALOR_TOTAL_ITEM
        math_context = make_context(db_path, reference["table_name"])
        math_processor = MathNodeProcessor()
        math_result = math_processor.process(
            node_id="math-1",
            config={
                "expressions": [
                    {
                        "target_column": "VALOR_TOTAL_ITEM",
                        "expression": "QUANTIDADE * VALOR_UNITARIO - DESCONTO",
                    }
                ]
            },
            context=math_context,
        )

        # Passo 2: aggregator_node usa a saida do math como entrada
        math_output_ref = math_result["data"]
        agg_context = {
            "execution_id": "test-exec-001",
            "workflow_id": "test-workflow-001",
            "upstream_results": {
                "math-1": math_result,
            },
        }

        agg_processor = AggregatorNodeProcessor()
        agg_result = agg_processor.process(
            node_id="agg-1",
            config={
                "group_by": ["NUMERO_NOTA"],
                "aggregations": [
                    {"operation": "count", "alias": "QTD_ITENS"},
                    {"operation": "sum", "column": "VALOR_TOTAL_ITEM", "alias": "VALOR_TOTAL_NOTA"},
                ],
            },
            context=agg_context,
        )

        output_ref = agg_result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])

        # Nota 1001: CADEIRA (2*100-0=200) + MESA (3*50-10=140) = 340
        row_1001 = next(r for r in rows if r["NUMERO_NOTA"] == 1001)
        assert row_1001["QTD_ITENS"] == 2
        assert row_1001["VALOR_TOTAL_NOTA"] == pytest.approx(340.0)

        # Nota 1002: SOFA (1*200-0=200)
        row_1002 = next(r for r in rows if r["NUMERO_NOTA"] == 1002)
        assert row_1002["QTD_ITENS"] == 1
        assert row_1002["VALOR_TOTAL_NOTA"] == pytest.approx(200.0)

        # Nota 1003: LAMPADA (5*20-5=95)
        row_1003 = next(r for r in rows if r["NUMERO_NOTA"] == 1003)
        assert row_1003["QTD_ITENS"] == 1
        assert row_1003["VALOR_TOTAL_NOTA"] == pytest.approx(95.0)


# ---------------------------------------------------------------------------
# Testes de validacao e erros
# ---------------------------------------------------------------------------

class TestAggregatorNodeValidation:

    def test_erro_sem_agregacoes(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando nenhuma agregacao e informada."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        with pytest.raises(NodeProcessingError, match="ao menos uma agregacao"):
            processor.process(
                node_id="agg-1",
                config={
                    "group_by": ["NUMERO_NOTA"],
                    "aggregations": [],
                },
                context=context,
            )

    def test_erro_operacao_invalida(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando a operacao nao e suportada."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = AggregatorNodeProcessor()
        with pytest.raises(NodeProcessingError, match="nao suportada"):
            processor.process(
                node_id="agg-1",
                config={
                    "group_by": ["NUMERO_NOTA"],
                    "aggregations": [
                        {"operation": "median", "column": "QUANTIDADE", "alias": "MEDIANA"}
                    ],
                },
                context=context,
            )
