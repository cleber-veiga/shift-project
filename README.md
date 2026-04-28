# Shift

Plataforma de integração, migração e automação de dados entre sistemas legados e data warehouses modernos.

## Visão Geral

O Shift foi construído para resolver um problema comum em empresas com ERPs legados (Firebird, Oracle, etc.): extrair dados desses sistemas, transformá-los e carregá-los em destinos modernos (PostgreSQL, DW) de forma confiável, com rastreabilidade e sem necessidade de scripts avulsos.

A plataforma oferece um ambiente visual para criar conexões, montar workflows de ETL, executar queries exploratórias com assistência de IA e acompanhar as execuções orquestradas pelo Prefect.

## Funcionalidades

- **Conexões** — gerenciamento de connection strings para múltiplas fontes e destinos, com suporte a Firebird, PostgreSQL e outros. Strings armazenadas com criptografia.
- **Workflows de ETL** — editor visual para montar fluxos de extração, transformação e carga. Execução orquestrada via Prefect com histórico de runs.
- **Playground SQL** — editor de queries com assistente de IA (LiteLLM + LangGraph). O assistente executa um loop ReAct com ferramentas read-only (inspecionar schema, contar linhas, executar query, etc.) e transmite o raciocínio em tempo real via SSE.
- **Workspaces e Projetos** — estrutura multi-tenant com organizações, grupos econômicos, workspaces e projetos para isolar ambientes de diferentes clientes ou equipes.
- **Queries salvas** — repositório de queries reutilizáveis por projeto.
- **Autenticação** — login com e-mail/senha (JWT) e OAuth com Google.

## Stack

| Camada | Tecnologias |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/ui |
| Backend | FastAPI, Python 3.11+, SQLAlchemy (async), Alembic |
| Banco de dados | PostgreSQL (aplicação), DuckDB (staging local) |
| Orquestração | Prefect 3 |
| Pipelines | dlt (data load tool) |
| IA | LiteLLM, LangChain, LangGraph |
| Auth | JWT (PyJWT + pwdlib/Argon2), Google OAuth |

## Estrutura do Repositório

```
shift-project/
├── shift-backend/   # API FastAPI + orquestração Prefect + pipelines dlt
└── shift-frontend/  # Aplicação Next.js
```

Cada diretório possui seu próprio README com instruções de setup e execução.

## Configuração

Existem múltiplos arquivos `.env*` no repo, um para cada audiência (dev local, build, tester, MCP, etc). O ponto de entrada único é:

→ **[docs/configuration.md](docs/configuration.md)** — mapa completo, hierarquia de fontes, e qual arquivo editar em cada situação.

Para publicar imagens no Docker Hub, ver [BUILD-AND-PUBLISH.md](BUILD-AND-PUBLISH.md).

## Suporte a Firebird

A Shift trata Firebird como cidadão de primeira classe — comum em ERPs brasileiros legados (Viasoft, Linx, etc). Suporta 3 cenários de deploy:

- **Cenário A — Servidor bundled**: cliente entrega só o `.fdb`; a Shift sobe FB 2.5 ou 3.0 em container.
- **Cenário B — Firebird no Windows host**: backend conecta no Firebird que já roda na máquina via `host.docker.internal`.
- **Cenário C — Servidor remoto na rede**: conexão TCP direta para outra máquina.

O wizard de cenário no formulário de conexão guia o usuário e o pipeline de diagnóstico em 4 etapas (DNS → TCP → greeting → auth_query) localiza falhas com mensagens acionáveis em PT-BR.

Guia completo: [docs/firebird-deployment.md](docs/firebird-deployment.md).
