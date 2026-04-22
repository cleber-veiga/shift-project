"""
Testes de ParameterValue em BulkInsertProcessor e CompositeInsertProcessor.

Verifica que:
  - Formato legado { source, target } continua funcionando.
  - Novo formato { value: ParameterValue, target } e aceito.
  - Templates dinamicos sao resolvidos por linha.
  - Valores fixos sao inseridos sem leitura de coluna DuckDB.
  - Mistura legado + PV funciona em bulk insert.
  - composite_insert: _collect_upstream_columns e _resolve_composite_rows
    lidam com PV e strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest

from app.services.workflow.nodes.bulk_insert import (
    _extract_pv_column_refs,
    _normalize_bulk_map,
    _resolve_rows_pv,
)
from app.services.workflow.nodes.composite_insert import (
    _collect_upstream_columns,
    _resolve_composite_rows,
)
from app.services.workflow.parameter_value import ResolutionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(**kwargs: Any) -> ResolutionContext:
    return ResolutionContext(
        input_data=kwargs.get("input_data", {}),
        upstream_results=kwargs.get("upstream_results", {}),
        vars=kwargs.get("vars", {}),
    )


# ---------------------------------------------------------------------------
# _normalize_bulk_map
# ---------------------------------------------------------------------------

class TestNormalizeBulkMap:
    def test_legacy_source_target(self) -> None:
        m = _normalize_bulk_map({"source": "NOME", "target": "name"})
        assert m == {"pv": None, "source": "NOME", "target": "name"}

    def test_new_pv_format(self) -> None:
        pv = {"mode": "dynamic", "template": "{{NOME}}"}
        m = _normalize_bulk_map({"value": pv, "target": "name"})
        assert m is not None
        assert m["pv"] is pv
        assert m["source"] is None
        assert m["target"] == "name"

    def test_fixed_pv_format(self) -> None:
        pv = {"mode": "fixed", "value": "constante"}
        m = _normalize_bulk_map({"value": pv, "target": "col"})
        assert m is not None
        assert m["pv"] is pv
        assert m["target"] == "col"

    def test_missing_target_returns_none(self) -> None:
        assert _normalize_bulk_map({"source": "X"}) is None

    def test_missing_source_and_no_value_returns_none(self) -> None:
        assert _normalize_bulk_map({"target": "col"}) is None

    def test_non_dict_returns_none(self) -> None:
        assert _normalize_bulk_map("not_a_dict") is None


# ---------------------------------------------------------------------------
# _extract_pv_column_refs
# ---------------------------------------------------------------------------

class TestExtractPVColumnRefs:
    def test_single_token(self) -> None:
        assert _extract_pv_column_refs({"mode": "dynamic", "template": "{{NOME}}"}) == ["NOME"]

    def test_multiple_tokens(self) -> None:
        refs = _extract_pv_column_refs({"mode": "dynamic", "template": "{{A}} {{B}}"})
        assert refs == ["A", "B"]

    def test_vars_excluded(self) -> None:
        refs = _extract_pv_column_refs({"mode": "dynamic", "template": "{{NOME}} {{vars.x}}"})
        assert refs == ["NOME"]

    def test_builtin_excluded(self) -> None:
        refs = _extract_pv_column_refs({"mode": "dynamic", "template": "{{$now}}"})
        assert refs == []

    def test_fixed_pv_no_refs(self) -> None:
        assert _extract_pv_column_refs({"mode": "fixed", "value": "abc"}) == []

    def test_non_pv_no_refs(self) -> None:
        assert _extract_pv_column_refs("plain_string") == []


# ---------------------------------------------------------------------------
# _resolve_rows_pv
# ---------------------------------------------------------------------------

class TestResolveRowsPV:
    def _ctx(self) -> ResolutionContext:
        return _make_ctx()

    def test_all_legacy_unchanged(self) -> None:
        valid_maps = [
            {"pv": None, "source": "NOME", "target": "name"},
            {"pv": None, "source": "IDADE", "target": "age"},
        ]
        rows = [{"NOME": "Alice", "IDADE": 30}]
        resolved, mapping = _resolve_rows_pv(rows, valid_maps, self._ctx())
        assert resolved == [{"name": "Alice", "age": 30}]
        assert mapping == [{"source": "name", "target": "name"}, {"source": "age", "target": "age"}]

    def test_pv_dynamic_resolved_per_row(self) -> None:
        valid_maps = [
            {"pv": {"mode": "dynamic", "template": "{{NOME}}"}, "source": None, "target": "name"},
        ]
        rows = [{"NOME": "Alice"}, {"NOME": "Bob"}]
        resolved, _ = _resolve_rows_pv(rows, valid_maps, self._ctx())
        assert [r["name"] for r in resolved] == ["Alice", "Bob"]

    def test_pv_fixed_value(self) -> None:
        valid_maps = [
            {"pv": {"mode": "fixed", "value": "BR"}, "source": None, "target": "country"},
        ]
        rows = [{"X": 1}, {"X": 2}]
        resolved, _ = _resolve_rows_pv(rows, valid_maps, self._ctx())
        assert all(r["country"] == "BR" for r in resolved)

    def test_mixed_legacy_and_pv(self) -> None:
        valid_maps = [
            {"pv": {"mode": "dynamic", "template": "{{NOME}}"}, "source": None, "target": "name"},
            {"pv": None, "source": "IDADE", "target": "age"},
        ]
        rows = [{"NOME": "Alice", "IDADE": 25}]
        resolved, mapping = _resolve_rows_pv(rows, valid_maps, self._ctx())
        assert resolved == [{"name": "Alice", "age": 25}]
        # identity mapping for both
        assert len(mapping) == 2
        assert all(m["source"] == m["target"] for m in mapping)

    def test_pv_vars_resolved(self) -> None:
        ctx = _make_ctx(vars={"prefix": "Dr."})
        valid_maps = [
            {"pv": {"mode": "dynamic", "template": "{{vars.prefix}}"}, "source": None, "target": "title"},
        ]
        rows = [{"X": 1}]
        resolved, _ = _resolve_rows_pv(rows, valid_maps, ctx)
        assert resolved[0]["title"] == "Dr."

    def test_identity_mapping_uses_target_names(self) -> None:
        valid_maps = [
            {"pv": {"mode": "dynamic", "template": "{{COL}}"}, "source": None, "target": "dest_col"},
        ]
        rows = [{"COL": "val"}]
        _, mapping = _resolve_rows_pv(rows, valid_maps, self._ctx())
        assert mapping == [{"source": "dest_col", "target": "dest_col"}]


# ---------------------------------------------------------------------------
# _collect_upstream_columns (composite)
# ---------------------------------------------------------------------------

class TestCollectUpstreamColumns:
    def test_legacy_strings(self) -> None:
        cols = _collect_upstream_columns({"a.x": "NOME", "a.y": "IDADE"})
        assert cols == ["IDADE", "NOME"]

    def test_pv_dynamic(self) -> None:
        cols = _collect_upstream_columns({
            "a.x": {"mode": "dynamic", "template": "{{NOME}}"},
        })
        assert cols == ["NOME"]

    def test_pv_dynamic_multi_token(self) -> None:
        cols = _collect_upstream_columns({
            "a.x": {"mode": "dynamic", "template": "{{A}} {{B}}"},
        })
        assert cols == ["A", "B"]

    def test_pv_dynamic_excludes_vars(self) -> None:
        cols = _collect_upstream_columns({
            "a.x": {"mode": "dynamic", "template": "{{NOME}} {{vars.y}}"},
        })
        assert cols == ["NOME"]

    def test_pv_fixed_no_cols(self) -> None:
        cols = _collect_upstream_columns({
            "a.x": {"mode": "fixed", "value": "static"},
        })
        assert cols == []

    def test_mixed_legacy_and_pv(self) -> None:
        cols = _collect_upstream_columns({
            "a.x": "NOME",
            "b.y": {"mode": "dynamic", "template": "{{COD}}"},
        })
        assert cols == ["COD", "NOME"]

    def test_key_without_dot_ignored(self) -> None:
        cols = _collect_upstream_columns({"no_dot": "NOME", "a.x": "COD"})
        assert cols == ["COD"]


# ---------------------------------------------------------------------------
# _resolve_composite_rows
# ---------------------------------------------------------------------------

class TestResolveCompositeRows:
    def _ctx(self) -> ResolutionContext:
        return _make_ctx()

    def test_all_legacy_passthrough(self) -> None:
        rows = [{"NOME": "Alice"}]
        aug, mapping = _resolve_composite_rows(rows, {"a.x": "NOME"}, self._ctx())
        assert aug is rows  # unchanged
        assert mapping == {"a.x": "NOME"}

    def test_pv_dynamic_creates_synthetic_col(self) -> None:
        rows = [{"NOME": "Alice"}]
        field_mapping = {"a.x": {"mode": "dynamic", "template": "{{NOME}}"}}
        aug, str_map = _resolve_composite_rows(rows, field_mapping, self._ctx())
        syn_col = str_map["a.x"]
        assert syn_col.startswith("__pv_")
        assert aug[0][syn_col] == "Alice"

    def test_pv_fixed_value(self) -> None:
        rows = [{"X": 1}]
        field_mapping = {"a.country": {"mode": "fixed", "value": "BR"}}
        aug, str_map = _resolve_composite_rows(rows, field_mapping, self._ctx())
        syn_col = str_map["a.country"]
        assert aug[0][syn_col] == "BR"

    def test_mixed_legacy_and_pv(self) -> None:
        rows = [{"NOME": "Alice", "COD": 99}]
        field_mapping = {
            "a.name": {"mode": "dynamic", "template": "{{NOME}}"},
            "a.code": "COD",
        }
        aug, str_map = _resolve_composite_rows(rows, field_mapping, self._ctx())
        # Legacy entry unchanged
        assert str_map["a.code"] == "COD"
        assert aug[0]["COD"] == 99
        # PV entry resolved
        syn = str_map["a.name"]
        assert aug[0][syn] == "Alice"

    def test_multiple_rows_resolved_independently(self) -> None:
        rows = [{"NOME": "Alice"}, {"NOME": "Bob"}]
        field_mapping = {"a.x": {"mode": "dynamic", "template": "{{NOME}}"}}
        aug, str_map = _resolve_composite_rows(rows, field_mapping, self._ctx())
        syn = str_map["a.x"]
        assert [r[syn] for r in aug] == ["Alice", "Bob"]

    def test_vars_resolved(self) -> None:
        ctx = _make_ctx(vars={"suffix": "_test"})
        rows = [{"X": 1}]
        field_mapping = {"a.tag": {"mode": "dynamic", "template": "{{vars.suffix}}"}}
        aug, str_map = _resolve_composite_rows(rows, field_mapping, ctx)
        syn = str_map["a.tag"]
        assert aug[0][syn] == "_test"
