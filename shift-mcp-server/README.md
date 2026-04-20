# shift-mcp-server

Servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io) que expõe o **Platform Agent** do Shift para clientes como Claude Desktop, Cursor, n8n, ou qualquer outro runtime compatível. Ele é uma ponte fina: autentica via **API key Bearer**, consulta o backend Shift (`/agent-mcp/*`) e serve dinamicamente as tools permitidas por aquela chave.

## Arquitetura em 3 caixas

```
+------------------+     stdio / http     +---------------------+    Bearer key    +--------------+
|  MCP client      | <------------------> |  shift-mcp-server   | <--------------> |  Shift API   |
|  (Claude, n8n)   |                      |  (este pacote)      |                  | /agent-mcp/* |
+------------------+                      +---------------------+                  +--------------+
```

- O backend mantém o **tool registry**, faz enforcement de permissões, gera **audit log** (`source="mcp"`) e orquestra **aprovações humanas**.
- Este servidor só traduz protocolos (MCP ↔ REST) e faz polling de aprovações.

## Instalação

```bash
cd shift-mcp-server
pip install -e .
# ou para dev:
pip install -e '.[dev]'
```

## Configuração

Copie `.env.example` para `.env` e preencha:

```bash
SHIFT_BACKEND_URL=https://shift.example.com/api/v1
SHIFT_API_KEY=sk_shift_<plaintext-da-chave>
SHIFT_MCP_TRANSPORT=stdio          # ou streamable-http
```

Gere a chave no Shift em **Espaço → API Keys → Criar** (role MANAGER no workspace). O plaintext aparece **uma única vez** — copie para o `.env` imediatamente.

## Uso

### 1. Testar a chave

```bash
shift-mcp-server validate
# OK — api_key_id=... workspace=... tools=[...] approval=True
```

### 2. Rodar stdio (Claude Desktop)

```bash
shift-mcp-server run --transport stdio
```

Em `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) ou `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "shift": {
      "command": "shift-mcp-server",
      "args": ["run", "--transport", "stdio"],
      "env": {
        "SHIFT_BACKEND_URL": "https://shift.example.com/api/v1",
        "SHIFT_API_KEY": "sk_shift_..."
      }
    }
  }
}
```

### 3. Rodar HTTP (n8n / integrações remotas)

```bash
shift-mcp-server run --transport streamable-http --host 0.0.0.0 --port 8765
```

O endpoint MCP fica em `POST http://<host>:8765/mcp`. Em n8n, adicione um nó *MCP Client* apontando para essa URL.

### 4. Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
EXPOSE 8765
ENV SHIFT_MCP_TRANSPORT=streamable-http
ENV SHIFT_MCP_HOST=0.0.0.0
CMD ["shift-mcp-server", "run"]
```

```bash
docker build -t shift-mcp .
docker run --rm -p 8765:8765 \
  -e SHIFT_BACKEND_URL=https://shift.example.com/api/v1 \
  -e SHIFT_API_KEY=sk_shift_... \
  shift-mcp
```

## Fluxo de aprovação

Tools destrutivas (`execute_workflow`, `cancel_execution`, `create_project`, `trigger_webhook_manually`) exigem aprovação humana por padrão.

1. O cliente MCP chama a tool.
2. O servidor chama `POST /agent-mcp/execute`.
3. Backend cria um `AgentApproval` (status=pending) e retorna `approval_id`.
4. O servidor **pollea** `GET /agent-mcp/approvals/{id}` a cada `SHIFT_MCP_APPROVAL_POLL_INTERVAL` segundos.
5. Quando um humano aprova na UI do Shift, o servidor reexecuta com `approval_id` e retorna o resultado.
6. Em timeout, rejeição ou expiração, o servidor devolve uma mensagem textual ao cliente — **nunca** executa sem aprovação.

Opt-out: se a chave foi criada com `require_human_approval=false`, o backend executa direto. Use apenas para automações de confiança (ex.: n8n dedicado a jobs noturnos).

## Auditoria

Todo `/execute` grava uma linha em `agent_audit_log` com `metadata.source="mcp"` + `api_key_id`. Use a UI de auditoria (`/espaço/<ws>/agent-audit`) ou consulta direta:

```sql
SELECT created_at, tool_name, status, log_metadata->>'api_key_id'
FROM agent_audit_log
WHERE log_metadata->>'source' = 'mcp'
ORDER BY created_at DESC;
```

## Testes

```bash
pip install -e '.[dev]'
pytest
```

## Troubleshooting

- **`Configuracao invalida: ...`** — uma variável obrigatória está faltando. Veja `.env.example`.
- **`401 Chave invalida, revogada ou expirada`** — a chave foi revogada no painel, ou a flag `AGENT_ENABLED` está `false` no backend.
- **`403 Tool fora do allowed_tools`** — a chave não autoriza aquela tool; edite em API Keys ou use outra chave.
- **Aprovação nunca chega** — verifique a UI do Shift; o thread sintético aparece no painel de aprovações com título `MCP: <nome-da-chave>`.

## Licença

Proprietário — uso interno do Shift.
