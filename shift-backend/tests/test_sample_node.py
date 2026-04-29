"""
Testes para SampleNodeProcessor.

Cobre:
  - Modo first_n: retorna exatamente N primeiras linhas
  - Modo random: retorna N linhas com seed determinístico
  - Modo percent: retorna ~P% das linhas
  - Erros de validacao (mode invalido, n ausente, percent invalido)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow.nodes.sample_node import SampleNodeProcessor
from app.services.workflow.nodes.exceptions import NodeProcessingError
from tests.conftest import make_context, read_duckdb_table, create_duckdb_with_rows


@pytest.fixture
def db_with_100_rows(tmp_path: Path):
    rows = [{"ID": i, "VALOR": i * 10} for i in range(100)]
    db_path = tmp_path / "sample.duckdb"
    ref = create_duckdb_with_rows(db_path, "src", rows)
    return db_path, ref


class TestSampleNodeFirstN:

    def test_first_n_retorna_exatamente_n(self, db_with_100_rows) -> None:
        db_path, ref = db_with_100_rows
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "first_n", "n": 10},
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(rows) == 10

    def test_first_n_zero(self, db_with_100_rows) -> None:
        """n=0 deve retornar tabela vazia."""
        db_path, ref = db_with_100_rows
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "first_n", "n": 0},
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(rows) == 0

    def test_first_n_maior_que_total(self, db_with_100_rows) -> None:
        """n maior que o dataset deve retornar todas as linhas."""
        db_path, ref = db_with_100_rows
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "first_n", "n": 200},
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(rows) == 100


class TestSampleNodeRandom:

    def test_random_retorna_n_linhas(self, db_with_100_rows) -> None:
        db_path, ref = db_with_100_rows
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "random", "n": 15, "seed": 42},
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(rows) == 15

    def test_random_determinístico_com_mesmo_seed(self, db_with_100_rows) -> None:
        """Dois processos com mesmo seed devem retornar as mesmas linhas."""
        db_path, ref = db_with_100_rows
        context = make_context(db_path, "src")

        r1 = SampleNodeProcessor().process(
            "sample-a", {"mode": "random", "n": 20, "seed": 7}, context
        )
        r2 = SampleNodeProcessor().process(
            "sample-b", {"mode": "random", "n": 20, "seed": 7}, context
        )

        rows1 = read_duckdb_table(r1["data"]["database_path"], r1["data"]["table_name"])
        rows2 = read_duckdb_table(r2["data"]["database_path"], r2["data"]["table_name"])
        ids1 = sorted(r["ID"] for r in rows1)
        ids2 = sorted(r["ID"] for r in rows2)
        assert ids1 == ids2


class TestSampleNodePercent:

    def test_percent_retorna_proporcao(self, db_with_100_rows) -> None:
        """50% de 100 linhas deve retornar ~50 linhas (BERNOULLI row-level)."""
        db_path, ref = db_with_100_rows
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "percent", "percent": 50.0},
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        # Amostragem probabilistica: tolerancia ±30 linhas
        assert 20 <= len(rows) <= 80

    def test_percent_100_retorna_tudo(self, db_with_100_rows) -> None:
        db_path, ref = db_with_100_rows
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "percent", "percent": 100.0},
            context,
        )

        rows = read_duckdb_table(result["data"]["database_path"], result["data"]["table_name"])
        assert len(rows) == 100


class TestSampleNodeValidation:

    def test_erro_mode_invalido(self, tmp_path: Path) -> None:
        rows = [{"ID": 1}]
        db_path = tmp_path / "v.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="mode"):
            SampleNodeProcessor().process("s-1", {"mode": "top_k"}, context)

    def test_erro_first_n_sem_n(self, tmp_path: Path) -> None:
        rows = [{"ID": 1}]
        db_path = tmp_path / "v2.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="'n'"):
            SampleNodeProcessor().process("s-1", {"mode": "first_n"}, context)

    def test_erro_random_sem_n(self, tmp_path: Path) -> None:
        rows = [{"ID": 1}]
        db_path = tmp_path / "v3.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="'n'"):
            SampleNodeProcessor().process("s-1", {"mode": "random"}, context)

    def test_erro_percent_zero(self, tmp_path: Path) -> None:
        rows = [{"ID": 1}]
        db_path = tmp_path / "v4.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="percent"):
            SampleNodeProcessor().process("s-1", {"mode": "percent", "percent": 0}, context)

    def test_erro_percent_acima_100(self, tmp_path: Path) -> None:
        rows = [{"ID": 1}]
        db_path = tmp_path / "v5.duckdb"
        ref = create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        with pytest.raises(NodeProcessingError, match="percent"):
            SampleNodeProcessor().process("s-1", {"mode": "percent", "percent": 150}, context)


class TestSampleOutputSummary:

    def test_first_n_summary(self, tmp_path: Path) -> None:
        rows = [{"ID": i} for i in range(20)]
        db_path = tmp_path / "sample_first_n_summary.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "first_n", "n": 5},
            context,
        )

        summary = result["output_summary"]
        assert summary["row_count_in"] == 20
        assert summary["row_count_out"] == 5
        assert summary["warnings"] == []

    def test_random_sem_seed_emite_warning(self, tmp_path: Path) -> None:
        rows = [{"ID": i} for i in range(20)]
        db_path = tmp_path / "sample_random_no_seed.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "random", "n": 5},
            context,
        )

        assert "non_reproducible_sample" in result["output_summary"]["warnings"]

    def test_random_com_seed_sem_warning(self, tmp_path: Path) -> None:
        rows = [{"ID": i} for i in range(20)]
        db_path = tmp_path / "sample_random_seed.duckdb"
        create_duckdb_with_rows(db_path, "src", rows)
        context = make_context(db_path, "src")

        result = SampleNodeProcessor().process(
            "sample-1",
            {"mode": "random", "n": 5, "seed": 7},
            context,
        )

        assert result["output_summary"]["warnings"] == []
