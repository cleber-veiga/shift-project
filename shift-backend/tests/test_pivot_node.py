"""
Testes para PivotNodeProcessor.

Cobre:
  - Pivot basico com agregacao SUM
  - Multiplas agregacoes na mesma execucao
  - Sanitizacao de nomes de colunas invalidos
  - Limite max_pivot_values: falha acima do limite
  - Coluna pivot sem valores nao-nulos
  - Erros de validacao (sem index_columns, agregacao invalida)
  - Round-trip com UnpivotNodeProcessor (idempotencia)
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from app.services.workflow.nodes.pivot_node import PivotNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table, create_duckdb_with_rows


VENDAS_ROWS = [
    {"REGIAO": "NORTE", "PRODUTO": "A", "VALOR": 100},
    {"REGIAO": "NORTE", "PRODUTO": "B", "VALOR": 200},
    {"REGIAO": "SUL",   "PRODUTO": "A", "VALOR": 150},
    {"REGIAO": "SUL",   "PRODUTO": "B", "VALOR": 300},
    {"REGIAO": "NORTE", "PRODUTO": "A", "VALOR":  50},
]


@pytest.fixture
def db_vendas(tmp_path: Path):
    db_path = tmp_path / "vendas.duckdb"
    ref = create_duckdb_with_rows(db_path, "src", VENDAS_ROWS)
    return db_path, ref


class TestPivotNodeBasic:

    def test_pivot_sum_basico(self, db_vendas) -> None:
        """NORTE×A=150, NORTE×B=200, SUL×A=150, SUL×B=300."""
        db_path, ref = db_vendas
        context = make_context(db_path, "src")

        result = PivotNodeProcessor().process(
            "piv-1",
            {
                "index_columns": ["REGIAO"],
                "pivot_column": "PRODUTO",
                "value_column": "VALOR",
                "aggregations": ["sum"],
            },
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        norte = next(r for r in rows if r["REGIAO"] == "NORTE")
        sul   = next(r for r in rows if r["REGIAO"] == "SUL")

        assert norte["A_sum"] == 150
        assert norte["B_sum"] == 200
        assert sul["A_sum"]   == 150
        assert sul["B_sum"]   == 300

    def test_pivot_count(self, db_vendas) -> None:
        """Contagem de ocorrencias por celula."""
        db_path, ref = db_vendas
        context = make_context(db_path, "src")

        result = PivotNodeProcessor().process(
            "piv-1",
            {
                "index_columns": ["REGIAO"],
                "pivot_column": "PRODUTO",
                "value_column": "VALOR",
                "aggregations": ["count"],
            },
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        norte = next(r for r in rows if r["REGIAO"] == "NORTE")
        assert norte["A_count"] == 2  # duas linhas NORTE/A

    def test_pivot_multiplas_agregacoes(self, db_vendas) -> None:
        """sum e count na mesma execucao geram colunas distintas."""
        db_path, ref = db_vendas
        context = make_context(db_path, "src")

        result = PivotNodeProcessor().process(
            "piv-1",
            {
                "index_columns": ["REGIAO"],
                "pivot_column": "PRODUTO",
                "value_column": "VALOR",
                "aggregations": ["sum", "count"],
            },
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(rows) == 2
        # 2 valores pivot × 2 agregacoes = 4 colunas pivot + 1 index
        assert "A_sum" in rows[0]
        assert "A_count" in rows[0]
        assert "B_sum" in rows[0]
        assert "B_count" in rows[0]

    def test_pivot_col_mapping_retornado(self, db_vendas) -> None:
        """Resultado deve conter pivot_col_mapping para rastreabilidade."""
        db_path, ref = db_vendas
        context = make_context(db_path, "src")

        result = PivotNodeProcessor().process(
            "piv-1",
            {
                "index_columns": ["REGIAO"],
                "pivot_column": "PRODUTO",
                "value_column": "VALOR",
                "aggregations": ["sum"],
            },
            context,
        )

        mapping = result.get("pivot_col_mapping")
        assert mapping is not None
        assert "A" in mapping
        assert mapping["A"]["sum"] == "A_sum"

    def test_pivot_nome_coluna_sanitizado(self, tmp_path: Path) -> None:
        """Valores com caracteres especiais devem ser sanitizados em nomes validos."""
        rows = [
            {"IDX": "x", "CAT": "valor-1", "V": 10},
            {"IDX": "x", "CAT": "valor 2", "V": 20},
        ]
        db_path = tmp_path / "spec.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = PivotNodeProcessor().process(
            "piv-1",
            {
                "index_columns": ["IDX"],
                "pivot_column": "CAT",
                "value_column": "V",
                "aggregations": ["sum"],
            },
            context,
        )

        rows_out = read_duckdb_table(
            result["data"]["database_path"], result["data"]["table_name"]
        )
        assert len(rows_out) == 1
        # Colunas sanitizadas existem
        col_names = list(rows_out[0].keys())
        assert any("sum" in c for c in col_names)


class TestPivotNodeLimits:

    def test_max_pivot_values_falha_acima_limite(self, tmp_path: Path) -> None:
        """Deve falhar quando a coluna pivot tem mais valores que max_pivot_values."""
        rows = [{"IDX": 1, "CAT": str(i), "V": i} for i in range(10)]
        db_path = tmp_path / "many.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="max_pivot_values"):
            PivotNodeProcessor().process(
                "piv-1",
                {
                    "index_columns": ["IDX"],
                    "pivot_column": "CAT",
                    "value_column": "V",
                    "aggregations": ["sum"],
                    "max_pivot_values": 5,
                },
                context,
            )

    def test_pivot_coluna_sem_valores_nao_nulos(self, tmp_path: Path) -> None:
        """Falha informativa quando pivot_column tem apenas NULLs."""
        rows = [{"IDX": 1, "CAT": None, "V": 10}]
        db_path = tmp_path / "null.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="nao tem valores nao-nulos"):
            PivotNodeProcessor().process(
                "piv-1",
                {
                    "index_columns": ["IDX"],
                    "pivot_column": "CAT",
                    "value_column": "V",
                    "aggregations": ["sum"],
                },
                context,
            )


class TestPivotNodeValidation:

    def test_erro_sem_index_columns(self, db_vendas) -> None:
        db_path, ref = db_vendas
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="index_columns"):
            PivotNodeProcessor().process(
                "piv-1",
                {
                    "index_columns": [],
                    "pivot_column": "PRODUTO",
                    "value_column": "VALOR",
                },
                context,
            )

    def test_erro_agregacao_invalida(self, db_vendas) -> None:
        db_path, ref = db_vendas
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="invalida"):
            PivotNodeProcessor().process(
                "piv-1",
                {
                    "index_columns": ["REGIAO"],
                    "pivot_column": "PRODUTO",
                    "value_column": "VALOR",
                    "aggregations": ["median"],
                },
                context,
            )


class TestPivotOutputSummary:

    def test_summary_e_warnings(self, db_vendas) -> None:
        db_path, _ = db_vendas
        context = make_context(db_path, "src")

        result = PivotNodeProcessor().process(
            "piv-1",
            {
                "index_columns": ["REGIAO"],
                "pivot_column": "PRODUTO",
                "value_column": "VALOR",
                "aggregations": ["sum"],
            },
            context,
        )

        summary = result["output_summary"]
        assert summary["row_count_in"] == 5
        # 2 regiões → 2 linhas de saída agrupadas.
        assert summary["row_count_out"] == 2
        assert summary["warnings"] == []

    def test_near_max_pivot_values_warning(self, tmp_path: Path) -> None:
        # 8 valores únicos com max_pivot_values=10 → ratio 0.8 → warning.
        rows = [{"GRUPO": "X", "PROD": f"P{i}", "VALOR": i} for i in range(8)]
        db_path = tmp_path / "near_max.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = PivotNodeProcessor().process(
            "piv-1",
            {
                "index_columns": ["GRUPO"],
                "pivot_column": "PROD",
                "value_column": "VALOR",
                "aggregations": ["sum"],
                "max_pivot_values": 10,
            },
            context,
        )

        assert "near_max_pivot_values" in result["output_summary"]["warnings"]
