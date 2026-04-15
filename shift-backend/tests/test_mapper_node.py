"""
Testes unitarios e de integracao para MapperNodeProcessor.

Cobre:
  - Renomeacao simples de coluna (source -> target)
  - Selecao de subconjunto de colunas com drop_unmapped=True
  - Manutencao de colunas nao mapeadas com drop_unmapped=False (padrao)
  - Campo computado via expressao SQL (sem source)
  - Combinacao de renomeacao e campo computado
  - Leitura de tabelas no schema dlt (shift_extract)
  - Erros de validacao (sem mappings, sem target, sem source nem expression)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.workflow.nodes.mapper_node import MapperNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table


# ---------------------------------------------------------------------------
# Testes de caminho feliz
# ---------------------------------------------------------------------------

class TestMapperNodeHappyPath:

    def test_renomeia_coluna_simples(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve renomear NUMERO_NOTA para NUM_NF mantendo as demais colunas."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        result = processor.process(
            node_id="mapper-1",
            config={
                "mappings": [
                    {"source": "NUMERO_NOTA", "target": "NUM_NF"}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        colunas = set(rows[0].keys())

        assert "NUM_NF" in colunas
        assert "NUMERO_NOTA" not in colunas
        # Demais colunas devem estar presentes (drop_unmapped=False por padrao)
        assert "QUANTIDADE" in colunas
        assert "PRODUTO" in colunas

    def test_drop_unmapped_seleciona_apenas_mapeadas(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Com drop_unmapped=True, apenas as colunas mapeadas devem aparecer."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        result = processor.process(
            node_id="mapper-1",
            config={
                "drop_unmapped": True,
                "mappings": [
                    {"source": "NUMERO_NOTA", "target": "NUM_NF"},
                    {"source": "PRODUTO", "target": "DESC_PRODUTO"},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        colunas = set(rows[0].keys())

        assert colunas == {"NUM_NF", "DESC_PRODUTO"}
        assert len(rows) == 4

    def test_mantém_colunas_nao_mapeadas_por_padrao(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Com drop_unmapped=False (padrao), colunas nao mapeadas devem permanecer."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        result = processor.process(
            node_id="mapper-1",
            config={
                "mappings": [
                    {"source": "NUMERO_NOTA", "target": "NUM_NF"}
                ]
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        colunas = set(rows[0].keys())

        # Coluna renomeada presente, original ausente
        assert "NUM_NF" in colunas
        assert "NUMERO_NOTA" not in colunas
        # Colunas nao mapeadas presentes
        assert "QUANTIDADE" in colunas
        assert "VALOR_UNITARIO" in colunas
        assert "DESCONTO" in colunas
        assert "PRODUTO" in colunas

    def test_campo_computado_via_expressao(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve criar coluna VALOR_TOTAL via expressao sem source."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        result = processor.process(
            node_id="mapper-1",
            config={
                "drop_unmapped": True,
                "mappings": [
                    {"source": "NUMERO_NOTA", "target": "NUM_NF"},
                    {
                        "target": "VALOR_TOTAL",
                        "expression": "QUANTIDADE * VALOR_UNITARIO - DESCONTO",
                    },
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        colunas = set(rows[0].keys())

        assert colunas == {"NUM_NF", "VALOR_TOTAL"}
        # CADEIRA: 2 * 100.0 - 0.0 = 200.0
        row_cadeira = next(r for r in rows if r["NUM_NF"] == 1001 and r["VALOR_TOTAL"] == pytest.approx(200.0))
        assert row_cadeira is not None

    def test_renomeia_para_mesmo_nome(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Mapping com source == target deve manter a coluna sem alteracao."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        result = processor.process(
            node_id="mapper-1",
            config={
                "drop_unmapped": True,
                "mappings": [
                    {"source": "PRODUTO", "target": "PRODUTO"},
                    {"source": "QUANTIDADE", "target": "QUANTIDADE"},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert set(rows[0].keys()) == {"PRODUTO", "QUANTIDADE"}
        assert len(rows) == 4

    def test_le_tabela_de_schema_dlt(
        self, duckdb_with_dlt_schema: tuple[Path, dict]
    ) -> None:
        """Deve ler corretamente tabelas criadas pelo dlt no schema shift_extract."""
        db_path, reference = duckdb_with_dlt_schema
        context = make_context(
            db_path, reference["table_name"], schema="shift_extract"
        )

        processor = MapperNodeProcessor()
        result = processor.process(
            node_id="mapper-1",
            config={
                "drop_unmapped": True,
                "mappings": [
                    {"source": "NUMERO_NOTA", "target": "NUM_NF"},
                    {"source": "PRODUTO", "target": "PRODUTO"},
                ],
            },
            context=context,
        )

        output_ref = result["data"]
        assert output_ref["dataset_name"] is None
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 4
        assert set(rows[0].keys()) == {"NUM_NF", "PRODUTO"}


# ---------------------------------------------------------------------------
# Testes de validacao e erros
# ---------------------------------------------------------------------------

class TestMapperNodeValidation:

    def test_erro_sem_mappings(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando nenhum mapping e informado."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        with pytest.raises(NodeProcessingError, match="ao menos um mapping"):
            processor.process(
                node_id="mapper-1",
                config={"mappings": []},
                context=context,
            )

    def test_erro_mapping_sem_target(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando target esta ausente."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        with pytest.raises(NodeProcessingError, match="target"):
            processor.process(
                node_id="mapper-1",
                config={
                    "mappings": [{"source": "NUMERO_NOTA"}]
                },
                context=context,
            )

    def test_erro_mapping_sem_source_nem_expression(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando nem source nem expression sao informados."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = MapperNodeProcessor()
        with pytest.raises(NodeProcessingError, match="source.*expression|expression.*source"):
            processor.process(
                node_id="mapper-1",
                config={
                    "mappings": [{"target": "NOVA_COLUNA"}]
                },
                context=context,
            )
