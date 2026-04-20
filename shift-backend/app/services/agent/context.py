"""
Contexto de usuario para o Platform Agent.

Transporta identidade e roles pre-computados do usuario que iniciou
a thread. Imutavel por design — o contexto nao muda durante a conversa.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UserContext:
    """Identidade e permissoes do usuario que interage com o Platform Agent.

    Todos os roles aqui sao os roles efetivos (ja resolvendo heranca
    de organizacao/workspace), calculados uma vez na criacao da thread.
    """

    user_id: UUID
    workspace_id: UUID
    project_id: UUID | None        # None quando a thread nao esta ancorada num projeto
    workspace_role: str            # VIEWER | CONSULTANT | MANAGER
    project_role: str | None       # CLIENT | EDITOR | None
    organization_id: UUID
    organization_role: str | None  # GUEST | MEMBER | MANAGER | OWNER | None
