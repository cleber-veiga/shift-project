# Agente Shift — Como Funciona

> Documento de funcionamento da plataforma AI-native do Shift.
> Cobre as 8 fases (0–7) implementadas: do banco de dados à UI, passando por tools, StateGraph, segurança e MCP externo.

---

## 1. Visão geral em uma página

O Shift ganhou um **Agente de Plataforma**: um assistente com IA que entende o sistema inteiro (workflows, conexões, projetos, webhooks) e pode **ler E agir** sobre ele — sempre respeitando as permissões do usuário que está falando com ele.

Ele opera em **dois modos de entrada**:

1. **Painel lateral direito** dentro do próprio Shift — o usuário logado conversa com o agente, que enxerga o contexto da tela atual.
2. **API / MCP externo** — ferramentas como Claude Desktop, n8n ou scripts podem se conectar via MCP usando uma **API Key** emitida pelo projeto.

Por baixo, o fluxo é o mesmo: uma **LangGraph StateGraph** com 6 nós (guardrails → intent → planner → approval → executor → report), persistência via Postgres checkpointer (HITL), sanitização obrigatória de entrada e saída, e budgets de mensagem/tokens por thread.

O antigo Assistente SQL do Playground **continua existindo e inalterado** — ele é especialista em SQL read-only contra uma conexão. O novo agente é o "motor" que opera a plataforma toda.

---

## 2. Arquitetura em camadas

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                          │
│  ┌─────────────────┐  ┌──────────────────────────────────┐   │
│  │ Painel lateral  │  │ /ai (full-screen)                │   │
│  │ AIPanel         │  │ AIContextProvider + context hook │   │
│  └────────┬────────┘  └────────────┬─────────────────────┘   │
│           │                        │                         │
│           └──────────┬─────────────┘                         │
│                      │ SSE (text/event-stream)               │
└──────────────────────┼───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│  Backend FastAPI                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  /api/v1/agent/chat   /agent/threads   /agent-mcp/*    │  │
│  └───────────┬────────────────────────────┬───────────────┘  │
│              │                            │                  │
│  ┌───────────▼───────────────┐  ┌─────────▼─────────────┐    │
│  │ LangGraph StateGraph      │  │ API Key auth          │    │
│  │  guardrails → intent      │  │ (Argon2, whitelist)   │    │
│  │  → planner → approval     │  └───────────────────────┘    │
│  │  → executor → report      │                               │
│  └───────────┬───────────────┘                               │
│              │                                               │
│  ┌───────────▼────────────┐  ┌─────────────────────────┐     │
│  │ Tools Layer (15 tools) │  │ Services existentes     │     │
│  │ + UserContext          │──▶│ workflow/project/...    │     │
│  └────────────────────────┘  └─────────────────────────┘     │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Postgres (checkpointer + ai_*_threads + audit)         │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                       ▲
                       │ MCP (stdio/HTTP)
┌──────────────────────┴───────────────────────────────────────┐
│ shift-mcp-server (pacote standalone)                         │
│ Claude Desktop / n8n / scripts                               │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Fluxo de uma pergunta ponta a ponta

Suponha que o usuário (role CLIENT no projeto) esteja na tela de um workflow e pergunte no painel:

> *"Executa esse workflow com o payload padrão."*

Passo a passo:

1. **Frontend captura o contexto.**
   O `AIContextProvider` expõe o hook `useRegisterAIContext` que a página do workflow usou para registrar `{ kind: "workflow", workflowId, workflowName, ... }`. Esse contexto vai junto no payload da mensagem.

2. **POST `/api/v1/agent/chat`** com `thread_id` (cria uma se ausente), `message`, `context`.

3. **Guardrails (nó 1)**
   - `sanitize_user_input` remove/encapsula padrões de prompt injection conhecidos (`IGNORE ALL PREVIOUS INSTRUCTIONS`, tags `<tool_call>`, `[INST]`, persona reassignments, etc).
   - Valida tamanho, caracteres de controle, tokens especiais.

4. **Intent (nó 2)**
   - LLM classifica a intenção: *navigation*, *inspection*, *execution*, *mutation*.
   - Aqui seria: `execution` (executar workflow).

5. **Planner (nó 3)**
   - LLM propõe um plano: `execute_workflow(id=<uuid>, payload={})`.
   - O plano passa pelo `UserContext.check_permission` — o planner só pode propor tools que o usuário **tem permissão** de executar.

6. **Approval (nó 4)**
   - Toda ação **destrutiva/de execução** força `interrupt()` do LangGraph.
   - O estado é persistido no `PostgresSaver` (checkpointer).
   - Frontend recebe evento SSE `approval_required` com diff/resumo → usuário clica "Aprovar" ou "Cancelar".
   - Ao aprovar, outro POST retoma a execução pelo mesmo `thread_id`.

7. **Executor (nó 5)**
   - **Re-valida** permissões (defense-in-depth — um prompt injection que tenha sobrevivido ao planner não consegue escalar aqui).
   - Debita budget (mensagens + tokens + contador destrutivo).
   - Chama a tool real, que internamente usa os services existentes (`workflow_service.execute(...)`).
   - Tool result passa por `sanitize_tool_output` (encapsula em `<tool_result>` com delimitadores — previne que metadados do resultado injetem instruções novas).

8. **Report (nó 6)**
   - LLM redige resposta final em linguagem natural.
   - Stream SSE de tokens para o painel.
   - Registro no `ai_agent_audit_log`: quem, o quê, quando, tool_call_id, aprovador.

Se o budget estourar em qualquer ponto → HTTP 429 com `Retry-After`, thread marcada como "budget exhausted", auditoria registrada.

---

## 4. O que o agente sabe fazer (Tools Layer)

Foram expostos **15 tools**, agrupados por categoria. Cada tool tem schema JSON e validação de permissão embutida.

### Workflow
- `list_workflows` — lista do projeto com filtros
- `get_workflow_details` — detalhes + nós + última execução
- `execute_workflow` ⚠️ destrutivo — requer approval
- `list_executions` — histórico
- `get_execution_details` — logs, dead-letters, duração

### Project
- `list_projects` — projetos visíveis ao usuário
- `get_project_details`
- `list_project_members`

### Connection
- `list_connections`
- `get_connection_details` — **sem credenciais**, só metadados
- `test_connection` — valida conectividade

### Webhook
- `list_webhooks`
- `get_webhook_details` — URLs de test/prod
- `list_webhook_executions`

### Utilitários
- `search_global` — busca cross-entity

**Nota:** tools read-only **não** passam pelo nó de approval. Só mutações/execuções.

---

## 5. Frontend — como o painel "sabe onde está"

O segredo é o `AIContextProvider` em [app/(private)/layout.tsx](https://github.com/cleber-veiga/shift-project/blob/main/shift-frontend/app/%28private%29/layout.tsx).

Cada página que quer contribuir para o contexto usa:

```tsx
useRegisterAIContext({
  kind: "workflow",
  workflowId: id,
  workflowName: name,
  // tokenRef previne updates stale
})
```

O provider mantém uma **pilha de contextos ativos** (entrando/saindo de rotas) e envia o contexto do topo junto com cada mensagem. Isso permite perguntas como:

- Na tela de um workflow: *"executa esse"* → o agente sabe qual.
- Na tela de conexões: *"testa as que estão com erro"* → o agente sabe o escopo.
- Em `/ai` (full-screen): sem contexto de página, funciona como chat geral.

O painel é **push, não overlay** — o conteúdo da página encolhe, não é coberto. Isso preserva as ferramentas visuais do Shift enquanto o usuário conversa.

---

## 6. Segurança — camadas

| Camada | Onde | O quê |
|--------|------|-------|
| **Input sanitization** | `sanitize_user_input` (nó guardrails) | Remove/encapsula padrões de injection, limita tamanho |
| **Output sanitization** | `sanitize_tool_output` | Encapsula resultados de tools em `<tool_result>` para impedir que dados vindos do banco virem instruções |
| **Permission re-check** | UserContext no executor | Valida de novo, mesmo após planner ter aprovado |
| **HITL approval** | `interrupt()` antes de mutação/execução | Usuário humano confirma antes de agir |
| **Budget** | `budget_service` | Mensagens/tokens por thread, contador de destrutivas |
| **Rate limit** | slowapi (sliding window) | Por IP + por user |
| **API Key scope** | `allowed_tools` whitelist | MCP externo só acessa tools listadas na key |
| **Argon2** | Hash das API keys | Plaintext mostrado **uma única vez** na criação |
| **Expiração** | APScheduler job | Keys e threads com TTL são revogadas automaticamente |
| **Audit log** | `ai_agent_audit_log` | Toda tool_call registrada: quem, quando, aprovado por quem |

Cobertura garantida por `tests/integration/test_injection_attacks.py` (7 cenários + extras).

---

## 7. MCP externo — Claude Desktop, n8n, scripts

### Como emitir uma API Key

1. Ir em **Projeto → Chaves de API** (menu lateral, visível para roles MANAGER+).
2. **Nova chave** → nome, expiração (30/60/90 dias ou nunca), escolher tools permitidos (whitelist por categoria, wildcard `"*"` possível).
3. Dialog mostra o plaintext **uma única vez** (`shk_<...>`). Copiar e guardar — não há "ver depois".
4. Revogar a qualquer momento (lista mostra prefix, status, último uso).

### Como conectar

O pacote `shift-mcp-server` (publicado separadamente) expõe o agente via MCP stdio/HTTP. Config típica no Claude Desktop:

```json
{
  "mcpServers": {
    "shift": {
      "command": "npx",
      "args": ["-y", "shift-mcp-server"],
      "env": {
        "SHIFT_API_URL": "https://shift.viasoft.com.br",
        "SHIFT_API_KEY": "shk_..."
      }
    }
  }
}
```

Requisições caem em `/api/v1/agent-mcp/*`, autenticadas via API Key (Argon2 hash check), passam pelo **mesmo StateGraph**, respeitam whitelist de tools da key, e contam no audit log com `source=api_key:<id>`.

---

## 8. Persistência — o que está no Postgres

4 tabelas novas:

- `ai_agent_threads` — sessões de conversa (user, workspace, context, status, budget usado).
- `ai_agent_messages` — histórico de mensagens da thread (para retomada e auditoria).
- `ai_agent_audit_log` — toda tool_call: timing, input/output (sanitizados), aprovador.
- `agent_api_keys` — keys para MCP externo (hash, prefix, allowed_tools, expires_at, revoked_at, last_used_at).

Além disso, a tabela `checkpoints` do `langgraph-checkpoint-postgres` guarda o estado do StateGraph **a cada nó** — é isso que permite retomar após `interrupt()` de approval horas depois.

---

## 9. Operação — flags, configs e monitoramento

| Flag / env | Efeito |
|------------|--------|
| `AGENT_ENABLED` | Liga/desliga a feature inteira |
| `LLM_API_KEY`, `LLM_MODEL` | Modelo principal (LiteLLM) |
| `LLM_REASONING_MODEL`, `LLM_REASONING_EFFORT` | Modelo para deep reasoning (opcional) |
| `MESSAGE_BUDGET_HARD_CAP`, `TOKEN_BUDGET_HARD_CAP` | Caps por thread |
| `AGENT_RATE_LIMIT_*` | slowapi config |
| `AGENT_KEY_DEFAULT_TTL_DAYS` | TTL default para novas keys |

Jobs em background (APScheduler):
- **expire-keys** — revoga API keys expiradas a cada N minutos.
- **expire-threads** — marca threads inativas como expiradas (libera budget).

Endpoints de audit em `/api/v1/agent/audit/*` consumidos pela UI administrativa.

---

## 10. O que NÃO foi feito (por decisão)

- Assistente SQL **não foi migrado** para o StateGraph — continua como está no Playground.
- Sem edição de API keys (padrão de secrets: só criar e revogar).
- Sem export/import de threads.
- Sem fuzzing automatizado de prompts (suite de injection cobre os padrões conhecidos).

---

## 11. Próximos passos naturais

1. **QA em staging** com usuários reais dos três níveis (Owner/Manager/Client).
2. **Dogfooding interno** — time de suporte usando o Claude Desktop via MCP para responder tickets.
3. Métricas: quantas threads/dia, % aprovadas, tool_calls mais usadas, budget estourado.
4. Iterar tools conforme padrão de uso — provavelmente faltam 2-3 tools específicas que só aparecem em uso real.

---

*Versão do doc: 2026-04-20. Referência: fases 0–7 implementadas e revisadas via suite de integration tests.*
