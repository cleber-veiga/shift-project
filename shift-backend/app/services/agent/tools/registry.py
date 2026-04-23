"""
Registry unificado das tools do Platform Agent.

Este modulo e o ponto de integracao com o grafo LangGraph (Fase 2).
Expoe TOOL_SCHEMAS (formato OpenAI function calling), TOOL_REGISTRY
(metadados + funcao), requires_approval() e execute_tool() dispatcher.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

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
from app.services.agent.tools.workflow_pending_tools import (
    pending_add_edge,
    pending_add_node,
    pending_remove_node,
    pending_set_io_schema,
    pending_set_variables,
    pending_update_node,
)
from app.services.agent.tools.workflow_write_tools import (
    add_edge,
    add_node,
    create_workflow,
    remove_edge,
    remove_node,
    set_workflow_variables,
    update_node_config,
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
# Schemas — tools de escrita de workflow
# ---------------------------------------------------------------------------

_CREATE_WORKFLOW_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_workflow",
        "description": (
            "Cria um workflow vazio (status draft) em um projeto. "
            "Operacao destrutiva — exige aprovacao humana antes de criar. "
            "Requer role CONSULTANT no workspace e EDITOR no projeto. "
            "Retorna o workflow_id do workflow criado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID do projeto onde o workflow sera criado",
                },
                "name": {
                    "type": "string",
                    "description": "Nome do workflow (1 a 255 caracteres)",
                },
                "description": {
                    "type": "string",
                    "description": "Descricao opcional do workflow",
                },
            },
            "required": ["project_id", "name"],
        },
    },
}

_ADD_NODE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "add_node",
        "description": (
            "Adiciona um novo no ao workflow. "
            "Operacao destrutiva — exige aprovacao humana. "
            "O node_type deve ser um tipo registrado no engine (ex: sql_script, "
            "mapper_node, filter_node, bulk_insert, loop, if_node). "
            "Retorna o node_id gerado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
                "node_type": {
                    "type": "string",
                    "description": "Tipo do no (ex: sql_script, mapper_node, filter_node)",
                },
                "position": {
                    "type": "object",
                    "description": "Posicao visual do no no canvas: {x: number, y: number}",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                    "required": ["x", "y"],
                },
                "config": {
                    "type": "object",
                    "description": "Configuracao inicial do no (campo data). Opcional.",
                },
            },
            "required": ["workflow_id", "node_type", "position"],
        },
    },
}

_UPDATE_NODE_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_node_config",
        "description": (
            "Atualiza parcialmente a configuracao (campo data) de um no existente. "
            "Operacao destrutiva — exige aprovacao humana. "
            "O config_patch e mesclado (shallow merge) com a config existente. "
            "Use get_workflow para inspecionar a config atual antes de alterar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
                "node_id": {
                    "type": "string",
                    "description": "ID do no a atualizar (ex: node_abc123)",
                },
                "config_patch": {
                    "type": "object",
                    "description": "Campos a mesclar na config do no",
                },
            },
            "required": ["workflow_id", "node_id", "config_patch"],
        },
    },
}

_REMOVE_NODE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "remove_node",
        "description": (
            "Remove um no e TODAS as arestas conectadas a ele do workflow. "
            "Operacao destrutiva e irreversivel — exige aprovacao humana. "
            "Retorna a lista de edge_ids removidos em cascata."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
                "node_id": {
                    "type": "string",
                    "description": "ID do no a remover",
                },
            },
            "required": ["workflow_id", "node_id"],
        },
    },
}

_ADD_EDGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "add_edge",
        "description": (
            "Conecta dois nos existentes com uma aresta direcional. "
            "Operacao destrutiva — exige aprovacao humana. "
            "source_id e target_id devem ser node_ids validos no workflow. "
            "Retorna o edge_id gerado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
                "source_id": {
                    "type": "string",
                    "description": "ID do no de origem",
                },
                "target_id": {
                    "type": "string",
                    "description": "ID do no de destino",
                },
                "source_handle": {
                    "type": "string",
                    "description": "Handle de saida do no fonte (opcional, ex: 'true', 'false')",
                },
                "target_handle": {
                    "type": "string",
                    "description": "Handle de entrada do no destino (opcional)",
                },
            },
            "required": ["workflow_id", "source_id", "target_id"],
        },
    },
}

_REMOVE_EDGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "remove_edge",
        "description": (
            "Remove uma aresta especifica do workflow pelo seu edge_id. "
            "Operacao destrutiva — exige aprovacao humana. "
            "Use get_workflow para descobrir os edge_ids existentes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
                "edge_id": {
                    "type": "string",
                    "description": "ID da aresta a remover (ex: edge_abc123)",
                },
            },
            "required": ["workflow_id", "edge_id"],
        },
    },
}

_SET_WORKFLOW_VARIABLES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_workflow_variables",
        "description": (
            "Substitui integralmente a lista de variaveis do workflow. "
            "Operacao destrutiva — exige aprovacao humana. "
            "Tipos validos: string, number, integer, boolean, object, array. "
            "Retorna o numero de variaveis configuradas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID do workflow",
                },
                "variables": {
                    "type": "array",
                    "description": "Lista completa de variaveis do workflow",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nome da variavel"},
                            "type": {
                                "type": "string",
                                "enum": ["string", "number", "integer", "boolean", "object", "array"],
                                "description": "Tipo da variavel",
                            },
                            "required": {"type": "boolean", "description": "Se e obrigatoria"},
                            "default": {"description": "Valor padrao (opcional)"},
                            "description": {"type": "string", "description": "Descricao opcional"},
                        },
                        "required": ["name", "type"],
                    },
                },
            },
            "required": ["workflow_id", "variables"],
        },
    },
}

# ---------------------------------------------------------------------------
# Schemas — pending build tools (FASE 5)
# ---------------------------------------------------------------------------

_PENDING_ADD_NODE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "pending_add_node",
        "description": (
            "Adiciona um no pendente a sessao de build ativa. "
            "Nao exige aprovacao humana — o usuario aprova tudo de uma vez no confirm. "
            "temp_id deve ser unico por sessao e referenciado em pending_add_edge."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "UUID da build session"},
                "temp_id": {
                    "type": "string",
                    "description": "Identificador temporario unico (ex: 'n_filter1'). Usado para referenciar o no em pending_add_edge.",
                },
                "node_type": {
                    "type": "string",
                    "description": "Tipo do no (ex: sql_script, filter, mapper, bulk_insert, if_node, loop)",
                },
                "label": {"type": "string", "description": "Rotulo do no"},
                "config": {
                    "type": "object",
                    "description": "Configuracao inicial do no (opcional)",
                },
                "position": {
                    "type": "object",
                    "description": "Posicao visual {x, y} — omitir para auto-layout",
                    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                },
            },
            "required": ["session_id", "temp_id", "node_type", "label"],
        },
    },
}

_PENDING_ADD_EDGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "pending_add_edge",
        "description": (
            "Conecta dois nos pendentes pelo temp_id de cada um. "
            "source_temp_id e target_temp_id devem ter sido criados por pending_add_node na mesma sessao."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "UUID da build session"},
                "source_temp_id": {"type": "string", "description": "temp_id do no de origem"},
                "target_temp_id": {"type": "string", "description": "temp_id do no de destino"},
                "source_handle": {
                    "type": "string",
                    "description": "Handle de saida (ex: 'success', 'failure', 'true', 'false'). Opcional.",
                },
                "target_handle": {
                    "type": "string",
                    "description": "Handle de entrada do destino. Opcional.",
                },
            },
            "required": ["session_id", "source_temp_id", "target_temp_id"],
        },
    },
}

_PENDING_UPDATE_NODE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "pending_update_node",
        "description": (
            "Aplica patch shallow na configuracao de um no pendente. "
            "Util para corrigir ou completar config de um no antes do confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "UUID da build session"},
                "temp_id": {"type": "string", "description": "temp_id do no a atualizar"},
                "config_patch": {
                    "type": "object",
                    "description": "Campos a mesclar na config do no",
                },
            },
            "required": ["session_id", "temp_id", "config_patch"],
        },
    },
}

_PENDING_REMOVE_NODE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "pending_remove_node",
        "description": (
            "Remove um no pendente e suas arestas conectadas da sessao de build. "
            "Util para descartar nos adicionados por engano antes do confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "UUID da build session"},
                "temp_id": {"type": "string", "description": "temp_id do no a remover"},
            },
            "required": ["session_id", "temp_id"],
        },
    },
}

_PENDING_SET_VARIABLES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "pending_set_variables",
        "description": (
            "Define variaveis do workflow a serem aplicadas quando o build for confirmado. "
            "Substitui integralmente a lista de variaveis pendentes da sessao."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "UUID da build session"},
                "variables": {
                    "type": "array",
                    "description": "Lista completa de variaveis",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [
                                    "string",
                                    "number",
                                    "integer",
                                    "boolean",
                                    "object",
                                    "array",
                                    "connection",
                                    "file_upload",
                                    "secret",
                                ],
                            },
                            "required": {"type": "boolean"},
                            "default": {},
                            "description": {"type": "string"},
                            "connection_type": {
                                "type": "string",
                                "enum": [
                                    "postgres",
                                    "mysql",
                                    "sqlserver",
                                    "oracle",
                                    "mongodb",
                                ],
                                "description": (
                                    "Obrigatorio quando type='connection'; indica o "
                                    "driver esperado em tempo de execucao."
                                ),
                            },
                        },
                        "required": ["name", "type"],
                    },
                },
            },
            "required": ["session_id", "variables"],
        },
    },
}

_PENDING_SET_IO_SCHEMA_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "pending_set_io_schema",
        "description": (
            "Define o Schema de I/O (inputs/outputs) do subfluxo sendo construido. "
            "Necessario para que o workflow possa ser chamado como sub-workflow via "
            "call_workflow e para que o runtime valide as entradas no disparo. "
            "Os parametros seguem o shape WorkflowParam e geralmente espelham as "
            "variaveis definidas via pending_set_variables (nome, tipo, required)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "UUID da build session"},
                "inputs": {
                    "type": "array",
                    "description": "Lista de parametros de entrada do subfluxo",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [
                                    "string",
                                    "integer",
                                    "number",
                                    "boolean",
                                    "object",
                                    "array",
                                    "table_reference",
                                    "connection",
                                    "file_upload",
                                    "secret",
                                ],
                            },
                            "required": {"type": "boolean"},
                            "default": {},
                            "description": {"type": "string"},
                            "connection_type": {
                                "type": "string",
                                "enum": [
                                    "postgres",
                                    "mysql",
                                    "sqlserver",
                                    "oracle",
                                    "mongodb",
                                ],
                            },
                        },
                        "required": ["name", "type"],
                    },
                },
                "outputs": {
                    "type": "array",
                    "description": "Lista de parametros de saida do subfluxo",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [
                                    "string",
                                    "integer",
                                    "number",
                                    "boolean",
                                    "object",
                                    "array",
                                    "table_reference",
                                    "connection",
                                    "file_upload",
                                    "secret",
                                ],
                            },
                            "required": {"type": "boolean"},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "type"],
                    },
                },
            },
            "required": ["session_id"],
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
    # --- write tools ---
    "create_workflow": {
        "func": create_workflow,
        "schema": _CREATE_WORKFLOW_SCHEMA,
        "requires_approval": True,
        "is_write": True,
        "returns": "json",
    },
    "add_node": {
        "func": add_node,
        "schema": _ADD_NODE_SCHEMA,
        "requires_approval": True,
        "is_write": True,
        "returns": "json",
    },
    "update_node_config": {
        "func": update_node_config,
        "schema": _UPDATE_NODE_CONFIG_SCHEMA,
        "requires_approval": True,
        "is_write": True,
        "returns": "json",
    },
    "remove_node": {
        "func": remove_node,
        "schema": _REMOVE_NODE_SCHEMA,
        "requires_approval": True,
        "is_write": True,
        "returns": "json",
    },
    "add_edge": {
        "func": add_edge,
        "schema": _ADD_EDGE_SCHEMA,
        "requires_approval": True,
        "is_write": True,
        "returns": "json",
    },
    "remove_edge": {
        "func": remove_edge,
        "schema": _REMOVE_EDGE_SCHEMA,
        "requires_approval": True,
        "is_write": True,
        "returns": "json",
    },
    "set_workflow_variables": {
        "func": set_workflow_variables,
        "schema": _SET_WORKFLOW_VARIABLES_SCHEMA,
        "requires_approval": True,
        "is_write": True,
        "returns": "json",
    },
    # --- pending build tools (FASE 5) ---
    "pending_add_node": {
        "func": pending_add_node,
        "schema": _PENDING_ADD_NODE_SCHEMA,
        "requires_approval": False,
        "is_pending": True,
        "returns": "json",
    },
    "pending_add_edge": {
        "func": pending_add_edge,
        "schema": _PENDING_ADD_EDGE_SCHEMA,
        "requires_approval": False,
        "is_pending": True,
        "returns": "json",
    },
    "pending_update_node": {
        "func": pending_update_node,
        "schema": _PENDING_UPDATE_NODE_SCHEMA,
        "requires_approval": False,
        "is_pending": True,
        "returns": "json",
    },
    "pending_remove_node": {
        "func": pending_remove_node,
        "schema": _PENDING_REMOVE_NODE_SCHEMA,
        "requires_approval": False,
        "is_pending": True,
        "returns": "json",
    },
    "pending_set_variables": {
        "func": pending_set_variables,
        "schema": _PENDING_SET_VARIABLES_SCHEMA,
        "requires_approval": False,
        "is_pending": True,
        "returns": "json",
    },
    "pending_set_io_schema": {
        "func": pending_set_io_schema,
        "schema": _PENDING_SET_IO_SCHEMA_SCHEMA,
        "requires_approval": False,
        "is_pending": True,
        "returns": "json",
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
    thread_id: UUID | None = None,
) -> str:
    """Dispatcher central. Converte AgentToolError em string formatada para o LLM.

    thread_id e repassado apenas para write tools (is_write=True) para que
    gravem before/after em agent_audit_log.
    """
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return f"Tool desconhecida: '{name}'. Tools disponiveis: {', '.join(TOOL_REGISTRY)}"
    extra: dict[str, Any] = {}
    if entry.get("is_write") and thread_id is not None:
        extra["thread_id"] = thread_id
    try:
        return await entry["func"](db=db, ctx=user_context, **arguments, **extra)
    except AgentPermissionError as exc:
        return f"Permissao negada: {exc}"
    except AgentValidationError as exc:
        return f"Argumentos invalidos: {exc}"
    except AgentNotFoundError as exc:
        return f"Nao encontrado: {exc}"
    except AgentToolError as exc:
        return f"Erro: {exc}"
