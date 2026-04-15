"""
Testes unitarios e de integracao para MathNodeProcessor.

Cobre:
  - Adicao de coluna calculada simples
  - Multiplas colunas calculadas em uma unica execucao
  - Preservacao das colunas originais
  - Leitura correta de tabelas criadas pelo dlt (schema shift_extract)
  - Erro quando nenhuma expressao e informada
  - Erro quando expressao esta incompleta (sem target_column ou expression)
  - Erro quando a expressao SQL e invalida
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.workflow.nodes.math_node import MathNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table


# ---------------------------------------------------------------------------
# Testes de caminho feliz
# ---------------------------------------------------------------------------

class TestMathNodeHappyPath:

    def test_adiciona_coluna_calculada_simples(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve adicionar uma coluna VALOR_TOTAL = QUANTIDADE * VALOR_UNITARIO."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        result = processor.process(
            node_id="math-1",
            config={
                "expressions": [
                    {
                        "target_column": "VALOR_TOTAL",
                        "expression": "QUANTIDADE * VALOR_UNITARIO",
                    }
                ]
            },
            context=context,
        )

        assert result["status"] == "completed"
        assert result["node_id"] == "math-1"

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])

        assert len(rows) == 4
        # Linha 1: 2 * 100.0 = 200.0
        row_1001_a = next(r for r in rows if r["PRODUTO"] == "CADEIRA")
        assert row_1001_a["VALOR_TOTAL"] == pytest.approx(200.0)
        # Linha 2: 3 * 50.0 = 150.0
        row_1001_b = next(r for r in rows if r["PRODUTO"] == "MESA")
        assert row_1001_b["VALOR_TOTAL"] == pytest.approx(150.0)

    def test_preserva_colunas_originais(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Todas as colunas originais devem estar presentes na saida."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        result = processor.process(
            node_id="math-1",
            config={
                "expressions": [
                    {"target_column": "VALOR_TOTAL", "expression": "QUANTIDADE * VALOR_UNITARIO"}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        colunas = set(rows[0].keys())

        assert "NUMERO_NOTA" in colunas
        assert "QUANTIDADE" in colunas
        assert "VALOR_UNITARIO" in colunas
        assert "DESCONTO" in colunas
        assert "PRODUTO" in colunas
        assert "VALOR_TOTAL" in colunas

    def test_multiplas_expressoes(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve adicionar multiplas colunas calculadas em uma unica execucao."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        result = processor.process(
            node_id="math-1",
            config={
                "expressions": [
                    {"target_column": "VALOR_BRUTO", "expression": "QUANTIDADE * VALOR_UNITARIO"},
                    {"target_column": "VALOR_LIQUIDO", "expression": "QUANTIDADE * VALOR_UNITARIO - DESCONTO"},
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        colunas = set(rows[0].keys())

        assert "VALOR_BRUTO" in colunas
        assert "VALOR_LIQUIDO" in colunas

        row_mesa = next(r for r in rows if r["PRODUTO"] == "MESA")
        assert row_mesa["VALOR_BRUTO"] == pytest.approx(150.0)   # 3 * 50
        assert row_mesa["VALOR_LIQUIDO"] == pytest.approx(140.0)  # 150 - 10

    def test_expressao_com_funcao_sql(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve suportar funcoes SQL nativas do DuckDB nas expressoes."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        result = processor.process(
            node_id="math-1",
            config={
                "expressions": [
                    {"target_column": "PRODUTO_UPPER", "expression": "UPPER(PRODUTO)"}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert all(r["PRODUTO_UPPER"] == r["PRODUTO"].upper() for r in rows)

    def test_le_tabela_de_schema_dlt(
        self, duckdb_with_dlt_schema: tuple[Path, dict]
    ) -> None:
        """Deve ler corretamente tabelas criadas pelo dlt no schema shift_extract."""
        db_path, reference = duckdb_with_dlt_schema
        assert reference["dataset_name"] == "shift_extract"

        context = make_context(
            db_path, reference["table_name"], schema="shift_extract"
        )

        processor = MathNodeProcessor()
        result = processor.process(
            node_id="math-1",
            config={
                "expressions": [
                    {"target_column": "VALOR_TOTAL", "expression": "QUANTIDADE * VALOR_UNITARIO"}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        # A tabela de saida deve estar no schema main (sem dataset_name)
        assert output_ref["dataset_name"] is None

        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 4

    def test_output_field_customizado(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve usar o output_field customizado quando informado."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        result = processor.process(
            node_id="math-1",
            config={
                "output_field": "resultado_math",
                "expressions": [
                    {"target_column": "DOBRO", "expression": "QUANTIDADE * 2"}
                ],
            },
            context=context,
        )

        assert result["output_field"] == "resultado_math"
        assert "resultado_math" in result
        assert result["resultado_math"]["storage_type"] == "duckdb"


# ---------------------------------------------------------------------------
# Testes de validacao e erros
# ---------------------------------------------------------------------------

class TestMathNodeValidation:

    def test_erro_sem_expressoes(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando nenhuma expressao e informada."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        with pytest.raises(NodeProcessingError, match="informe ao menos uma expressao"):
            processor.process(
                node_id="math-1",
                config={"expressions": []},
                context=context,
            )

    def test_erro_expressao_sem_target_column(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando target_column esta ausente."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        with pytest.raises(NodeProcessingError, match="target_column"):
            processor.process(
                node_id="math-1",
                config={
                    "expressions": [{"expression": "QUANTIDADE * 2"}]
                },
                context=context,
            )

    def test_erro_expressao_sem_expression(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando expression esta ausente."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        with pytest.raises(NodeProcessingError, match="expression"):
            processor.process(
                node_id="math-1",
                config={
                    "expressions": [{"target_column": "NOVO"}]
                },
                context=context,
            )

    def test_erro_sql_invalido(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve propagar erro quando a expressao SQL e invalida."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MathNodeProcessor()
        with pytest.raises(Exception):
            processor.process(
                node_id="math-1",
                config={
                    "expressions": [
                        {"target_column": "ERRO", "expression": "COLUNA_INEXISTENTE * 2"}
                    ]
                },
                context=context,
            )
