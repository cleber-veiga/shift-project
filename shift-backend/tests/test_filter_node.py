"""
Testes unitarios e de integracao para FilterNodeProcessor.

Cobre:
  - Filtro com operador eq (igual)
  - Filtro com operador ne (diferente)
  - Filtro com operadores de comparacao (gt, lt, gte, lte)
  - Filtro com operadores LIKE e ILIKE
  - Filtro com operador IN e NOT IN
  - Filtro com IS NULL e IS NOT NULL
  - Filtro com operador contains
  - Logica AND (padrao) e OR entre multiplas condicoes
  - Resultado vazio quando nenhuma linha satisfaz o filtro
  - Leitura de tabelas no schema dlt (shift_extract)
  - Erros de validacao (sem condicoes, logic invalido, operador invalido)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.workflow.nodes.filter_node import FilterNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table, create_duckdb_with_rows


# ---------------------------------------------------------------------------
# Testes de caminho feliz — operadores basicos
# ---------------------------------------------------------------------------

class TestFilterNodeOperators:

    def test_filtro_eq(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar apenas as linhas onde NUMERO_NOTA = 1001."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [{"field": "NUMERO_NOTA", "operator": "eq", "value": 1001}]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 2
        assert all(r["NUMERO_NOTA"] == 1001 for r in rows)

    def test_filtro_ne(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar linhas onde NUMERO_NOTA != 1001."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [{"field": "NUMERO_NOTA", "operator": "ne", "value": 1001}]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 2
        assert all(r["NUMERO_NOTA"] != 1001 for r in rows)

    def test_filtro_gt(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar linhas onde VALOR_UNITARIO > 50."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [{"field": "VALOR_UNITARIO", "operator": "gt", "value": 50.0}]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert all(r["VALOR_UNITARIO"] > 50.0 for r in rows)

    def test_filtro_lte(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar linhas onde QUANTIDADE <= 2."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [{"field": "QUANTIDADE", "operator": "lte", "value": 2}]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert all(r["QUANTIDADE"] <= 2 for r in rows)

    def test_filtro_in(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar linhas onde NUMERO_NOTA IN (1001, 1003)."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [
                    {"field": "NUMERO_NOTA", "operator": "in", "value": [1001, 1003]}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 3
        assert all(r["NUMERO_NOTA"] in (1001, 1003) for r in rows)

    def test_filtro_not_in(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar linhas onde NUMERO_NOTA NOT IN (1001)."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [
                    {"field": "NUMERO_NOTA", "operator": "not_in", "value": [1001]}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 2
        assert all(r["NUMERO_NOTA"] != 1001 for r in rows)

    def test_filtro_contains(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar linhas onde PRODUTO contem 'A'."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [
                    {"field": "PRODUTO", "operator": "contains", "value": "A"}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert all("A" in r["PRODUTO"] for r in rows)

    def test_filtro_like(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar linhas onde PRODUTO LIKE 'C%'."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [
                    {"field": "PRODUTO", "operator": "like", "value": "C%"}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 1
        assert rows[0]["PRODUTO"] == "CADEIRA"


# ---------------------------------------------------------------------------
# Testes de IS NULL / IS NOT NULL
# ---------------------------------------------------------------------------

class TestFilterNodeNullOperators:

    def test_filtro_is_null(self, tmp_path: Path) -> None:
        """Deve retornar apenas linhas onde DESCONTO IS NULL."""
        rows = [
            {"ID": 1, "NOME": "A", "DESCONTO": None},
            {"ID": 2, "NOME": "B", "DESCONTO": 10.0},
            {"ID": 3, "NOME": "C", "DESCONTO": None},
        ]
        db_path = tmp_path / "null_test.duckdb"
        reference = create_duckdb_with_rows(db_path, "source", rows)
        context = make_context(db_path, "source")

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [{"field": "DESCONTO", "operator": "is_null"}]
            },
            context=context,
        )

        output_ref = result["data"]
        result_rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(result_rows) == 2
        assert all(r["DESCONTO"] is None for r in result_rows)

    def test_filtro_is_not_null(self, tmp_path: Path) -> None:
        """Deve retornar apenas linhas onde DESCONTO IS NOT NULL."""
        rows = [
            {"ID": 1, "NOME": "A", "DESCONTO": None},
            {"ID": 2, "NOME": "B", "DESCONTO": 10.0},
        ]
        db_path = tmp_path / "null_test2.duckdb"
        reference = create_duckdb_with_rows(db_path, "source", rows)
        context = make_context(db_path, "source")

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [{"field": "DESCONTO", "operator": "is_not_null"}]
            },
            context=context,
        )

        output_ref = result["data"]
        result_rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(result_rows) == 1
        assert result_rows[0]["NOME"] == "B"


# ---------------------------------------------------------------------------
# Testes de logica AND / OR
# ---------------------------------------------------------------------------

class TestFilterNodeLogic:

    def test_logica_and_padrao(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Com logica AND, todas as condicoes devem ser satisfeitas."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "logic": "and",
                "conditions": [
                    {"field": "NUMERO_NOTA", "operator": "eq", "value": 1001},
                    {"field": "QUANTIDADE", "operator": "gt", "value": 2},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        # Apenas MESA (nota 1001, quantidade 3) satisfaz ambas as condicoes
        assert len(rows) == 1
        assert rows[0]["PRODUTO"] == "MESA"

    def test_logica_or(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Com logica OR, basta uma condicao ser satisfeita."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "logic": "or",
                "conditions": [
                    {"field": "NUMERO_NOTA", "operator": "eq", "value": 1001},
                    {"field": "NUMERO_NOTA", "operator": "eq", "value": 1003},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 3
        assert all(r["NUMERO_NOTA"] in (1001, 1003) for r in rows)

    def test_resultado_vazio(self, duckdb_with_sample: tuple[Path, dict]) -> None:
        """Deve retornar tabela vazia quando nenhuma linha satisfaz o filtro."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [
                    {"field": "NUMERO_NOTA", "operator": "eq", "value": 9999}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 0

    def test_le_tabela_de_schema_dlt(
        self, duckdb_with_dlt_schema: tuple[Path, dict]
    ) -> None:
        """Deve ler corretamente tabelas criadas pelo dlt no schema shift_extract."""
        db_path, reference = duckdb_with_dlt_schema
        context = make_context(
            db_path, reference["table_name"], schema="shift_extract"
        )

        processor = FilterNodeProcessor()
        result = processor.process(
            node_id="filter-1",
            config={
                "conditions": [
                    {"field": "NUMERO_NOTA", "operator": "eq", "value": 1002}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        assert output_ref["dataset_name"] is None  # saida sempre no schema main
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 1
        assert rows[0]["NUMERO_NOTA"] == 1002


# ---------------------------------------------------------------------------
# Testes de validacao e erros
# ---------------------------------------------------------------------------

class TestFilterNodeValidation:

    def test_erro_sem_condicoes(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando nenhuma condicao e informada."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        with pytest.raises(NodeProcessingError, match="ao menos uma condicao"):
            processor.process(
                node_id="filter-1",
                config={"conditions": []},
                context=context,
            )

    def test_erro_logic_invalido(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando logic nao e 'and' nem 'or'."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        with pytest.raises(NodeProcessingError, match="logic"):
            processor.process(
                node_id="filter-1",
                config={
                    "logic": "xor",
                    "conditions": [
                        {"field": "NUMERO_NOTA", "operator": "eq", "value": 1001}
                    ],
                },
                context=context,
            )

    def test_erro_operador_invalido(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando o operador nao e suportado."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        with pytest.raises(NodeProcessingError, match="nao suportado"):
            processor.process(
                node_id="filter-1",
                config={
                    "conditions": [
                        {"field": "NUMERO_NOTA", "operator": "between", "value": 1001}
                    ]
                },
                context=context,
            )

    def test_erro_condicao_sem_field(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando field esta ausente na condicao."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        with pytest.raises(NodeProcessingError, match="field"):
            processor.process(
                node_id="filter-1",
                config={
                    "conditions": [{"operator": "eq", "value": 1001}]
                },
                context=context,
            )

    def test_erro_in_sem_lista(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando 'in' recebe valor nao-lista."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = FilterNodeProcessor()
        with pytest.raises(NodeProcessingError, match="lista"):
            processor.process(
                node_id="filter-1",
                config={
                    "conditions": [
                        {"field": "NUMERO_NOTA", "operator": "in", "value": 1001}
                    ]
                },
                context=context,
            )


# ---------------------------------------------------------------------------
# Testes de ParameterValue — formatos left/right e vars
# ---------------------------------------------------------------------------

class TestFilterParameterValueConditions:
    """Garante que o novo formato {left, operator, right} e o legado coexistem."""

    def test_new_format_left_chip_right_fixed(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """left=chip {{PRODUTO}}, right=fixed 'CADEIRA' → 1 linha."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        result = FilterNodeProcessor().process(
            "f-pv-1",
            {
                "conditions": [
                    {
                        "left": {"mode": "dynamic", "template": "{{PRODUTO}}"},
                        "operator": "eq",
                        "right": {"mode": "fixed", "value": "CADEIRA"},
                    }
                ]
            },
            context,
        )

        rows = read_duckdb_table(
            result["data"]["database_path"], result["data"]["table_name"]
        )
        assert len(rows) == 1
        assert rows[0]["PRODUTO"] == "CADEIRA"

    def test_new_format_right_resolved_from_vars(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """right={{vars.alvo}} é resolvido antes de gerar o SQL."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])
        context["vars"] = {"alvo": "MESA"}

        result = FilterNodeProcessor().process(
            "f-pv-vars",
            {
                "conditions": [
                    {
                        "left": {"mode": "dynamic", "template": "{{PRODUTO}}"},
                        "operator": "eq",
                        "right": {"mode": "dynamic", "template": "{{vars.alvo}}"},
                    }
                ]
            },
            context,
        )

        rows = read_duckdb_table(
            result["data"]["database_path"], result["data"]["table_name"]
        )
        assert len(rows) == 1
        assert rows[0]["PRODUTO"] == "MESA"

    def test_new_format_numeric_comparison(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """left=chip {{QUANTIDADE}}, right=fixed '3', operador gte → >= 3."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        result = FilterNodeProcessor().process(
            "f-pv-num",
            {
                "conditions": [
                    {
                        "left": {"mode": "dynamic", "template": "{{QUANTIDADE}}"},
                        "operator": "gte",
                        "right": {"mode": "fixed", "value": "3"},
                    }
                ]
            },
            context,
        )

        rows = read_duckdb_table(
            result["data"]["database_path"], result["data"]["table_name"]
        )
        # MESA (3) e LAMPADA (5) têm QUANTIDADE >= 3
        assert len(rows) == 2
        assert all(r["QUANTIDADE"] >= 3 for r in rows)

    def test_legacy_and_new_conditions_mixed(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Mistura de formato legado e novo na mesma lista (logic OR)."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        result = FilterNodeProcessor().process(
            "f-mixed",
            {
                "logic": "or",
                "conditions": [
                    # legado
                    {"field": "PRODUTO", "operator": "eq", "value": "SOFA"},
                    # novo
                    {
                        "left": {"mode": "dynamic", "template": "{{PRODUTO}}"},
                        "operator": "eq",
                        "right": {"mode": "fixed", "value": "LAMPADA"},
                    },
                ],
            },
            context,
        )

        rows = read_duckdb_table(
            result["data"]["database_path"], result["data"]["table_name"]
        )
        assert len(rows) == 2
        assert {r["PRODUTO"] for r in rows} == {"SOFA", "LAMPADA"}

    def test_new_format_is_null_ignores_right(
        self, tmp_path: Path
    ) -> None:
        """is_null com formato novo não usa right — campo DESCONTO nulo."""
        rows = [
            {"ID": 1, "DESCONTO": None},
            {"ID": 2, "DESCONTO": 5.0},
        ]
        db_path = tmp_path / "null_pv.duckdb"
        reference = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = FilterNodeProcessor().process(
            "f-null-pv",
            {
                "conditions": [
                    {
                        "left": {"mode": "dynamic", "template": "{{DESCONTO}}"},
                        "operator": "is_null",
                        "right": {"mode": "fixed", "value": ""},
                    }
                ]
            },
            context,
        )

        result_rows = read_duckdb_table(
            result["data"]["database_path"], result["data"]["table_name"]
        )
        assert len(result_rows) == 1
        assert result_rows[0]["ID"] == 1
