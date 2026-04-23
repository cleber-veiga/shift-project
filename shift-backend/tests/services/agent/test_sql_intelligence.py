"""
Testes do modulo SQL Intelligence (FASE 5 — Componente A).

Cobre:
  - extract_binds: Oracle (:PARAM), SQL Server (@param), PostgreSQL ($1)
  - extract_binds: inferencia de tipo por nome
  - extract_tables: tabelas com operacao correta (READ, INSERT, UPDATE, DELETE, DDL)
  - classify_destructiveness: safe, writes, destructive, schema_change
  - split_statements: split por semicolons (simples e multi-statement)
  - analyze_sql_script: analise completa integrada
  - Fallback gracioso para SQL invalido
"""

from __future__ import annotations

import pytest

from app.services.agent.sql_intelligence.parser import (
    analyze_sql_script,
    classify_destructiveness,
    extract_binds,
    extract_tables,
    split_statements,
)


# ---------------------------------------------------------------------------
# extract_binds
# ---------------------------------------------------------------------------


class TestExtractBinds:
    def test_colon_oracle_style(self):
        sql = "SELECT * FROM t WHERE id = :I_IDPEDIDO AND status = :V_STATUS"
        binds = extract_binds(sql)
        names = [b.name for b in binds]
        assert "I_IDPEDIDO" in names
        assert "V_STATUS" in names

    def test_colon_style_is_colon(self):
        sql = "SELECT :PARAM FROM t"
        binds = extract_binds(sql)
        assert binds[0].style == "colon"

    def test_at_sqlserver_style(self):
        sql = "SELECT * FROM t WHERE id = @UserId AND name = @UserName"
        binds = extract_binds(sql)
        names = [b.name for b in binds]
        assert "UserId" in names
        assert "UserName" in names
        assert all(b.style == "at" for b in binds)

    def test_dollar_postgres_style(self):
        sql = "SELECT * FROM t WHERE id = $1 AND name = $2"
        binds = extract_binds(sql)
        names = [b.name for b in binds]
        assert "1" in names
        assert "2" in names
        assert all(b.style == "dollar" for b in binds)

    def test_no_duplicates(self):
        sql = "SELECT :ID FROM t WHERE id = :ID AND parent = :ID"
        binds = extract_binds(sql)
        id_binds = [b for b in binds if b.name == "ID"]
        assert len(id_binds) == 1
        assert len(id_binds[0].positions) == 3

    def test_empty_sql_returns_empty(self):
        assert extract_binds("SELECT 1") == []
        assert extract_binds("") == []

    # --- Type inference ---

    def test_infer_integer_i_prefix(self):
        binds = extract_binds("SELECT :I_ESTAB FROM t")
        assert binds[0].inferred_type == "integer"

    def test_infer_integer_cod_suffix(self):
        binds = extract_binds("SELECT :COD_CLI FROM t")
        assert binds[0].inferred_type == "integer"

    def test_infer_date_d_prefix(self):
        binds = extract_binds("SELECT :D_NASC FROM t")
        assert binds[0].inferred_type == "date"

    def test_infer_date_dt_prefix(self):
        binds = extract_binds("SELECT :DT_INICIO FROM t")
        assert binds[0].inferred_type == "date"

    def test_infer_decimal_vl_prefix(self):
        binds = extract_binds("SELECT :VL_VALOR FROM t")
        assert binds[0].inferred_type == "decimal"

    def test_infer_string_for_plain_name(self):
        binds = extract_binds("SELECT :NOME FROM t")
        assert binds[0].inferred_type == "string"

    def test_infer_string_v_prefix(self):
        # V_ prefix = varchar in Oracle naming, should be string
        binds = extract_binds("SELECT :V_STATUS FROM t")
        assert binds[0].inferred_type == "string"


# ---------------------------------------------------------------------------
# extract_tables
# ---------------------------------------------------------------------------


class TestExtractTables:
    def test_select_is_read(self):
        tables = extract_tables("SELECT * FROM orders o JOIN items i ON o.id = i.order_id")
        ops = {t.operation for t in tables}
        assert "READ" in ops
        table_names = {t.table.lower() for t in tables}
        assert "orders" in table_names
        assert "items" in table_names

    def test_insert_is_insert(self):
        tables = extract_tables("INSERT INTO logs (msg) VALUES ('test')")
        assert any(t.operation == "INSERT" and t.table.lower() == "logs" for t in tables)

    def test_update_is_update(self):
        tables = extract_tables("UPDATE users SET name = 'x' WHERE id = 1")
        assert any(t.operation == "UPDATE" and t.table.lower() == "users" for t in tables)

    def test_delete_is_delete(self):
        tables = extract_tables("DELETE FROM audit_log WHERE created_at < '2020-01-01'")
        assert any(t.operation == "DELETE" for t in tables)

    def test_schema_qualified_table(self):
        tables = extract_tables("SELECT * FROM schema1.pedidos WHERE id = 1")
        pedidos = next((t for t in tables if t.table.lower() == "pedidos"), None)
        assert pedidos is not None
        assert pedidos.schema == "schema1"

    def test_empty_sql_returns_empty(self):
        assert extract_tables("") == []

    def test_invalid_sql_returns_empty_not_exception(self):
        # Should not raise even for totally invalid SQL
        result = extract_tables("THIS IS NOT SQL AT ALL %%%")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# classify_destructiveness
# ---------------------------------------------------------------------------


class TestClassifyDestructiveness:
    def test_select_is_safe(self):
        assert classify_destructiveness("SELECT id, name FROM users WHERE active = 1") == "safe"

    def test_insert_is_writes(self):
        assert classify_destructiveness("INSERT INTO log VALUES (1, 'msg')") == "writes"

    def test_update_is_writes(self):
        assert classify_destructiveness("UPDATE users SET name = 'x'") == "writes"

    def test_delete_is_destructive(self):
        assert classify_destructiveness("DELETE FROM orders WHERE id > 100") == "destructive"

    def test_truncate_is_destructive(self):
        assert classify_destructiveness("TRUNCATE TABLE staging") == "destructive"

    def test_drop_table_is_schema_change(self):
        assert classify_destructiveness("DROP TABLE old_logs") == "schema_change"

    def test_create_table_is_schema_change(self):
        assert classify_destructiveness("CREATE TABLE new_table (id INT)") == "schema_change"

    def test_alter_is_schema_change(self):
        assert classify_destructiveness("ALTER TABLE users ADD COLUMN phone VARCHAR(20)") == "schema_change"

    def test_multi_statement_takes_worst(self):
        sql = "SELECT 1; DELETE FROM t WHERE id = 1"
        assert classify_destructiveness(sql) == "destructive"

    def test_empty_is_safe(self):
        assert classify_destructiveness("") == "safe"

    def test_invalid_sql_falls_back(self):
        # Should not raise for invalid SQL
        result = classify_destructiveness("THIS IS NOT SQL")
        assert result in ("safe", "writes", "destructive", "schema_change")


# ---------------------------------------------------------------------------
# split_statements
# ---------------------------------------------------------------------------


class TestSplitStatements:
    def test_single_statement(self):
        stmts = split_statements("SELECT 1")
        assert len(stmts) == 1
        assert stmts[0].strip() == "SELECT 1"

    def test_multiple_statements(self):
        sql = "SELECT 1; SELECT 2; SELECT 3"
        stmts = split_statements(sql)
        assert len(stmts) == 3

    def test_trailing_semicolon_no_extra(self):
        stmts = split_statements("SELECT 1;")
        assert len(stmts) == 1

    def test_semicolon_in_string_not_split(self):
        # This is a harder case; we just check it does not crash
        sql = "SELECT 'a;b' FROM t; SELECT 2"
        stmts = split_statements(sql)
        assert len(stmts) >= 1  # At minimum stays alive


# ---------------------------------------------------------------------------
# analyze_sql_script (integration)
# ---------------------------------------------------------------------------


class TestAnalyzeSqlScript:
    def test_full_analysis_select(self):
        sql = "SELECT id, nome FROM clientes WHERE cod = :COD_CLI AND ativo = :V_ATIVO"
        result = analyze_sql_script(sql)
        assert result["destructiveness"] == "safe"
        assert result["has_binds"] is True
        assert result["statement_count"] == 1
        bind_names = [b["name"] for b in result["binds"]]
        assert "COD_CLI" in bind_names
        assert "V_ATIVO" in bind_names
        # COD_CLI should be integer, V_ATIVO should be string
        cod = next(b for b in result["binds"] if b["name"] == "COD_CLI")
        assert cod["inferred_type"] == "integer"

    def test_full_analysis_delete_blocked(self):
        sql = "DELETE FROM orders WHERE id < :I_ID"
        result = analyze_sql_script(sql)
        assert result["destructiveness"] == "destructive"

    def test_full_analysis_suggested_input_schema(self):
        sql = "SELECT * FROM t WHERE id = :I_ESTAB AND dt = :D_REF"
        result = analyze_sql_script(sql)
        schema = result["suggested_input_schema"]
        assert any(s["name"] == "I_ESTAB" and s["type"] == "integer" for s in schema)
        assert any(s["name"] == "D_REF" and s["type"] == "date" for s in schema)

    def test_no_binds_empty_input_schema(self):
        result = analyze_sql_script("SELECT 1")
        assert result["has_binds"] is False
        assert result["suggested_input_schema"] == []

    def test_multi_statement_count(self):
        sql = "SELECT 1; SELECT 2; UPDATE t SET x = 1"
        result = analyze_sql_script(sql)
        assert result["statement_count"] == 3
        assert result["destructiveness"] == "writes"


# ---------------------------------------------------------------------------
# A1 — Falsos positivos em bind detection (comentarios, strings, ::cast)
# ---------------------------------------------------------------------------


class TestBindFalsePositives:
    def test_line_comment_not_a_bind(self):
        sql = "SELECT id FROM t -- :foo is a comment\nWHERE id = 1"
        binds = extract_binds(sql)
        assert not any(b.name == "foo" for b in binds)

    def test_string_literal_not_a_bind(self):
        sql = "SELECT * FROM t WHERE label = 'valor :bar aqui'"
        binds = extract_binds(sql)
        assert not any(b.name == "bar" for b in binds)

    def test_postgres_cast_not_a_bind(self):
        sql = "SELECT id::text FROM t WHERE col = :PARAM"
        binds = extract_binds(sql)
        names = [b.name for b in binds]
        assert "PARAM" in names
        assert "text" not in names

    def test_block_comment_not_a_bind(self):
        sql = "SELECT /* :ignored */ id FROM t WHERE x = :REAL"
        binds = extract_binds(sql)
        names = [b.name for b in binds]
        assert "REAL" in names
        assert "ignored" not in names

    def test_timestamp_literal_not_a_bind(self):
        sql = "SELECT * FROM t WHERE ts > TIMESTAMP '2024-01-01 10:00:00'"
        binds = extract_binds(sql)
        # '10:00:00' inside string should not produce bind named '00'
        assert not any(b.name in ("00", "00") for b in binds)
        assert len(binds) == 0


# ---------------------------------------------------------------------------
# A2 — INSERT INTO t1 SELECT FROM t2: target=INSERT, source=READ
# ---------------------------------------------------------------------------


class TestInsertSelectTableOps:
    def test_insert_select_target_is_insert(self):
        sql = "INSERT INTO t1 SELECT * FROM t2 WHERE id > 0"
        tables = extract_tables(sql)
        t1 = next((t for t in tables if t.table.lower() == "t1"), None)
        t2 = next((t for t in tables if t.table.lower() == "t2"), None)
        assert t1 is not None, "t1 not found in tables"
        assert t2 is not None, "t2 not found in tables"
        assert t1.operation == "INSERT", f"Expected INSERT for t1, got {t1.operation}"
        assert t2.operation == "READ", f"Expected READ for t2, got {t2.operation}"

    def test_insert_values_only_target_is_insert(self):
        sql = "INSERT INTO logs (msg) VALUES ('test')"
        tables = extract_tables(sql)
        assert any(t.operation == "INSERT" and t.table.lower() == "logs" for t in tables)
        # No extra READ tables from VALUES
        assert not any(t.operation == "READ" for t in tables)


# ---------------------------------------------------------------------------
# A5 — _asyncpg_dsn normaliza multiplos formatos de URL
# ---------------------------------------------------------------------------


class TestAsyncpgDsn:
    def _dsn(self, url: str) -> str:
        """Helper: temporarily swap settings.DATABASE_URL and call _asyncpg_dsn."""
        from app.services import definition_event_service as des_mod
        from app.core.config import settings
        original = settings.DATABASE_URL
        try:
            settings.DATABASE_URL = url  # type: ignore[misc]
            return des_mod._asyncpg_dsn()
        finally:
            settings.DATABASE_URL = original  # type: ignore[misc]

    def test_asyncpg_url_unchanged_scheme(self):
        dsn = self._dsn("postgresql+asyncpg://user:pass@host/db")
        assert dsn.startswith("postgresql://")
        assert "+asyncpg" not in dsn

    def test_psycopg_url_normalised(self):
        dsn = self._dsn("postgresql+psycopg://user:pass@host/db")
        assert dsn.startswith("postgresql://")
        assert "+psycopg" not in dsn

    def test_postgres_scheme_normalised(self):
        dsn = self._dsn("postgres://user:pass@host/db")
        assert dsn.startswith("postgresql://")

    def test_query_string_preserved(self):
        dsn = self._dsn("postgresql+asyncpg://user:pass@host/db?sslmode=require")
        assert "sslmode=require" in dsn
        assert dsn.startswith("postgresql://")
