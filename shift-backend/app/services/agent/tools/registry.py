"""
Registry unificado das tools do Platform Agent.

Este modulo e o ponto de integracao com o grafo LangGraph (Fase 2).
Expoe TOOL_SCHEMAS (formato OpenAI function calling), TOOL_REGISTRY
(metadados + funcao), requires_approval() e execute_tool() dispatcher.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.base import (
    AgentNotFoundError,
    AgentPermissionError,
    AgentToolError,
    AgentValidationError,
)
from app.services.agent.context import UserContext
from app.services.agent.tools.connection_tools import (
    get_connection,
    list_connections,
    test_connection,
)
from app.services.agent.tools.project_tools import (
    create_project,
    get_project,
    list_project_members,
    list_projects,
)
from app.services.agent.tools.webhook_tools import (
    list_webhooks,
    trigger_webhook_manually,
)
from app.services.agent.tools.workflow_tools import (
    cancel_execution,
    execute_workflow,
    get_execution_status,
    get_workflow,
    list_recent_executions,
    list_workflows,
)

ToolFunc = Callable[..., Awaitable[Any]]

# ---------------------------------------------------------------------------
# Schemas (formato OpenAI function calling)
# ---------------------------------------------------------------------------

_LIST_WORKFLOWS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_workflows",
        "description": (
            "Lista workflows do projeto ou workspace atual com nome, status e id. "
            "Especifique project_id para filtrar por um projeto especifico. "
            "Use limit para controlar o numero de resultados (padrao 20)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID do projeto para filtrar workflows (opcional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de workflows a retornar (padrao 20, max 100)",
                },
            },
            "required": [],
        },
    },
}

_GET_WORKFLOW_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_workflow",
        "description": (
            "Retorna detalhes completos de um workflow: nome, descricao, status, "
            "numero de nos, se e template/publicado e data de criacao. "
            "Use antes de executar para confirmar o workflow correto."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
            },
            "required": ["workflow_id"],
        },
    },
}

_EXECUTE_WORKFLOW_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "execute_workflow",
        "description": (
            "Dispara a execucao de um workflow. Operacao destrutiva — "
            "SEMPRE exige aprovacao humana antes de rodar. "
            "Retorna execution_id para monitoramento via get_execution_status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow a executar",
                },
                "trigger_params": {
                    "type": "object",
                    "description": (
                        "Parametros de entrada para o workflow (quando necessario)"
                    ),
                },
            },
            "required": ["workflow_id"],
        },
    },
}

_GET_EXECUTION_STATUS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_execution_status",
        "description": (
            "Retorna o status atual de uma execucao de workflow: "
            "RUNNING, COMPLETED, FAILED, CANCELLED ou CRASHED, "
            "com timestamps de inicio/fim e mensagem de erro quando houver."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "execution_id": {
                    "type": "string",
                    "description": "UUID da execucao retornado por execute_workflow",
                },
            },
            "required": ["execution_id"],
        },
    },
}

_LIST_RECENT_EXECUTIONS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_recent_executions",
        "description": (
            "Lista as ultimas execucoes de um workflow ordenadas pela mais recente, "
            "com status e timestamps. Util para diagnosticar falhas ou verificar "
            "o historico de execucoes recentes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de execucoes a retornar (padrao 10, max 50)",
                },
            },
            "required": ["workflow_id"],
        },
    },
}

_CANCEL_EXECUTION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cancel_execution",
        "description": (
            "Solicita cancelamento de uma execucao em andamento. "
            "Operacao destrutiva — exige aprovacao humana. "
            "Nao garante cancelamento imediato; o status e atualizado de forma assincrona."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "execution_id": {
                    "type": "string",
                    "description": "UUID da execucao a cancelar",
                },
            },
            "required": ["execution_id"],
        },
    },
}

_LIST_PROJECTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_projects",
        "description": (
            "Lista os projetos do workspace atual visiveis ao usuario, "
            "ordenados por nome, com id e descricao. "
            "Use get_project para obter detalhes completos de um projeto especifico."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de projetos a retornar (padrao 20)",
                },
            },
            "required": [],
        },
    },
}

_GET_PROJECT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_project",
        "description": (
            "Retorna detalhes completos de um projeto: nome, descricao, id, "
            "numero de workflows e conexoes associadas. "
            "Use list_projects para descobrir o project_id correto."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID do projeto",
                },
            },
            "required": ["project_id"],
        },
    },
}

_CREATE_PROJECT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_project",
        "description": (
            "Cria um novo projeto no workspace atual. "
            "Operacao destrutiva — exige aprovacao humana antes de criar. "
            "Requer role MANAGER no workspace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nome do projeto (1 a 255 caracteres)",
                },
                "description": {
                    "type": "string",
                    "description": "Descricao opcional do projeto",
                },
            },
            "required": ["name"],
        },
    },
}

_LIST_PROJECT_MEMBERS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_project_members",
        "description": (
            "Lista os membros de um projeto com seus roles (EDITOR ou CLIENT) "
            "e datas de ingresso. Util para entender quem tem acesso e qual nivel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID do projeto",
                },
            },
            "required": ["project_id"],
        },
    },
}

_LIST_CONNECTIONS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_connections",
        "description": (
            "Lista as conexoes de banco de dados visiveis ao usuario no workspace "
            "ou projeto atual, com nome, tipo e host. "
            "Nunca retorna senhas, tokens ou strings de conexao."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID do projeto para filtrar conexoes (opcional)",
                },
            },
            "required": [],
        },
    },
}

_GET_CONNECTION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_connection",
        "description": (
            "Retorna metadados nao-sensiveis de uma conexao: nome, tipo, host, "
            "porta, banco e usuario. "
            "Nunca retorna senhas, tokens ou strings de conexao."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {
                    "type": "string",
                    "description": "UUID da conexao",
                },
            },
            "required": ["connection_id"],
        },
    },
}

_TEST_CONNECTION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "test_connection",
        "description": (
            "Testa a conectividade de uma conexao de banco de dados com timeout "
            "de 5 segundos. Operacao read-only — nao altera dados nem exige aprovacao. "
            "Retorna SUCESSO ou FALHA com mensagem descritiva."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {
                    "type": "string",
                    "description": "UUID da conexao a testar",
                },
            },
            "required": ["connection_id"],
        },
    },
}

_LIST_WEBHOOKS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_webhooks",
        "description": (
            "Lista os nos webhook configurados nos workflows do projeto ou workspace "
            "atual, com o path de disparo e o workflow associado. "
            "Use trigger_webhook_manually para simular um disparo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID do projeto para filtrar (opcional)",
                },
            },
            "required": [],
        },
    },
}

_TRIGGER_WEBHOOK_MANUALLY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "trigger_webhook_manually",
        "description": (
            "Simula uma chamada ao webhook de um workflow em modo de teste. "
            "Operacao destrutiva — exige aprovacao humana antes de disparar. "
            "Retorna execution_id para acompanhamento."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow que possui o no webhook",
                },
                "payload": {
                    "type": "object",
                    "description": "Payload JSON a enviar para o webhook (opcional)",
                },
            },
            "required": ["workflow_id"],
        },
    },
}

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "list_workflows": {
        "func": list_workflows,
        "schema": _LIST_WORKFLOWS_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "get_workflow": {
        "func": get_workflow,
        "schema": _GET_WORKFLOW_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "execute_workflow": {
        "func": execute_workflow,
        "schema": _EXECUTE_WORKFLOW_SCHEMA,
        "requires_approval": True,
        "returns": "text",
    },
    "get_execution_status": {
        "func": get_execution_status,
        "schema": _GET_EXECUTION_STATUS_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "list_recent_executions": {
        "func": list_recent_executions,
        "schema": _LIST_RECENT_EXECUTIONS_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "cancel_execution": {
        "func": cancel_execution,
        "schema": _CANCEL_EXECUTION_SCHEMA,
        "requires_approval": True,
        "returns": "text",
    },
    "list_projects": {
        "func": list_projects,
        "schema": _LIST_PROJECTS_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "get_project": {
        "func": get_project,
        "schema": _GET_PROJECT_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "create_project": {
        "func": create_project,
        "schema": _CREATE_PROJECT_SCHEMA,
        "requires_approval": True,
        "returns": "text",
    },
    "list_project_members": {
        "func": list_project_members,
        "schema": _LIST_PROJECT_MEMBERS_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "list_connections": {
        "func": list_connections,
        "schema": _LIST_CONNECTIONS_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "get_connection": {
        "func": get_connection,
        "schema": _GET_CONNECTION_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "test_connection": {
        "func": test_connection,
        "schema": _TEST_CONNECTION_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "list_webhooks": {
        "func": list_webhooks,
        "schema": _LIST_WEBHOOKS_SCHEMA,
        "requires_approval": False,
        "returns": "text",
    },
    "trigger_webhook_manually": {
        "func": trigger_webhook_manually,
        "schema": _TRIGGER_WEBHOOK_MANUALLY_SCHEMA,
        "requires_approval": True,
        "returns": "text",
    },
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    entry["schema"] for entry in TOOL_REGISTRY.values()
]


def requires_approval(tool_name: str) -> bool:
    """Retorna True se a tool requer aprovacao humana antes da execucao."""
    entry = TOOL_REGISTRY.get(tool_name)
    return entry is not None and entry["requires_approval"]


async def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    db: AsyncSession,
    user_context: UserContext,
) -> str:
    """Dispatcher central. Converte AgentToolError em string formatada para o LLM."""
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return f"Tool desconhecida: '{name}'. Tools disponiveis: {', '.join(TOOL_REGISTRY)}"
    try:
        return await entry["func"](db=db, ctx=user_context, **arguments)
    except AgentPermissionError as exc:
        return f"Permissao negada: {exc}"
    except AgentValidationError as exc:
        return f"Argumentos invalidos: {exc}"
    except AgentNotFoundError as exc:
        return f"Nao encontrado: {exc}"
    except AgentToolError as exc:
        return f"Erro: {exc}"
