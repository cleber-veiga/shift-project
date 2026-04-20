"""
Excecoes, helpers de permissao e utilitarios compartilhados pelas tools.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from app.services.agent.context import UserContext

# ---------------------------------------------------------------------------
# Hierarquia de roles
# ---------------------------------------------------------------------------

_WS_ROLE_RANK: dict[str, int] = {
    "VIEWER": 0,
    "CONSULTANT": 1,
    "MANAGER": 2,
}

_PROJ_ROLE_RANK: dict[str, int] = {
    "CLIENT": 0,
    "EDITOR": 1,
}

# Sequencias que podem ser usadas para injecao de prompt via dados do usuario
_INJECTION_RE = re.compile(r"<\|.*?\|>|#{3,}|\"{3,}|\[\[|\]\]", re.DOTALL)


# ---------------------------------------------------------------------------
# Excecoes
# ---------------------------------------------------------------------------


class AgentToolError(Exception):
    """Erro generico recuperavel — mensagem e repassada ao LLM como resultado."""


class AgentPermissionError(AgentToolError):
    """Violacao de permissao: usuario nao tem role suficiente para a operacao."""


class AgentValidationError(AgentToolError):
    """Argumentos invalidos fornecidos pelo LLM."""


class AgentNotFoundError(AgentToolError):
    """Entidade solicitada nao existe ou esta fora do escopo do usuario."""


# ---------------------------------------------------------------------------
# Helpers de permissao
# ---------------------------------------------------------------------------


def require_workspace_role(ctx: UserContext, min_role: str) -> None:
    """Levanta AgentPermissionError se o workspace_role do usuario for insuficiente."""
    rank = _WS_ROLE_RANK.get(ctx.workspace_role.upper(), -1)
    min_rank = _WS_ROLE_RANK.get(min_role.upper(), 999)
    if rank < min_rank:
        raise AgentPermissionError(
            f"Operacao requer role '{min_role}' no workspace; "
            f"usuario possui '{ctx.workspace_role}'."
        )


def require_project_role(ctx: UserContext, min_role: str) -> None:
    """Levanta AgentPermissionError se o project_role efetivo for insuficiente.

    Workspace MANAGER herda EDITOR em todos os projetos conforme a hierarquia
    definida em security.py (compute_effective_project_role).
    """
    if ctx.workspace_role.upper() == "MANAGER":
        return  # heranca implicita de EDITOR

    role = (ctx.project_role or "").upper()
    rank = _PROJ_ROLE_RANK.get(role, -1)
    min_rank = _PROJ_ROLE_RANK.get(min_role.upper(), 999)
    if rank < min_rank:
        raise AgentPermissionError(
            f"Operacao requer role '{min_role}' no projeto; "
            f"usuario possui '{ctx.project_role or 'nenhum'}'."
        )


# ---------------------------------------------------------------------------
# Sanitizacao contra injecao de prompt
# ---------------------------------------------------------------------------


def sanitize_llm_string(value: str) -> str:
    """Remove sequencias que podem causar injecao de prompt via dados do usuario."""
    return _INJECTION_RE.sub("", value).strip()


# ---------------------------------------------------------------------------
# Serializacao
# ---------------------------------------------------------------------------


def serialize_value(v: Any) -> Any:
    """Converte UUID e datetime para tipos JSON-serializaveis."""
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v
