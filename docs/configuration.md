# Configuração — variáveis de ambiente

Este documento é o **ponto de entrada único** para entender qual arquivo
`.env*` editar em cada situação. Cada arquivo `.env.example` no repo tem
um cabeçalho curto que aponta de volta para cá.

## Mapa de arquivos

| Arquivo | Audiência | Lido por | Arquivo real (gitignore) |
|---|---|---|---|
| [`.env.example`](../.env.example) | Dev Shift | `docker compose up` na raiz | `.env` |
| [`.env.build.example`](../.env.build.example) | Cleber / CI | `scripts/build-and-publish.sh` | `.env.build` |
| [`shift-backend/.env.example`](../shift-backend/.env.example) | Dev Shift | `uvicorn` standalone (sem Docker) | `shift-backend/.env` |
| [`shift-frontend/.env.example`](../shift-frontend/.env.example) | Dev Shift | `pnpm dev` standalone | `shift-frontend/.env` ou `.env.local` |
| [`tester-package/.env.example`](../tester-package/.env.example) | Tester / cliente do produto | `docker compose up` no pacote zipado | `tester-package/.env` |
| [`shift-mcp-server/.env.example`](../shift-mcp-server/.env.example) | Cliente final do MCP | Claude Desktop, n8n, etc. | `shift-mcp-server/.env` |

## Qual eu uso?

**Sou dev da Shift e quero rodar o stack completo localmente:**
→ `.env.example` (raiz). Copie para `.env`, ajuste `DATABASE_URL`, suba com `docker compose up`.

**Sou dev da Shift e quero debugar só o backend (sem Docker):**
→ `shift-backend/.env.example`. Copie para `shift-backend/.env`, rode `uvicorn main:app --reload`.

**Sou dev da Shift e quero debugar só o frontend:**
→ `shift-frontend/.env.example`. Copie para `shift-frontend/.env.local`, rode `pnpm dev`.

**Sou o Cleber e vou publicar uma nova versão no Docker Hub:**
→ `.env.build.example`. Copie para `.env.build`, preencha as chaves oficiais (Anthropic, Google, Resend, LangSmith), rode `bash scripts/build-and-publish.sh`. Ver [`BUILD-AND-PUBLISH.md`](../BUILD-AND-PUBLISH.md).

**Sou tester / cliente recebendo o produto:**
→ `tester-package/.env.example`. Copie para `.env`, preencha apenas `DATABASE_URL`. Ver [`tester-package/README.md`](../tester-package/README.md).

**Sou cliente final integrando o MCP server com Claude Desktop / n8n:**
→ `shift-mcp-server/.env.example`. Copie para `.env`, preencha `SHIFT_BACKEND_URL` e `SHIFT_API_KEY`.

## Hierarquia de fontes (apenas backend)

O backend (Pydantic Settings) lê variáveis nesta ordem (mais forte → mais fraco):

1. **Variável de ambiente explícita** — override consciente, dev local
2. **`/shift-secrets/secrets.env`** — auto-gerado no primeiro `up`, único por instalação (SECRET_KEY, ENCRYPTION_KEY)
3. **`/etc/shift/embedded.env`** — embutido na imagem no build (LLM_API_KEY, GOOGLE_CLIENT_ID, RESEND_API_KEY, LANGSMITH_API_KEY)
4. **`.env`** — usado em dev standalone (uvicorn fora do Docker)
5. **Defaults** definidos em `app/core/config.py`

Implementação em [shift-backend/app/core/config.py](../shift-backend/app/core/config.py).

## Segredos auto-gerados

`SECRET_KEY` (JWT) e `ENCRYPTION_KEY` (Fernet) são geradas automaticamente
no primeiro boot pelo `bootstrap-secrets.py` e persistidas no volume Docker
nomeado `shift_secrets` (montado em `/shift-secrets`).

- **Não precisa gerar manualmente** em produção (Docker).
- **Em dev standalone** (uvicorn fora do Docker), gerar uma vez e colar
  em `shift-backend/.env`. Comandos no template.
- **NUNCA apagar o volume `shift_secrets`** (`docker compose down -v`)
  em produção sem antes ter feito backup das connections — a
  `ENCRYPTION_KEY` é a única coisa que decifra as senhas armazenadas.

## Segredos embutidos na imagem

`LLM_API_KEY`, `GOOGLE_CLIENT_ID`, `RESEND_API_KEY`, `LANGSMITH_API_KEY` e
`EMAIL_FROM` são **iguais para todos os clientes** (são chaves da Shift).
São injetadas no build via `--build-arg` e gravadas em
`/etc/shift/embedded.env` dentro da imagem.

- **Cliente nunca vê nem edita** essas chaves.
- **Cleber edita uma vez** em `.env.build` (não commitado).
- **Para rotacionar**: novo build com chave nova, push, cliente faz
  `docker compose pull && up -d`.

Detalhes em [BUILD-AND-PUBLISH.md](../BUILD-AND-PUBLISH.md).

## Modelos de IA

A Shift oferece três modos de uso de LLM, com configuração distinta:

| Feature | Variável | Onde fica | Quando setar |
|---|---|---|---|
| SQL Assistant (chat padrão) | `LLM_MODEL` | hardcoded no `docker-compose.yml` | Trocar via PR — decisão de produto |
| SQL Assistant — chave do provider | `LLM_API_KEY` | `.env.build` → `/etc/shift/embedded.env` | Build da imagem |
| **Modo "Pensamento profundo"** | `LLM_REASONING_MODEL` | `.env.build` → `/etc/shift/embedded.env` | Build da imagem |
| Platform Agent | `AGENT_LLM_MODEL` | hardcoded no `docker-compose.yml` | Trocar via PR |
| Platform Agent — liga/desliga | `AGENT_ENABLED` | `.env` (default `false`) | Por instalação |
| Endpoint custom (Ollama, etc) | `LLM_BASE_URL` | default `None` | Apenas em dev local com `.env` |

**Modo de raciocínio profundo**: se `LLM_REASONING_MODEL` ficar vazio, o
toggle "Pensamento profundo" no chat **não aparece na UI**. Para habilitar,
preencher no `.env.build` (exemplos: `openai/o4-mini`, `anthropic/claude-opus-4-5`).
Tunings relacionados (`LLM_REASONING_EFFORT`, `LLM_REASONING_MAX_TOKENS`)
têm defaults razoáveis (`medium` / `8192`) e raramente precisam mudar.

## Configurações operacionais (defaults razoáveis)

As variáveis abaixo **existem em `app/core/config.py`** mas **não estão
expostas** em nenhum `.env*` porque seus defaults atendem 99% dos casos.
Para override, basta exportá-las como env var (em dev) ou adicionar no
`docker-compose.yml` (em prod).

### Sandbox (execução de código)
| Variável | Default | Quando mexer |
|---|---|---|
| `SANDBOX_DEFAULT_TMPFS_MB` | 128 | Workflow precisa de scratch grande |
| `SANDBOX_DEFAULT_PIDS_LIMIT` | 128 | Código spawn-heavy |
| `SANDBOX_POOL_HEALTHCHECK_INTERVAL_S` | 30.0 | Tunning de pool |

### Rate limiting de execuções
| Variável | Default | Quando mexer |
|---|---|---|
| `RATE_LIMIT_EXECUTE_USER_MINUTE` | 30 | Cliente power-user |
| `RATE_LIMIT_EXECUTE_USER_HOUR` | 500 | — |
| `RATE_LIMIT_EXECUTE_PROJECT_MINUTE` | 100 | — |
| `RATE_LIMIT_EXECUTE_PROJECT_HOUR` | 2000 | — |

### Recursos / limites
| Variável | Default | Quando mexer |
|---|---|---|
| `WORKFLOW_DEFAULT_MAX_EXECUTION_TIME_SECONDS` | 3600 (1h) | Migrações longas |
| `EXTRACT_DEFAULT_MAX_ROWS` | 10.000.000 | Volumes muito grandes |
| `WORKFLOW_PREVIEW_MAX_ROWS` | 100 | Preview maior em UI |
| `SHIFT_MAX_EXECUTION_MEMORY_MB` | 4096 | Servidor com mais RAM |
| `SHIFT_MAX_DISK_GB` | 20 | Servidor com mais disco |

### Uploads
| Variável | Default | Quando mexer |
|---|---|---|
| `WORKFLOW_UPLOAD_MAX_FILE_MB` | 500 | Cliente sobe arquivos > 500MB |
| `WORKFLOW_UPLOAD_QUOTA_PER_PROJECT_MB` | 5120 (5GB) | Projeto grande |
| `WORKFLOW_UPLOAD_TTL_DAYS` | 30 | Política de retenção |

### Streaming
| Variável | Default | Quando mexer |
|---|---|---|
| `STREAMING_SPILL_WARN_THRESHOLD` | 50 | Tunning de observability |

### Agent
| Variável | Default | Quando mexer |
|---|---|---|
| `AGENT_APPROVAL_TIMEOUT_SECONDS` | 3600 | Política de aprovações |
| `AGENT_BUDGET_OVERRIDES_JSON` | "" | Override por workspace |
| `AGENT_EXPIRATION_JOB_INTERVAL_MINUTES` | 5 | — |

### Tokens / sessão
| Variável | Default | Quando mexer |
|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | Política de segurança |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 | — |
| `INVITATION_EXPIRE_DAYS` | 7 | — |

Lista completa em [shift-backend/app/core/config.py](../shift-backend/app/core/config.py).

## Cabeçalho padrão dos templates

Todos os arquivos `.env.example` deste repo começam com:

```
# ============================================================================
# PROPOSITO:    <pra que serve este arquivo>
# AUDIENCIA:    <quem edita>
# LIDO POR:     <comando ou processo que consome>
# ARQUIVO REAL: <nome do arquivo gitignored>
#
# Visão geral: docs/configuration.md
# ============================================================================
```

Ao editar qualquer `.env.example`, mantenha esse cabeçalho consistente.
Explicações longas vão neste documento — os templates ficam enxutos.
