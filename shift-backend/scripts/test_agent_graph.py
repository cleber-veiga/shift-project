"""
CLI para testar o grafo do Platform Agent ponta a ponta.

Uso:
  python -m scripts.test_agent_graph --user-id <uuid> --workspace-id <uuid>

O script:
  1. Gera um thread_id novo, cria a thread em agent_threads.
  2. Roda o grafo ate pausar em human_approval (se houver) ou terminar.
  3. Em caso de pausa, pede confirmacao no terminal e faz resume.
  4. Imprime o final_report.

Requer:
  - Banco Postgres acessivel via DATABASE_URL.
  - Configuracoes AGENT_* e LLM_* preenchidas no ambiente.
  - Usuario existente nas tabelas users/workspaces com as permissoes
    necessarias para as tools que o LLM vier a planejar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import asdict
from uuid import UUID

from langgraph.types import Command

from app.db.session import async_session_factory
from app.services.agent.context import UserContext
from app.services.agent.graph.builder import build_graph
from app.services.agent.graph.checkpointer import close_checkpointer, get_checkpointer
from app.services.agent.persistence import ensure_thread


def _ctx_to_dict(ctx: UserContext) -> dict:
    """Serializa UserContext para o estado (UUIDs -> str)."""
    d = asdict(ctx)
    return {
        k: (str(v) if isinstance(v, UUID) else v)
        for k, v in d.items()
    }


async def run(args: argparse.Namespace) -> None:
    checkpointer = await get_checkpointer()
    graph = build_graph(checkpointer=checkpointer)

    thread_uuid = uuid.uuid4()
    thread_id = str(thread_uuid)

    ctx = UserContext(
        user_id=UUID(args.user_id),
        workspace_id=UUID(args.workspace_id),
        project_id=UUID(args.project_id) if args.project_id else None,
        workspace_role=args.workspace_role,
        project_role=args.project_role,
        organization_id=UUID(args.organization_id),
        organization_role=args.organization_role,
    )

    async with async_session_factory() as session:
        await ensure_thread(
            session,
            thread_id=thread_uuid,
            user_id=ctx.user_id,
            workspace_id=ctx.workspace_id,
            project_id=ctx.project_id,
            initial_context=_ctx_to_dict(ctx),
            title=args.message[:80],
        )

    initial_state = {
        "thread_id": thread_id,
        "user_context": _ctx_to_dict(ctx),
        "messages": [{"role": "user", "content": args.message}],
        "executed_actions": [],
    }

    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n>>> thread_id: {thread_id}\n")
    result = await graph.ainvoke(initial_state, config=config)

    while result.get("__interrupt__"):
        interrupts = result["__interrupt__"]
        payload = interrupts[0].value if interrupts else {}
        print("\n=== Aprovacao necessaria ===")
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        answer = input("\nAprovar? [y/N]: ").strip().lower()
        approved = answer in {"y", "s", "sim", "yes"}
        rejection_reason = None
        if not approved:
            rejection_reason = input("Motivo da rejeicao (opcional): ").strip() or None

        result = await graph.ainvoke(
            Command(
                resume={
                    "approved": approved,
                    "decided_by": str(ctx.user_id),
                    "rejection_reason": rejection_reason,
                }
            ),
            config=config,
        )

    print("\n=== Relatorio final ===")
    print(result.get("final_report") or "(sem relatorio)")
    print()
    await close_checkpointer()


def main() -> None:
    parser = argparse.ArgumentParser(description="Teste ponta a ponta do Platform Agent.")
    parser.add_argument("--user-id", required=True, help="UUID do usuario autenticado")
    parser.add_argument("--workspace-id", required=True, help="UUID do workspace")
    parser.add_argument("--organization-id", required=True, help="UUID da organizacao")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--workspace-role", default="MANAGER", choices=["VIEWER", "CONSULTANT", "MANAGER"])
    parser.add_argument("--project-role", default=None, choices=[None, "CLIENT", "EDITOR"])
    parser.add_argument("--organization-role", default="MEMBER")
    parser.add_argument("--message", required=True, help="Mensagem do usuario")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
