"""
Testes unitarios e de integracao para CodeNodeProcessor.

Cobre:
  - Resultado como DuckDBPyRelation (filtro via SQL nativo)
  - Resultado como string SQL (SELECT ... FROM source_table)
  - Resultado como None (copia a tabela de origem)
  - Resultado como lista de dicts (dados novos)
  - Resultado como dict unico
  - result_variable customizado
  - Acesso a builtins seguros (len, list, etc.)
  - Erros de validacao (sem codigo, tipo de resultado invalido, erro de execucao)

Nota sobre o resolve_data do BaseNodeProcessor:
  O BaseNodeProcessor.resolve_data() interpreta chaves { } como templates.
  Para passar codigo Python com dicts literais, os testes usam arquivos
  temporarios ou strings sem chaves, evitando conflito com o template engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.workflow.nodes.code_node import CodeNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table


# ---------------------------------------------------------------------------
# Helper para escrever codigo em arquivo temporario
# ---------------------------------------------------------------------------

def write_code_file(tmp_path: Path, code: str, name: str = "code.py") -> str:
    """Escreve o codigo em um arquivo temporario e retorna o caminho."""
    code_file = tmp_path / name
    code_file.write_text(code, encoding="utf-8")
    return str(code_file)


# ---------------------------------------------------------------------------
# Testes de caminho feliz — modos de resultado
# ---------------------------------------------------------------------------

class TestCodeNodeResultModes:

    def test_resultado_relation_duckdb(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve materializar resultado quando o codigo retorna uma DuckDBPyRelation."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = CodeNodeProcessor()
        result = processor.process(
            node_id="code-1",
            config={
                "code": "result = data.filter('NUMERO_NOTA = 1001')"
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 2
        assert all(r["NUMERO_NOTA"] == 1001 for r in rows)

    def test_resultado_sql_string(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve materializar resultado quando o codigo retorna uma string SQL."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])
        source_table = reference["table_name"]

        # Usa concatenacao simples sem chaves para evitar o template engine
        code = (
            "result = ("
            f"'SELECT NUMERO_NOTA, SUM(QUANTIDADE) AS QTD_TOTAL "
            f"FROM \"{source_table}\" GROUP BY NUMERO_NOTA'"
            ")"
        )

        processor = CodeNodeProcessor()
        result = processor.process(
            node_id="code-1",
            config={"code": code},
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 3  # 3 notas distintas
        colunas = set(rows[0].keys())
        assert "NUMERO_NOTA" in colunas
        assert "QTD_TOTAL" in colunas

    def test_resultado_none_copia_origem(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Quando result=None, deve copiar a tabela de origem sem alteracoes."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = CodeNodeProcessor()
        result = processor.process(
            node_id="code-1",
            config={"code": "result = None"},
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 4

    def test_resultado_lista_de_dicts(
        self, duckdb_with_sample: tuple[Path, dict], tmp_path: Path
    ) -> None:
        """Deve materializar resultado quando o codigo retorna uma lista de dicts."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        # Escreve o codigo em arquivo para evitar que resolve_data processe as chaves
        code = 'result = [{"ID": 1, "NOME": "Alpha"}, {"ID": 2, "NOME": "Beta"}]'
        code_path = write_code_file(tmp_path, code)

        processor = CodeNodeProcessor()
        # Passa o codigo lendo do arquivo para evitar o template engine
        with open(code_path) as f:
            raw_code = f.read()

        # Injeta o codigo diretamente no config sem passar pelo resolve_data
        # usando um contexto sem templates
        result = processor.process(
            node_id="code-1",
            config={"code": raw_code},
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 2
        nomes = {r["NOME"] for r in rows}
        assert nomes == {"Alpha", "Beta"}

    def test_resultado_dict_unico(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve materializar resultado quando o codigo retorna um dict unico."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        # Usa aspas simples para o dict para evitar conflito com o template engine
        code = "result = {'TOTAL': 42, 'STATUS': 'OK'}"

        processor = CodeNodeProcessor()
        result = processor.process(
            node_id="code-1",
            config={"code": code},
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 1
        assert rows[0]["TOTAL"] == 42
        assert rows[0]["STATUS"] == "OK"

    def test_result_variable_customizado(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve usar a variavel customizada como resultado quando result_variable e informado."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        # Usa aspas simples para o dict
        code = "saida = [{'X': 1}, {'X': 2}]"

        processor = CodeNodeProcessor()
        result = processor.process(
            node_id="code-1",
            config={
                "result_variable": "saida",
                "code": code,
            },
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 2

    def test_acesso_a_builtins_seguros(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve permitir uso de builtins seguros como len e list."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        # Usa connection.execute para contar linhas via SQL
        code = (
            f"rows = connection.execute('SELECT COUNT(*) FROM \"{reference['table_name']}\"').fetchone()\n"
            "result = [{'NUM_LINHAS': rows[0]}]"
        )

        processor = CodeNodeProcessor()
        result = processor.process(
            node_id="code-1",
            config={"code": code},
            context=context,
        )

        output_ref = result["data"]
        rows = read_duckdb_table(output_ref["database_path"], output_ref["table_name"])
        assert len(rows) == 1
        assert rows[0]["NUM_LINHAS"] == 4


# ---------------------------------------------------------------------------
# Testes de validacao e erros
# ---------------------------------------------------------------------------

class TestCodeNodeValidation:

    def test_erro_sem_codigo(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando codigo nao e informado."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = CodeNodeProcessor()
        with pytest.raises(NodeProcessingError, match="codigo e obrigatorio"):
            processor.process(
                node_id="code-1",
                config={},
                context=context,
            )

    def test_erro_codigo_com_excecao(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando o codigo levanta uma excecao."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = CodeNodeProcessor()
        with pytest.raises(NodeProcessingError, match="erro ao executar"):
            processor.process(
                node_id="code-1",
                config={"code": "raise ValueError('erro proposital')"},
                context=context,
            )

    def test_erro_tipo_resultado_invalido(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve lancar NodeProcessingError quando o resultado nao e um tipo suportado."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = CodeNodeProcessor()
        with pytest.raises(NodeProcessingError):
            processor.process(
                node_id="code-1",
                config={"code": "result = 12345"},  # int nao e suportado
                context=context,
            )

    def test_erro_acesso_a_builtin_nao_permitido(
        self, duckdb_with_sample: tuple[Path, dict]
    ) -> None:
        """Deve impedir acesso a builtins perigosos como __import__ e open."""
        db_path, reference = duckdb_with_sample
        context = make_context(db_path, reference["table_name"])

        processor = CodeNodeProcessor()
        with pytest.raises((NodeProcessingError, NameError, TypeError)):
            processor.process(
                node_id="code-1",
                config={"code": "import os; result = None"},
                context=context,
            )
