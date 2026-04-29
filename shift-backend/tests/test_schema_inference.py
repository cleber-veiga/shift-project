"""
Testes para schema_inference (Fase 5).

predict_output_schema retorna list[FieldDescriptor] ou None.
"""

from __future__ import annotations

import pytest

from app.services.workflow.schema_inference import (
    FieldDescriptor,
    predict_output_schema,
)


def _fd(name: str, dtype: str = "VARCHAR", nullable: bool = True) -> FieldDescriptor:
    return FieldDescriptor(name=name, data_type=dtype, nullable=nullable)


def _schema(*fields: tuple[str, str]) -> list[FieldDescriptor]:
    return [_fd(name, dtype) for name, dtype in fields]


# ─── filter ──────────────────────────────────────────────────────────────────

class TestFilterSchema:

    def test_passthrough_input(self) -> None:
        inp = _schema(("id", "INTEGER"), ("name", "VARCHAR"), ("amount", "DOUBLE"))
        result = predict_output_schema("filter", {}, {"input": inp})
        assert result == inp

    def test_sem_input_schema_retorna_none(self) -> None:
        result = predict_output_schema("filter", {}, {})
        assert result is None

    def test_outro_handle_como_input(self) -> None:
        inp = _schema(("x", "INTEGER"))
        result = predict_output_schema("filter", {}, {"main": inp})
        assert result == inp


# ─── mapper ──────────────────────────────────────────────────────────────────

class TestMapperSchema:

    def test_renomeia_coluna(self) -> None:
        inp = _schema(("order_id", "INTEGER"), ("total", "DOUBLE"))
        mappings = [
            {"source": "order_id", "target": "id"},
            {"source": "total", "target": "valor"},
        ]
        result = predict_output_schema("mapper", {"mappings": mappings}, {"input": inp})
        assert result is not None
        names = [f.name for f in result]
        assert names == ["id", "valor"]

    def test_preserva_tipo_do_input(self) -> None:
        inp = [_fd("amount", "DOUBLE")]
        mappings = [{"source": "amount", "target": "valor"}]
        result = predict_output_schema("mapper", {"mappings": mappings}, {"input": inp})
        assert result is not None
        assert result[0].data_type == "DOUBLE"

    def test_tipo_declarado_no_mapping(self) -> None:
        mappings = [{"source": "x", "target": "y", "type": "integer"}]
        result = predict_output_schema("mapper", {"mappings": mappings}, {})
        assert result is not None
        assert result[0].data_type == "INTEGER"

    def test_sem_mappings_retorna_none(self) -> None:
        result = predict_output_schema("mapper", {}, {})
        assert result is None

    def test_placeholder_nao_resolvido_retorna_none(self) -> None:
        mappings = [{"source": "a", "target": "${TARGET_COL}"}]
        result = predict_output_schema("mapper", {"mappings": mappings}, {})
        assert result is None

    def test_campo_computado_sem_source(self) -> None:
        mappings = [{"target": "computed", "expression": "amount * 2"}]
        result = predict_output_schema("mapper", {"mappings": mappings}, {})
        assert result is not None
        assert result[0].name == "computed"
        assert result[0].data_type == "VARCHAR"  # fallback sem tipo declarado


# ─── join ─────────────────────────────────────────────────────────────────────

class TestJoinSchema:

    def test_merge_left_right(self) -> None:
        left = _schema(("id", "INTEGER"), ("name", "VARCHAR"))
        right = _schema(("id", "INTEGER"), ("score", "DOUBLE"))
        result = predict_output_schema(
            "join",
            {"conditions": [{"left_column": "id", "right_column": "id"}]},
            {"left": left, "right": right},
        )
        assert result is not None
        names = {f.name for f in result}
        assert "id" in names
        assert "name" in names
        assert "score" in names
        # right key (id) deve ser omitido → não duplica
        assert len([f for f in result if f.name == "id"]) == 1

    def test_conflito_de_nomes_usa_prefixo(self) -> None:
        left = _schema(("id", "INTEGER"), ("status", "VARCHAR"))
        right = _schema(("order_id", "INTEGER"), ("status", "INTEGER"))
        result = predict_output_schema(
            "join",
            {"conditions": [{"left_column": "id", "right_column": "order_id"}]},
            {"left": left, "right": right},
        )
        assert result is not None
        names = [f.name for f in result]
        # "status" do left está presente, do right vira "right_status"
        assert "status" in names
        assert "right_status" in names

    def test_sem_left_retorna_none(self) -> None:
        right = _schema(("id", "INTEGER"))
        result = predict_output_schema("join", {}, {"right": right})
        assert result is None

    def test_apenas_left_sem_right(self) -> None:
        left = _schema(("id", "INTEGER"), ("name", "VARCHAR"))
        result = predict_output_schema("join", {}, {"left": left})
        assert result is not None
        assert len(result) == 2


# ─── select ──────────────────────────────────────────────────────────────────

class TestSelectSchema:

    def test_subset_de_colunas(self) -> None:
        inp = _schema(("id", "INTEGER"), ("name", "VARCHAR"), ("age", "INTEGER"))
        result = predict_output_schema(
            "select",
            {"columns": ["id", "name"]},
            {"input": inp},
        )
        assert result is not None
        assert [f.name for f in result] == ["id", "name"]

    def test_preserva_tipo_do_input(self) -> None:
        inp = [_fd("amount", "DOUBLE")]
        result = predict_output_schema("select", {"columns": ["amount"]}, {"input": inp})
        assert result is not None
        assert result[0].data_type == "DOUBLE"

    def test_coluna_nao_encontrada_fallback_varchar(self) -> None:
        inp = _schema(("id", "INTEGER"))
        result = predict_output_schema("select", {"columns": ["id", "inexistente"]}, {"input": inp})
        assert result is not None
        tipos = {f.name: f.data_type for f in result}
        assert tipos["inexistente"] == "VARCHAR"

    def test_sem_columns_retorna_none(self) -> None:
        result = predict_output_schema("select", {}, {})
        assert result is None


# ─── sql_database → probe via LIMIT 0 ────────────────────────────────────────

class TestSqlDatabaseSchema:

    def test_sem_connection_strings_retorna_none(self) -> None:
        """Sem connection_strings, sql_database vira None graciosamente."""
        result = predict_output_schema("sql_database", {"query": "SELECT 1"}, {})
        assert result is None

    def test_connection_id_ausente_no_mapa_retorna_none(self) -> None:
        result = predict_output_schema(
            "sql_database",
            {"connection_id": "abc", "query": "SELECT 1"},
            {},
            connection_strings={"outro": "sqlite:///:memory:"},
        )
        assert result is None

    def test_query_com_placeholder_retorna_none(self) -> None:
        result = predict_output_schema(
            "sql_database",
            {"connection_id": "abc", "query": "SELECT * FROM ${TABLE}"},
            {},
            connection_strings={"abc": "sqlite:///:memory:"},
        )
        assert result is None

    def test_probe_sqlite_inmemory(self) -> None:
        """Sqlite in-memory: probe real via SELECT...LIMIT 0."""
        # Seta connection com tabela conhecida.
        from sqlalchemy import create_engine, text  # noqa: PLC0415
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER, name TEXT)"))
            conn.execute(text("INSERT INTO t VALUES (1, 'a')"))
            conn.commit()

        # O probe abre nova engine na mesma URL — mas sqlite :memory: é
        # per-engine, então usamos um arquivo temporário compartilhado.
        engine.dispose()

        import tempfile, os  # noqa: PLC0415
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            url = f"sqlite:///{path}"
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text("CREATE TABLE t (id INTEGER, name TEXT)"))
                conn.commit()
            engine.dispose()

            result = predict_output_schema(
                "sql_database",
                {"connection_id": "c1", "query": "SELECT id, name FROM t"},
                {},
                connection_strings={"c1": url},
            )
            assert result is not None
            assert [f.name for f in result] == ["id", "name"]
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_cache_evita_segunda_query(self) -> None:
        """Segunda chamada com mesma (connection_id, query) usa cache."""
        from app.services.workflow.schema_inference import _SQL_SCHEMA_CACHE  # noqa: PLC0415
        _SQL_SCHEMA_CACHE.clear()

        import tempfile, os  # noqa: PLC0415
        from sqlalchemy import create_engine, text  # noqa: PLC0415
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            url = f"sqlite:///{path}"
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text("CREATE TABLE u (x INTEGER)"))
                conn.commit()
            engine.dispose()

            r1 = predict_output_schema(
                "sql_database",
                {"connection_id": "c1", "query": "SELECT x FROM u"},
                {},
                connection_strings={"c1": url},
            )
            assert r1 is not None
            assert ("c1",) == tuple(k[0] for k in _SQL_SCHEMA_CACHE.keys())

            # Apaga o arquivo — segunda chamada com cache hit deve funcionar
            # sem reabrir conexão (caso contrário falharia).
            os.unlink(path)
            path = None  # type: ignore[assignment]

            r2 = predict_output_schema(
                "sql_database",
                {"connection_id": "c1", "query": "SELECT x FROM u"},
                {},
                connection_strings={"c1": url},
            )
            assert r2 == r1, "Segunda chamada deveria vir do cache"
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    def test_connection_error_retorna_none(self) -> None:
        """Connection inválida → None, sem levantar exceção."""
        from app.services.workflow.schema_inference import _SQL_SCHEMA_CACHE  # noqa: PLC0415
        _SQL_SCHEMA_CACHE.clear()

        result = predict_output_schema(
            "sql_database",
            {"connection_id": "bad", "query": "SELECT 1"},
            {},
            connection_strings={"bad": "postgresql://invalid:0/nada"},
        )
        assert result is None

    def test_engine_disposed_on_query_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pool do engine é descartado mesmo quando a query do probe falha.

        Sem dispose() explícito, sqlalchemy mantém o pool de conexões vivo
        e vaza handles em produção. with engine.connect() fecha apenas a
        conexão individual — não o pool subjacente.
        """
        from app.services.workflow import schema_inference as sm  # noqa: PLC0415

        class _FailingConnection:
            def execute(self, *_a, **_kw):
                raise RuntimeError("query exploded")

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        dispose_calls = {"n": 0}

        class _FakeEngine:
            def connect(self):
                return _FailingConnection()

            def dispose(self):
                dispose_calls["n"] += 1

        def _fake_create_engine(_url):
            return _FakeEngine()

        # Patch sqlalchemy.create_engine no namespace que _probe_sql_schema
        # importa lazy (importação dentro da função, então monkeypatch precisa
        # alvejar o módulo original).
        import sqlalchemy  # noqa: PLC0415
        monkeypatch.setattr(sqlalchemy, "create_engine", _fake_create_engine)

        result = sm._probe_sql_schema("sqlite:///:memory:", "SELECT 1")
        assert result is None
        assert dispose_calls["n"] == 1, "engine.dispose() deve ser chamado mesmo em falha"


# ─── tipos desconhecidos ──────────────────────────────────────────────────────

class TestUnknownNodeTypes:

    @pytest.mark.parametrize("node_type", [
        "aggregator", "pivot", "code", "sort", "text_to_rows", "tipo_xyz",
    ])
    def test_tipo_desconhecido_retorna_none(self, node_type: str) -> None:
        result = predict_output_schema(node_type, {}, {})
        assert result is None


# ─── lookup usa mesma lógica que join ────────────────────────────────────────

class TestLookupSchema:

    def test_lookup_merge_left_right(self) -> None:
        left = _schema(("id", "INTEGER"))
        right = _schema(("lookup_id", "INTEGER"), ("description", "VARCHAR"))
        result = predict_output_schema(
            "lookup",
            {"conditions": [{"left_column": "id", "right_column": "lookup_id"}]},
            {"left": left, "right": right},
        )
        assert result is not None
        names = {f.name for f in result}
        assert "id" in names
        assert "description" in names


# ─── FieldDescriptor ─────────────────────────────────────────────────────────

class TestFieldDescriptor:

    def test_criacao_basica(self) -> None:
        fd = FieldDescriptor(name="amount", data_type="DOUBLE")
        assert fd.name == "amount"
        assert fd.data_type == "DOUBLE"
        assert fd.nullable is True

    def test_nullable_false(self) -> None:
        fd = FieldDescriptor(name="id", data_type="INTEGER", nullable=False)
        assert fd.nullable is False

    def test_model_dump(self) -> None:
        fd = FieldDescriptor(name="id", data_type="INTEGER")
        d = fd.model_dump()
        assert d == {"name": "id", "data_type": "INTEGER", "nullable": True}
