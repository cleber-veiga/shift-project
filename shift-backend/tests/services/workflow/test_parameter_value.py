"""
Testes unitários para app.services.workflow.parameter_value.

Cobre todos os casos especificados:
  - modo fixed
  - dynamic com token único (preserva tipo)
  - dynamic com concatenação (string)
  - referência {{node_X.campo}} via upstream_results
  - referência {{vars.X}} via ctx.vars
  - builtins $now e $uuid
  - cada transform
  - erros: template vazio, nó/campo inexistente
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.workflow.parameter_value import (
    DynamicValue,
    FixedValue,
    ResolutionContext,
    TransformEntry,
    extract_field_reference,
    migrate_legacy_sql_parameter,
    parse_parameter_value,
    resolve_parameter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ctx(
    input_data: dict[str, Any] | None = None,
    upstream_results: dict[str, dict[str, Any]] | None = None,
    vars: dict[str, Any] | None = None,
) -> ResolutionContext:
    return ResolutionContext(
        input_data=input_data,
        upstream_results=upstream_results,
        vars=vars,
    )


def fixed(value: str) -> FixedValue:
    return FixedValue(value=value)


def dynamic(
    template: str,
    transforms: list[dict] | None = None,
) -> DynamicValue:
    entries = [TransformEntry(**t) for t in (transforms or [])]
    return DynamicValue(template=template, transforms=entries)


# ---------------------------------------------------------------------------
# Modo fixed
# ---------------------------------------------------------------------------

class TestFixedMode:
    def test_returns_value_directly(self):
        assert resolve_parameter(fixed("hello world"), ctx()) == "hello world"

    def test_empty_string_is_valid(self):
        assert resolve_parameter(fixed(""), ctx()) == ""

    def test_whitespace_is_preserved(self):
        assert resolve_parameter(fixed("  padded  "), ctx()) == "  padded  "


# ---------------------------------------------------------------------------
# Modo dynamic — token único (preserva tipo)
# ---------------------------------------------------------------------------

class TestDynamicSingleToken:
    def test_preserves_int(self):
        result = resolve_parameter(
            dynamic("{{count}}"),
            ctx(input_data={"count": 42}),
        )
        assert result == 42
        assert isinstance(result, int)

    def test_preserves_bool(self):
        result = resolve_parameter(
            dynamic("{{flag}}"),
            ctx(input_data={"flag": True}),
        )
        assert result is True
        assert isinstance(result, bool)

    def test_preserves_float(self):
        result = resolve_parameter(
            dynamic("{{price}}"),
            ctx(input_data={"price": 3.14}),
        )
        assert result == pytest.approx(3.14)

    def test_preserves_none(self):
        result = resolve_parameter(
            dynamic("{{x}}"),
            ctx(input_data={"x": None}),
        )
        assert result is None

    def test_preserves_list(self):
        data = [1, 2, 3]
        result = resolve_parameter(
            dynamic("{{items}}"),
            ctx(input_data={"items": data}),
        )
        assert result == data


# ---------------------------------------------------------------------------
# Modo dynamic — concatenação (string output)
# ---------------------------------------------------------------------------

class TestDynamicConcatenation:
    def test_two_tokens(self):
        result = resolve_parameter(
            dynamic("{{first}} {{last}}"),
            ctx(input_data={"first": "João", "last": "Silva"}),
        )
        assert result == "João Silva"
        assert isinstance(result, str)

    def test_text_between_tokens(self):
        result = resolve_parameter(
            dynamic("Rua {{ENDERECO}} nº {{NUMERO}}"),
            ctx(input_data={"ENDERECO": "das Flores", "NUMERO": 100}),
        )
        assert result == "Rua das Flores nº 100"

    def test_template_literal_without_tokens(self):
        result = resolve_parameter(
            dynamic("literal string"),
            ctx(),
        )
        assert result == "literal string"

    def test_none_value_becomes_empty_string(self):
        result = resolve_parameter(
            dynamic("prefix-{{x}}-suffix"),
            ctx(input_data={"x": None}),
        )
        assert result == "prefix--suffix"


# ---------------------------------------------------------------------------
# Referências a upstream_results e vars
# ---------------------------------------------------------------------------

class TestUpstreamAndVars:
    def test_upstream_node_field(self):
        result = resolve_parameter(
            dynamic("{{node_A.city}}"),
            ctx(upstream_results={"node_A": {"city": "São Paulo"}}),
        )
        assert result == "São Paulo"

    def test_upstream_node_field_in_concatenation(self):
        result = resolve_parameter(
            dynamic("De {{node_A.origin}} para {{node_B.dest}}"),
            ctx(
                upstream_results={
                    "node_A": {"origin": "BH"},
                    "node_B": {"dest": "SP"},
                }
            ),
        )
        assert result == "De BH para SP"

    def test_vars_reference(self):
        result = resolve_parameter(
            dynamic("{{vars.env}}"),
            ctx(vars={"env": "production"}),
        )
        assert result == "production"

    def test_vars_int_preserved_single_token(self):
        result = resolve_parameter(
            dynamic("{{vars.timeout}}"),
            ctx(vars={"timeout": 30}),
        )
        assert result == 30
        assert isinstance(result, int)

    def test_mixed_input_upstream_vars(self):
        result = resolve_parameter(
            dynamic("{{name}} / {{node_X.dept}} / {{vars.env}}"),
            ctx(
                input_data={"name": "Alice"},
                upstream_results={"node_X": {"dept": "Eng"}},
                vars={"env": "prod"},
            ),
        )
        assert result == "Alice / Eng / prod"


# ---------------------------------------------------------------------------
# Builtins $now e $uuid
# ---------------------------------------------------------------------------

class TestBuiltins:
    def test_now_returns_iso_string(self):
        result = resolve_parameter(dynamic("$now"), ctx())
        assert isinstance(result, str)
        # ISO 8601 com fuso horário UTC
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result)
        assert result.endswith("+00:00") or result.endswith("Z")

    def test_uuid_returns_uuid4_string(self):
        result = resolve_parameter(dynamic("$uuid"), ctx())
        assert isinstance(result, str)
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            result,
        )

    def test_uuid_is_different_each_call(self):
        r1 = resolve_parameter(dynamic("$uuid"), ctx())
        r2 = resolve_parameter(dynamic("$uuid"), ctx())
        assert r1 != r2

    def test_now_in_concatenation(self):
        result = resolve_parameter(dynamic("ts=$now id={{x}}"), ctx(input_data={"x": "abc"}))
        assert result.startswith("ts=")
        assert "id=abc" in result

    def test_builtin_in_template_with_surrounding_text(self):
        result = resolve_parameter(dynamic("prefix-$uuid-suffix"), ctx())
        assert result.startswith("prefix-")
        assert result.endswith("-suffix")


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

class TestTransforms:
    def _run(self, template: str, transforms: list[dict], input_data: dict) -> Any:
        return resolve_parameter(
            dynamic(template, transforms),
            ctx(input_data=input_data),
        )

    def test_upper(self):
        result = self._run("{{name}}", [{"kind": "upper"}], {"name": "hello"})
        assert result == "HELLO"

    def test_lower(self):
        result = self._run("{{name}}", [{"kind": "lower"}], {"name": "WORLD"})
        assert result == "world"

    def test_trim(self):
        result = self._run("{{val}}", [{"kind": "trim"}], {"val": "  spaces  "})
        assert result == "spaces"

    def test_digits_only(self):
        result = self._run("{{cpf}}", [{"kind": "digits_only"}], {"cpf": "123.456.789-00"})
        assert result == "12345678900"

    def test_remove_specials(self):
        result = self._run(
            "{{txt}}", [{"kind": "remove_specials"}], {"txt": "Olá, mundo!"}
        )
        assert result == "Ol mundo"

    def test_replace(self):
        result = self._run(
            "{{slug}}",
            [{"kind": "replace", "args": {"old": " ", "new": "-"}}],
            {"slug": "hello world foo"},
        )
        assert result == "hello-world-foo"

    def test_truncate(self):
        result = self._run(
            "{{text}}",
            [{"kind": "truncate", "args": {"length": 5}}],
            {"text": "abcdefghij"},
        )
        assert result == "abcde"

    def test_remove_chars_basic(self):
        result = self._run(
            "{{fone}}",
            [{"kind": "remove_chars", "args": {"chars": "()-."}}],
            {"fone": "(54) 9988-9051"},
        )
        assert result == "54 99889051"

    def test_remove_chars_removes_all_occurrences(self):
        result = self._run(
            "{{cpf}}",
            [{"kind": "remove_chars", "args": {"chars": ".-/"}}],
            {"cpf": "123.456.789-00"},
        )
        assert result == "12345678900"

    def test_remove_chars_hyphen_special_case(self):
        # Hyphen inside char class must not be treated as range
        result = self._run(
            "{{v}}",
            [{"kind": "remove_chars", "args": {"chars": "-"}}],
            {"v": "a-b-c"},
        )
        assert result == "abc"

    def test_remove_chars_backslash_special_case(self):
        result = self._run(
            "{{v}}",
            [{"kind": "remove_chars", "args": {"chars": "\\"}}],
            {"v": "a\\b\\c"},
        )
        assert result == "abc"

    def test_remove_chars_empty_chars_noop(self):
        result = self._run(
            "{{v}}",
            [{"kind": "remove_chars", "args": {"chars": ""}}],
            {"v": "unchanged"},
        )
        assert result == "unchanged"

    def test_transforms_applied_in_order(self):
        # upper → then truncate
        result = self._run(
            "{{v}}",
            [{"kind": "upper"}, {"kind": "truncate", "args": {"length": 3}}],
            {"v": "hello"},
        )
        assert result == "HEL"

    def test_transform_converts_int_to_string(self):
        result = self._run("{{n}}", [{"kind": "upper"}], {"n": 42})
        assert result == "42"

    def test_transforms_on_concatenated_string(self):
        result = resolve_parameter(
            dynamic("{{a}} {{b}}", [{"kind": "upper"}]),
            ctx(input_data={"a": "hello", "b": "world"}),
        )
        assert result == "HELLO WORLD"


# ---------------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------------

class TestErrors:
    def test_empty_template_raises_validation_error(self):
        with pytest.raises(ValidationError):
            DynamicValue(template="")

    def test_blank_template_raises_validation_error(self):
        with pytest.raises(ValidationError):
            DynamicValue(template="   ")

    def test_missing_input_field_raises_key_error(self):
        with pytest.raises(KeyError, match="nao_existe|não encontrado"):
            resolve_parameter(dynamic("{{nao_existe}}"), ctx())

    def test_missing_upstream_node_raises_key_error(self):
        with pytest.raises(KeyError, match="node_X|não encontrado"):
            resolve_parameter(
                dynamic("{{node_X.field}}"),
                ctx(upstream_results={}),
            )

    def test_missing_upstream_field_raises_key_error(self):
        with pytest.raises(KeyError, match="campo_y|não encontrado"):
            resolve_parameter(
                dynamic("{{node_A.campo_y}}"),
                ctx(upstream_results={"node_A": {"other": 1}}),
            )

    def test_missing_var_raises_key_error(self):
        with pytest.raises(KeyError, match="vars.missing|não encontrada"):
            resolve_parameter(dynamic("{{vars.missing}}"), ctx(vars={}))

    def test_unknown_builtin_raises_value_error(self):
        with pytest.raises(ValueError, match="desconhecida"):
            resolve_parameter(dynamic("$unknown_fn"), ctx())


# ---------------------------------------------------------------------------
# parse_parameter_value
# ---------------------------------------------------------------------------

class TestParseParameterValue:
    def test_parses_fixed(self):
        v = parse_parameter_value({"mode": "fixed", "value": "x"})
        assert isinstance(v, FixedValue)
        assert v.value == "x"

    def test_parses_dynamic(self):
        v = parse_parameter_value({"mode": "dynamic", "template": "{{x}}"})
        assert isinstance(v, DynamicValue)
        assert v.template == "{{x}}"

    def test_parses_dynamic_with_transforms(self):
        v = parse_parameter_value({
            "mode": "dynamic",
            "template": "{{name}}",
            "transforms": [{"kind": "upper"}],
        })
        assert isinstance(v, DynamicValue)
        assert v.transforms[0].kind == "upper"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            parse_parameter_value({"mode": "bad"})

    def test_missing_template_raises(self):
        with pytest.raises(ValidationError):
            parse_parameter_value({"mode": "dynamic", "template": ""})


# ---------------------------------------------------------------------------
# migrate_legacy_sql_parameter
# ---------------------------------------------------------------------------

class TestMigrateLegacySqlParameter:
    def test_upstream_results_prefix(self):
        pv = migrate_legacy_sql_parameter("upstream_results.node_X.data.CAMPO")
        assert isinstance(pv, DynamicValue)
        assert pv.template == "{{node_X.data.CAMPO}}"

    def test_upstream_alias(self):
        pv = migrate_legacy_sql_parameter("upstream.node_X.CAMPO")
        assert isinstance(pv, DynamicValue)
        assert pv.template == "{{node_X.CAMPO}}"

    def test_plain_string_becomes_fixed(self):
        pv = migrate_legacy_sql_parameter("valor_literal")
        assert isinstance(pv, FixedValue)
        assert pv.value == "valor_literal"

    def test_empty_string_becomes_fixed_empty(self):
        pv = migrate_legacy_sql_parameter("")
        assert isinstance(pv, FixedValue)
        assert pv.value == ""

    def test_already_fixed_dict(self):
        pv = migrate_legacy_sql_parameter({"mode": "fixed", "value": "hello"})
        assert isinstance(pv, FixedValue)
        assert pv.value == "hello"

    def test_already_dynamic_dict(self):
        pv = migrate_legacy_sql_parameter({"mode": "dynamic", "template": "{{X}}"})
        assert isinstance(pv, DynamicValue)
        assert pv.template == "{{X}}"

    def test_non_string_becomes_fixed(self):
        pv = migrate_legacy_sql_parameter(42)
        assert isinstance(pv, FixedValue)
        assert pv.value == "42"

    def test_resolve_migrated_legacy_path(self):
        """Round-trip: migrar path legado e resolver via ResolutionContext."""
        pv = migrate_legacy_sql_parameter("upstream_results.node_A.CNPJ")
        assert isinstance(pv, DynamicValue)
        result = resolve_parameter(
            pv,
            ResolutionContext(
                upstream_results={"node_A": {"CNPJ": "00000000000100"}},
            ),
        )
        assert result == "00000000000100"

    def test_resolve_migrated_nested_path(self):
        """Token multi-segmento (com 'data') percorre aninhamento."""
        pv = migrate_legacy_sql_parameter("upstream_results.node_A.data.IDITEM")
        result = resolve_parameter(
            pv,
            ResolutionContext(
                upstream_results={"node_A": {"data": {"IDITEM": "XYZ"}}},
            ),
        )
        assert result == "XYZ"


# ---------------------------------------------------------------------------
# _resolve_token — multi-segment paths
# ---------------------------------------------------------------------------

class TestResolveTokenMultiSegment:
    def test_two_segment_path(self):
        pv = DynamicValue(template="{{node_X.CAMPO}}")
        result = resolve_parameter(
            pv,
            ResolutionContext(upstream_results={"node_X": {"CAMPO": "valor"}}),
        )
        assert result == "valor"

    def test_three_segment_path(self):
        pv = DynamicValue(template="{{node_X.data.CAMPO}}")
        result = resolve_parameter(
            pv,
            ResolutionContext(
                upstream_results={"node_X": {"data": {"CAMPO": "aninhado"}}},
            ),
        )
        assert result == "aninhado"

    def test_missing_intermediate_key_raises(self):
        pv = DynamicValue(template="{{node_X.inexistente.CAMPO}}")
        with pytest.raises(KeyError, match="inexistente"):
            resolve_parameter(
                pv,
                ResolutionContext(upstream_results={"node_X": {"outro": {}}}),
            )


# ---------------------------------------------------------------------------
# extract_field_reference
# ---------------------------------------------------------------------------

class TestExtractFieldReference:
    def test_plain_string_returned_as_is(self):
        assert extract_field_reference("NOME") == "NOME"

    def test_none_returns_empty_string(self):
        assert extract_field_reference(None) == ""

    def test_fixed_pv_returns_value(self):
        assert extract_field_reference({"mode": "fixed", "value": "COL_A"}) == "COL_A"

    def test_fixed_pv_empty_value_returns_empty(self):
        assert extract_field_reference({"mode": "fixed", "value": ""}) == ""

    def test_dynamic_single_token_returns_field_name(self):
        assert extract_field_reference({"mode": "dynamic", "template": "{{CAMPO}}"}) == "CAMPO"

    def test_dynamic_node_path_token_returned(self):
        assert extract_field_reference({"mode": "dynamic", "template": "{{node_X.CAMPO}}"}) == "node_X.CAMPO"

    def test_dynamic_multi_token_returns_full_template(self):
        result = extract_field_reference({"mode": "dynamic", "template": "{{A}} {{B}}"})
        assert result == "{{A}} {{B}}"

    def test_dynamic_text_plus_token_returns_full_template(self):
        result = extract_field_reference({"mode": "dynamic", "template": "prefix_{{COL}}"})
        assert result == "prefix_{{COL}}"

    def test_dynamic_single_token_with_transforms_returns_field(self):
        # transforms não interferem na extração do nome do campo
        pv = {"mode": "dynamic", "template": "{{FONE}}", "transforms": [{"kind": "digits_only"}]}
        assert extract_field_reference(pv) == "FONE"

    def test_dynamic_with_whitespace_around_token(self):
        assert extract_field_reference({"mode": "dynamic", "template": "  {{COL}}  "}) == "COL"

    def test_unknown_dict_no_mode_returns_str(self):
        result = extract_field_reference({"foo": "bar"})
        assert result == str({"foo": "bar"})
