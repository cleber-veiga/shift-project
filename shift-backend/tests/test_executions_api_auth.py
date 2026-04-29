"""
Verifica que GET /executions/{id}/preview e /executions/{id}/plan exigem
require_permission("workspace", "CONSULTANT").

Bug histórico: ambos os endpoints usavam apenas Depends(get_current_user),
permitindo que qualquer usuário autenticado lesse resultado/plano de
qualquer execução se soubesse o ID. A correção troca para
require_permission, que resolve workspace_id a partir do execution_id
do path e valida acesso.
"""

from __future__ import annotations

from app.api.v1 import executions as executions_module


def _route_dependency_callables(endpoint_callable) -> list:
    """Devolve os callables de Depends(...) declarados na assinatura."""
    import inspect
    callables = []
    sig = inspect.signature(endpoint_callable)
    for param in sig.parameters.values():
        default = param.default
        if default is inspect.Parameter.empty:
            continue
        # FastAPI Depends armazena o callable em .dependency
        dep = getattr(default, "dependency", None)
        if dep is not None:
            callables.append(dep)
    return callables


class TestPreviewAuthorization:

    def test_preview_uses_require_permission(self) -> None:
        deps = _route_dependency_callables(executions_module.get_node_preview)
        names = [getattr(d, "__qualname__", "") for d in deps]
        assert any(n.startswith("require_permission") for n in names), (
            f"GET /executions/{{id}}/nodes/{{id}}/preview deve usar "
            f"require_permission. Deps encontradas: {names}"
        )

    def test_preview_does_not_use_get_current_user_only(self) -> None:
        """get_current_user sozinho não autoriza; só autentica."""
        deps = _route_dependency_callables(executions_module.get_node_preview)
        names = [getattr(d, "__qualname__", "") for d in deps]
        # Pode ter get_current_user via require_permission interno, mas não direto.
        assert "get_current_user" not in names, (
            f"Endpoint não pode depender só de get_current_user. Deps: {names}"
        )


class TestPlanAuthorization:

    def test_plan_uses_require_permission(self) -> None:
        deps = _route_dependency_callables(executions_module.get_execution_plan)
        names = [getattr(d, "__qualname__", "") for d in deps]
        assert any(n.startswith("require_permission") for n in names), (
            f"GET /executions/{{id}}/plan deve usar require_permission. "
            f"Deps encontradas: {names}"
        )

    def test_plan_does_not_use_get_current_user_only(self) -> None:
        deps = _route_dependency_callables(executions_module.get_execution_plan)
        names = [getattr(d, "__qualname__", "") for d in deps]
        assert "get_current_user" not in names, (
            f"Endpoint não pode depender só de get_current_user. Deps: {names}"
        )
