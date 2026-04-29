"""
Parameter Resolver — substituição de ${var} recursiva com fail-fast.

Porte adaptado de flowfile_core/flowfile_core/flowfile/parameter_resolver.py
(ver flowfile-mechanisms.md §4), com ajustes para Shift:
  - Pydantic v2 (model_fields em vez de __fields__)
  - Validação fail-fast: raise ParameterError antes de qualquer side effect
  - Lista PARAMETER_RESOLVER_SKIP_FIELDS por node_type (ex: sql_script.body
    usa bindings runtime intencionais e não deve ser pré-resolvido)

Uso no dynamic_runner (antes do loop de execução):
    from app.orchestration.flows.parameter_resolver import (
        apply_parameters, ParameterError
    )
    apply_parameters(workflow_definition, variable_values or {})
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

_PARAM_PATTERN = re.compile(r"\$\{([^}]+)\}")

# Campos que nunca devem ser pré-resolvidos — têm bindings runtime intencionais.
# Formato: {node_type: {field_name, ...}}
PARAMETER_RESOLVER_SKIP_FIELDS: dict[str, frozenset[str]] = {
    "sql_script": frozenset({"body", "query", "sql"}),
    "code":       frozenset({"script", "code", "body"}),
}

# Restorations = lista de (objeto, campo, valor_original) para reverter após exec.
_Restoration = tuple[Any, str, str]
_Restorations = list[_Restoration]


class ParameterError(ValueError):
    """Raised when ${var} references cannot be resolved before execution."""

    def __init__(self, unresolved: list[str]) -> None:
        self.unresolved = sorted(unresolved)
        super().__init__(
            f"Unresolved parameter references: {self.unresolved}. "
            "Declare os parâmetros no workflow antes de executar."
        )


def resolve_parameters(text: str, params: dict[str, Any]) -> str:
    """Substitui ${name} por params[name]. Referências desconhecidas ficam intactas."""
    if not params or "${" not in text:
        return text
    return _PARAM_PATTERN.sub(
        lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0),
        text,
    )


def find_unresolved(text: str) -> list[str]:
    """Retorna lista de names em ${name} que ainda não foram resolvidos."""
    return _PARAM_PATTERN.findall(text)


def _apply_recursive(
    obj: Any,
    params: dict[str, Any],
    restorations: _Restorations,
    skip_fields: frozenset[str],
) -> None:
    """Mutação in-place recursiva em Pydantic BaseModel, dict e list."""
    if isinstance(obj, BaseModel):
        for field_name in obj.model_fields:
            if field_name in skip_fields:
                continue
            value = getattr(obj, field_name, None)
            if isinstance(value, str) and "${" in value:
                resolved = resolve_parameters(value, params)
                if resolved != value:
                    restorations.append((obj, field_name, value))
                    object.__setattr__(obj, field_name, resolved)
            elif value is not None:
                _apply_recursive(value, params, restorations, frozenset())
        return

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in skip_fields:
                continue
            if isinstance(value, str) and "${" in value:
                resolved = resolve_parameters(value, params)
                if resolved != value:
                    restorations.append((obj, key, value))
                    obj[key] = resolved
            elif value is not None:
                _apply_recursive(value, params, restorations, frozenset())
        return

    if isinstance(obj, list):
        for item in obj:
            if item is not None:
                _apply_recursive(item, params, restorations, frozenset())


def _find_unresolved_in_obj(obj: Any) -> set[str]:
    """Encontra todos os ${name} que sobraram após a resolução."""
    unresolved: set[str] = set()

    if isinstance(obj, BaseModel):
        for field_name in obj.model_fields:
            value = getattr(obj, field_name, None)
            if isinstance(value, str):
                unresolved.update(find_unresolved(value))
            elif value is not None:
                unresolved.update(_find_unresolved_in_obj(value))
        return unresolved

    if isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, str):
                unresolved.update(find_unresolved(value))
            elif value is not None:
                unresolved.update(_find_unresolved_in_obj(value))
        return unresolved

    if isinstance(obj, list):
        for item in obj:
            if item is not None:
                unresolved.update(_find_unresolved_in_obj(item))

    if isinstance(obj, str):
        unresolved.update(find_unresolved(obj))

    return unresolved


def restore_parameters(restorations: _Restorations) -> None:
    """Reverte todas as mutações feitas por _apply_recursive."""
    for obj, field, original in restorations:
        if isinstance(obj, BaseModel):
            object.__setattr__(obj, field, original)
        elif isinstance(obj, dict):
            obj[field] = original


def apply_parameters(
    workflow_definition: dict[str, Any],
    params: dict[str, Any],
) -> _Restorations:
    """Resolve ${var} em todas as configs dos nós do workflow definition.

    Mutação in-place: cada node['data'] é percorrido recursivamente.
    Se algum ${var} não for resolvido, restaura tudo e levanta ParameterError.

    Retorna lista de restorations — o caller pode reverter após execução.
    """
    if not params:
        # Sem params declarados: qualquer ${} no workflow é erro imediato.
        unresolved: set[str] = set()
        for node in workflow_definition.get("nodes", []):
            node_data = node.get("data") if isinstance(node, dict) else None
            if node_data:
                unresolved.update(_find_unresolved_in_obj(node_data))
        if unresolved:
            raise ParameterError(list(unresolved))
        return []

    restorations: _Restorations = []
    nodes = workflow_definition.get("nodes", [])

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_data = node.get("data")
        if not isinstance(node_data, dict):
            continue

        # Determina skip_fields pelo node_type
        node_type = str(node_data.get("type", ""))
        skip = PARAMETER_RESOLVER_SKIP_FIELDS.get(node_type, frozenset())

        _apply_recursive(node_data, params, restorations, skip)

    # Fail-fast: nenhum ${} deve sobrar (excluindo campos em skip_fields).
    remaining: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_data = node.get("data")
        if not isinstance(node_data, dict):
            continue
        node_type = str(node_data.get("type", ""))
        skip_for_check = PARAMETER_RESOLVER_SKIP_FIELDS.get(node_type, frozenset())
        filtered_data = {k: v for k, v in node_data.items() if k not in skip_for_check}
        remaining.update(_find_unresolved_in_obj(filtered_data))

    if remaining:
        restore_parameters(restorations)
        raise ParameterError(list(remaining))

    return restorations
