"""
Testes para NODE_EXECUTION_PROFILE.

Critério de aceite principal: toda node_type registrada em _PROCESSOR_REGISTRY
deve ter entrada no NODE_EXECUTION_PROFILE.
"""

from __future__ import annotations

import pytest

from app.orchestration.flows.node_profile import NODE_EXECUTION_PROFILE, get_profile
from app.services.workflow.nodes import _PROCESSOR_REGISTRY


class TestNodeProfileCoverage:

    def test_todos_os_tipos_registrados_cobertos(self) -> None:
        """Cada tipo registrado em _PROCESSOR_REGISTRY deve ter entrada no perfil."""
        missing = [
            node_type
            for node_type in _PROCESSOR_REGISTRY
            if node_type not in NODE_EXECUTION_PROFILE
        ]
        assert missing == [], (
            f"NODE_EXECUTION_PROFILE não cobre os seguintes tipos registrados: {missing}\n"
            "Adicione cada um em app/orchestration/flows/node_profile.py."
        )

    def test_shape_values_validos(self) -> None:
        """Todos os shapes devem ser um dos valores permitidos."""
        valid_shapes = {"narrow", "wide", "io", "output", "control"}
        for node_type, profile in NODE_EXECUTION_PROFILE.items():
            assert profile["shape"] in valid_shapes, (
                f"node_type={node_type!r} tem shape={profile['shape']!r} inválido"
            )

    def test_strategy_values_validos(self) -> None:
        """Todas as estratégias devem ser um dos valores permitidos."""
        valid_strategies = {"local_thread", "data_worker", "io_thread"}
        for node_type, profile in NODE_EXECUTION_PROFILE.items():
            assert profile["default_strategy"] in valid_strategies, (
                f"node_type={node_type!r} tem strategy={profile['default_strategy']!r} inválido"
            )


class TestGetProfile:

    def test_tipo_conhecido(self) -> None:
        profile = get_profile("filter")
        assert profile["shape"] == "narrow"
        assert profile["default_strategy"] == "local_thread"

    def test_tipo_desconhecido_fallback(self) -> None:
        """Tipos desconhecidos devem retornar perfil padrão, não levantar exceção."""
        profile = get_profile("tipo_inexistente_xyz")
        assert profile["shape"] == "narrow"
        assert profile["default_strategy"] == "local_thread"

    @pytest.mark.parametrize("node_type,expected_shape", [
        ("join",           "wide"),
        ("lookup",         "wide"),
        ("deduplication",  "wide"),
        ("sql_database",   "io"),
        ("loadNode",       "output"),
        ("ifElse",         "control"),
        ("filter",         "narrow"),
        ("mapper",         "narrow"),
        ("pivot",          "wide"),
        ("text_to_rows",   "wide"),
    ])
    def test_shapes_conhecidos(self, node_type: str, expected_shape: str) -> None:
        assert get_profile(node_type)["shape"] == expected_shape

    @pytest.mark.parametrize("node_type,expected_strategy", [
        ("join",         "data_worker"),
        ("lookup",       "data_worker"),
        ("deduplication","data_worker"),
        ("sql_database", "io_thread"),
        ("filter",       "local_thread"),
    ])
    def test_estrategias_conhecidas(self, node_type: str, expected_strategy: str) -> None:
        assert get_profile(node_type)["default_strategy"] == expected_strategy
