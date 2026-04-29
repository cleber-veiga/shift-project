"""
Trava de cobertura para NODE_EXECUTION_PROFILE.

Sem este teste, um nó novo pode ser adicionado a PROCESSOR_REGISTRY sem
entrada correspondente em NODE_EXECUTION_PROFILE. O fallback silencioso
(narrow/local_thread) significa que perfis diferentes (ex: io, output,
control) são aplicados como narrow por engano, e o gap só vira evidente
quando alguém debugga performance ou estratégia.
"""

from __future__ import annotations

# Importa o módulo nodes para popular o registry via decorators.
import app.services.workflow.nodes  # noqa: F401  (side-effect import)
from app.services.workflow.nodes import _PROCESSOR_REGISTRY
from app.orchestration.flows.node_profile import NODE_EXECUTION_PROFILE


def test_todos_processors_registrados_tem_profile() -> None:
    registered = set(_PROCESSOR_REGISTRY.keys())
    profiled = set(NODE_EXECUTION_PROFILE.keys())
    missing = registered - profiled
    assert not missing, (
        f"Faltam em NODE_EXECUTION_PROFILE: {sorted(missing)}. "
        f"Adicione em shift-backend/app/orchestration/flows/node_profile.py "
        f"com shape (narrow/wide/io/output/control) apropriado."
    )


def test_profile_nao_referencia_processor_inexistente() -> None:
    """Entradas extras no profile sem processor correspondente são suspeitas.

    Aliases válidos (ex: 'extractNode' apontando para o mesmo SqlDatabase)
    devem aparecer em ambos lados — se aparecem só no profile, provavelmente
    é resíduo de refactor.
    """
    registered = set(_PROCESSOR_REGISTRY.keys())
    profiled = set(NODE_EXECUTION_PROFILE.keys())
    extra = profiled - registered
    assert not extra, (
        f"Profile tem entradas sem processor: {sorted(extra)}. "
        f"Remova de NODE_EXECUTION_PROFILE ou registre o processor correspondente."
    )


def test_shape_e_strategy_validos() -> None:
    valid_shapes = {"narrow", "wide", "io", "output", "control"}
    valid_strategies = {"local_thread", "data_worker", "io_thread"}

    for node_type, profile in NODE_EXECUTION_PROFILE.items():
        assert profile["shape"] in valid_shapes, (
            f"{node_type}: shape inválido {profile['shape']!r}"
        )
        assert profile["default_strategy"] in valid_strategies, (
            f"{node_type}: strategy inválida {profile['default_strategy']!r}"
        )
