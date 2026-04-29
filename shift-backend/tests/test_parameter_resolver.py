"""
Testes para ParameterResolver (Fase 4).

Critério de aceite principal: workflow com ${INEXISTENTE} falha com
ParameterError antes de qualquer nó rodar (< 100ms na prática).
"""

from __future__ import annotations

import pytest

from app.orchestration.flows.parameter_resolver import (
    ParameterError,
    apply_parameters,
    find_unresolved,
    resolve_parameters,
    restore_parameters,
    PARAMETER_RESOLVER_SKIP_FIELDS,
)


# ─── resolve_parameters ───────────────────────────────────────────────────────

class TestResolveParameters:

    def test_substituicao_simples(self) -> None:
        result = resolve_parameters("SELECT * FROM ${TABLE}", {"TABLE": "orders"})
        assert result == "SELECT * FROM orders"

    def test_multiplos_vars(self) -> None:
        result = resolve_parameters("${A} e ${B}", {"A": "foo", "B": "bar"})
        assert result == "foo e bar"

    def test_referencia_desconhecida_intacta(self) -> None:
        result = resolve_parameters("${INEXISTENTE}", {"OTHER": "val"})
        assert result == "${INEXISTENTE}"

    def test_sem_params_retorna_original(self) -> None:
        result = resolve_parameters("texto puro", {})
        assert result == "texto puro"

    def test_sem_placeholder_retorna_original(self) -> None:
        result = resolve_parameters("texto sem var", {"X": "y"})
        assert result == "texto sem var"

    def test_valor_numerico_convertido_para_str(self) -> None:
        result = resolve_parameters("LIMIT ${N}", {"N": 100})
        assert result == "LIMIT 100"


# ─── find_unresolved ─────────────────────────────────────────────────────────

class TestFindUnresolved:

    def test_encontra_referencias_nao_resolvidas(self) -> None:
        names = find_unresolved("${FOO} e ${BAR}")
        assert set(names) == {"FOO", "BAR"}

    def test_string_sem_refs_retorna_vazia(self) -> None:
        assert find_unresolved("sem placeholders") == []


# ─── apply_parameters ────────────────────────────────────────────────────────

def _make_workflow(nodes_data: list[dict]) -> dict:
    return {
        "nodes": [
            {"id": f"n{i}", "data": d}
            for i, d in enumerate(nodes_data)
        ],
        "edges": [],
    }


class TestApplyParameters:

    def test_resolve_simples(self) -> None:
        wf = _make_workflow([{"type": "filter", "condition": "${THRESHOLD}"}])
        restorations = apply_parameters(wf, {"THRESHOLD": "1000"})
        assert wf["nodes"][0]["data"]["condition"] == "1000"
        assert len(restorations) == 1

    def test_resolve_multiplos_nos(self) -> None:
        wf = _make_workflow([
            {"type": "sql_database", "query": "SELECT ${COLS} FROM t"},
            {"type": "filter", "condition": "amount > ${MIN}"},
        ])
        apply_parameters(wf, {"COLS": "*", "MIN": "100"})
        assert wf["nodes"][0]["data"]["query"] == "SELECT * FROM t"
        assert wf["nodes"][1]["data"]["condition"] == "amount > 100"

    def test_fail_fast_referencia_nao_resolvida(self) -> None:
        wf = _make_workflow([{"type": "filter", "condition": "${INEXISTENTE}"}])
        with pytest.raises(ParameterError) as exc_info:
            apply_parameters(wf, {"OUTRO": "valor"})
        assert "INEXISTENTE" in exc_info.value.unresolved

    def test_fail_fast_restaura_antes_de_levantar(self) -> None:
        """Após ParameterError, os dados originais são restaurados."""
        wf = _make_workflow([
            {"type": "filter", "condition": "${OK}", "extra": "${FALTANDO}"},
        ])
        with pytest.raises(ParameterError):
            apply_parameters(wf, {"OK": "valor"})
        # O campo OK foi resolvido temporariamente mas deve ter sido restaurado.
        assert wf["nodes"][0]["data"]["condition"] == "${OK}"

    def test_sem_params_com_refs_levanta(self) -> None:
        wf = _make_workflow([{"type": "filter", "condition": "${VAR}"}])
        with pytest.raises(ParameterError) as exc_info:
            apply_parameters(wf, {})
        assert "VAR" in exc_info.value.unresolved

    def test_sem_params_sem_refs_ok(self) -> None:
        wf = _make_workflow([{"type": "filter", "condition": "amount > 100"}])
        restorations = apply_parameters(wf, {})
        assert restorations == []

    def test_sql_script_body_ignorado(self) -> None:
        """Campos em PARAMETER_RESOLVER_SKIP_FIELDS não devem ser resolvidos."""
        wf = _make_workflow([
            {"type": "sql_script", "body": "SELECT ${RUNTIME_BIND}", "label": "${LABEL}"}
        ])
        apply_parameters(wf, {"LABEL": "Meu Script", "RUNTIME_BIND": "ignored"})
        # body não deve ser alterado (campo skipped)
        assert "${RUNTIME_BIND}" in wf["nodes"][0]["data"]["body"]
        # label deve ser resolvido
        assert wf["nodes"][0]["data"]["label"] == "Meu Script"

    def test_sem_nodes_nao_levanta(self) -> None:
        wf: dict = {"nodes": [], "edges": []}
        restorations = apply_parameters(wf, {"X": "y"})
        assert restorations == []

    def test_error_message_lista_variaveis(self) -> None:
        """ParameterError deve listar todos os nomes não resolvidos."""
        wf = _make_workflow([{"type": "filter", "a": "${X}", "b": "${Y}", "c": "${Z}"}])
        with pytest.raises(ParameterError) as exc_info:
            apply_parameters(wf, {})
        err = exc_info.value
        assert "X" in err.unresolved
        assert "Y" in err.unresolved
        assert "Z" in err.unresolved
        assert "X" in str(err)


# ─── restore_parameters ──────────────────────────────────────────────────────

class TestRestoreParameters:

    def test_restaura_dict(self) -> None:
        d = {"key": "novo"}
        restore_parameters([(d, "key", "original")])
        assert d["key"] == "original"

    def test_restaura_lista_vazia(self) -> None:
        restore_parameters([])  # sem exceção


# ─── PARAMETER_RESOLVER_SKIP_FIELDS ──────────────────────────────────────────

class TestSkipFields:

    def test_sql_script_tem_body(self) -> None:
        assert "body" in PARAMETER_RESOLVER_SKIP_FIELDS.get("sql_script", frozenset())

    def test_code_tem_script(self) -> None:
        assert "script" in PARAMETER_RESOLVER_SKIP_FIELDS.get("code", frozenset())


# ─── Restore pattern (espelha o try/finally do dynamic_runner) ────────────────

class TestApplyThenRestoreKeepsPayloadPristine:
    """Garante que o pattern do runner deixa resolved_payload imutado.

    Bug latente: dynamic_runner aplicava apply_parameters mas nunca chamava
    restore_parameters no finally — o payload ficava mutado. Para
    workflows reusados (loops inline, sub-workflows), segunda passada via
    valores resolvidos em vez do template original.
    """

    def test_payload_volta_ao_estado_original_apos_restore(self) -> None:
        wf = _make_workflow([
            {"type": "sql_database", "query": "SELECT * FROM ${TABLE}"},
            {"type": "filter", "condition": "amount > ${MIN}"},
        ])
        original_query = wf["nodes"][0]["data"]["query"]
        original_condition = wf["nodes"][1]["data"]["condition"]

        restorations = apply_parameters(wf, {"TABLE": "orders", "MIN": "100"})

        # Sanity: foi mutado in-place.
        assert wf["nodes"][0]["data"]["query"] == "SELECT * FROM orders"
        assert wf["nodes"][1]["data"]["condition"] == "amount > 100"

        # Restauração devolve o template original.
        restore_parameters(restorations)
        assert wf["nodes"][0]["data"]["query"] == original_query
        assert wf["nodes"][1]["data"]["condition"] == original_condition

    def test_segunda_aplicacao_apos_restore_funciona(self) -> None:
        """Reutiliza o mesmo payload com valores diferentes — garante que
        loops inline/sub-workflows possam re-aplicar parâmetros."""
        wf = _make_workflow([{"type": "filter", "condition": "x = ${V}"}])

        r1 = apply_parameters(wf, {"V": "1"})
        assert wf["nodes"][0]["data"]["condition"] == "x = 1"
        restore_parameters(r1)

        r2 = apply_parameters(wf, {"V": "2"})
        assert wf["nodes"][0]["data"]["condition"] == "x = 2"
        restore_parameters(r2)

        # Após segunda restauração: template original.
        assert wf["nodes"][0]["data"]["condition"] == "x = ${V}"
