# Shift — Deploy via Docker Compose

Stack completa rodando localmente (dev) ou em staging single-host. **Postgres e externo** (banco gerenciado em nuvem) — nao sobe via Compose.

## O que sobe

| Service | Porta host | Imagem | Funcao |
|---|---|---|---|
| `shift-backend` | 8000 | build local | FastAPI + APScheduler in-process |
| `shift-frontend` | 3000 | build local | Next.js 16 |
| `prometheus` | 9090 | prom/prometheus:v2.55.1 | Metricas + alertas |
| `grafana` | 3001 | grafana/grafana:11.3.0 | Dashboards e UI de traces |
| `otel-collector` | (interno) | otel-contrib:0.112.0 | Recebe spans OTLP |
| `tempo` | (interno) | grafana/tempo:2.6.1 | Storage de traces |
| `kernel-runtime-builder` | — | build local | One-shot, builda imagem da sandbox |

> Sem Redis. O backend de hoje usa `slowapi` com storage in-memory (default `memory://`); rate-limit e por instancia. Se algum dia voce subir multiplas replicas e precisar de rate-limit distribuido, o codigo em [shift-backend/app/services/webhooks/replay_limiter.py](shift-backend/app/services/webhooks/replay_limiter.py) ja suporta backend Redis — bastara adicionar `redis` em `pyproject.toml`, subir um service Redis, e setar `RATE_LIMIT_STORAGE_URI=redis://...`.

## Modelo de configuracao (.env)

O projeto tem **um unico `.env` canonico na raiz**. Esse e o que o Docker Compose le e propaga pros containers via `environment:`.

```
shift-project/
├── .env                       ← canonico (gitignored)
├── .env.example               ← template completo (commitado)
├── shift-backend/
│   ├── .env                   ← OPCIONAL — so pra rodar uvicorn standalone (gitignored)
│   └── .env.example           ← documenta vars que o backend consome em standalone
└── shift-frontend/
    ├── .env.local             ← OPCIONAL — so pra rodar pnpm dev standalone (gitignored)
    └── .env.example           ← documenta vars do frontend em standalone
```

**Regra:** o `.env` da raiz e a fonte da verdade. Os `.env*` em sub-pastas sao **opcionais** e existem so pra quando voce roda o backend ou frontend SEM Docker (`uvicorn main:app` ou `pnpm dev` direto). Os `.env.example` em sub-pastas sao **documentacao** da interface daquele app — ajudam alguem entendendo o que cada app precisa, sem ter que parsear `docker-compose.yml`.

### Quando duplicar?

**Quase nunca.** Se voce mantem dois `.env` (raiz + backend), eles vao divergir e voce vai debugar config velha por meia hora antes de perceber. Estrategias:

1. **Single-mode (recomendado)**: rode tudo via Docker. Apague `shift-backend/.env` e `shift-frontend/.env*`. So existe `.env` na raiz.

2. **Hybrid mode (pra debugar)**: ocasionalmente rodar uvicorn local. Em vez de manter `shift-backend/.env`, fonte do root inline:
   ```bash
   cd shift-backend
   set -a; source ../.env; set +a
   uvicorn main:app --reload
   ```
   `set -a` marca toda var lida em seguida pra ser exportada. `set +a` desliga. Pydantic le do `os.environ` e tudo funciona — sem arquivo duplicado.

3. **Symlink (Linux/macOS/WSL2)**: se voce roda standalone com frequencia:
   ```bash
   ln -sf ../.env shift-backend/.env
   ln -sf ../.env shift-frontend/.env.local
   ```
   Mesmo arquivo fisico, apontado de varios lugares. Funciona em WSL2; nao testar em Windows nativo.

### Variavel critica: `NEXT_PUBLIC_API_BASE_URL`

NEXT_PUBLIC_* sao **burned no build** do Next.js. O valor que vai pro JS bundle e o que estava setado **na hora do `pnpm build`**. No Compose, isso vem via `build.args` no `docker-compose.yml`. Se voce mudar a URL e nao rebuildar, o frontend continua chamando o endereco antigo.

Atalho:
```bash
docker compose build shift-frontend && docker compose up -d
```

## Banco de dados — em nuvem

O `Postgres` e um banco gerenciado externo (Neon, Supabase, AWS RDS, GCP Cloud SQL, Azure DB, etc). O backend recebe a conexao via `DATABASE_URL` no `.env`. O Compose **nao** sobe Postgres — economiza recursos e respeita o setup real do projeto.

**Formato esperado do URL** (asyncpg + alembic, SSL obrigatorio):
```
DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:5432/DB?sslmode=require
```

> Use `?sslmode=require` (NAO `?ssl=require`). SQLAlchemy traduz para asyncpg em runtime e psycopg2 em alembic — ambos respeitam `sslmode`. Misturar formatos quebra o boot ou as migrations.

**Bootstrap manual (uma unica vez):** o banco em nuvem precisa da extensao `pgcrypto` para `gen_random_uuid()`. Aplique:
```bash
make db-bootstrap
```
Equivale a `psql "$DATABASE_URL" -f ops/postgres/bootstrap.sql`. Idempotente.

**Conectividade:** o backend faz outbound do container — nenhuma config especial de rede e necessaria, desde que o cluster aceite conexoes do IP de saida da sua maquina/host. Em alguns provedores (RDS, Cloud SQL) voce precisa whitelist o IP publico ou usar VPN/proxy.

## Modelo de processo (importante)

Single-process. **Nao tem Celery worker, nao tem Celery beat, nao tem Prefect.** Todo o agendamento (webhook dispatch, cleanup de checkpoints, extract-cache GC, agent expiration) roda em **APScheduler in-process** dentro do FastAPI — registrado no `lifespan` em [shift-backend/main.py](shift-backend/main.py).

Consequencia operacional: o backend roda com **single worker** uvicorn (`--workers 1`). Multi-worker no mesmo container quebra APScheduler — cada worker tentaria iniciar o scheduler e disparar jobs duplicados. Para escalar horizontalmente, suba **multiplas replicas** do `shift-backend` — APScheduler com `SQLAlchemyJobStore` coordena via locks no Postgres (`coalesce=True`, `max_instances=1`).

## Pre-requisitos

- Docker Engine 24+ com Buildx
- Docker Compose v2
- 6 GB RAM livre, 10 GB disco
- **Linux ou macOS preferivel.** Windows funciona via Docker Desktop + WSL2 backend (so), mas com ressalvas — ver "Windows + Docker socket" abaixo.

## Primeira subida

```bash
cp .env.example .env

# 1) Configurar DATABASE_URL no .env apontando pro Postgres em nuvem.
#    Edite .env e troque a linha DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST...

# 2) Gerar segredos:
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))" >> .env
python -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())" >> .env
# (Editar .env e remover linhas duplicadas / __GENERATE_ME__)

# 3) Linux/WSL2: descobrir GID do grupo docker e setar no .env
echo "DOCKER_GID=$(getent group docker | cut -d: -f3)" >> .env

# 4) Bootstrap do banco em nuvem (UMA UNICA VEZ — instala pgcrypto):
make db-bootstrap

# 5) Build + up
make build          # builda kernel-runtime + backend + frontend
make up             # sobe stack (entrypoint roda alembic upgrade head)
make test-stack     # smoke test
```

Esperar ~60-90s na primeira subida (pull de imagens + build do venv + pre-warm de 2 sandboxes).

> Se `make db-bootstrap` falhar com timeout/conexao recusada, o IP de saida da sua maquina nao tem permissao no provider. Adicione na whitelist (RDS Security Group, Cloud SQL authorized networks, Neon project settings, etc).

## URLs

| Recurso | URL |
|---|---|
| Backend API | http://localhost:8000 |
| Backend OpenAPI | http://localhost:8000/docs |
| Backend metrics | http://localhost:8000/metrics |
| Frontend | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 (admin / `GRAFANA_ADMIN_PASSWORD`) |
| Tempo | via Grafana → Explore → Tempo |

## Volumes persistentes

| Volume | Conteudo |
|---|---|
| `prometheus_data` | TSDB (15d retencao) |
| `grafana_data` | Config/usuarios do Grafana |
| `tempo_data` | Blocos de traces (24h retencao) |
| `shift_checkpoints` | DuckDB de checkpoints de execucao |
| `shift_extract_cache` | Cache de extracoes |
| `shift_uploads` | Arquivos uploadados pra variaveis de workflow |
| `streaming_spill` | tmpfs (2GB) — spillover de chunks entre nodes |

`make down` preserva todos. `make down-volumes` apaga (com confirmacao).

## Sandbox de code_node — funcionamento

A sandbox executa codigo Python do usuario em containers efemeros (imagem `shift-kernel-runtime:latest`, baseada em `kernel-runtime/Dockerfile`). O backend usa o socket Docker do host (`/var/run/docker.sock`) para spawnar e destruir containers via `docker-py`.

**Pre-warming**: `SANDBOX_POOL_TARGET_IDLE=2` mantem 2 containers iniciados e bloqueados em `sys.stdin.read()` esperando codigo. `acquire()` devolve em ms (sem custo de start + import duckdb).

**Verificar**:
```bash
make prewarm-check
```
Deve listar 2 containers `shift-kernel-runtime:latest` em estado `Up`.

## Windows + Docker socket

No Windows, o backend roda dentro de um container Linux via WSL2. O mount `/var/run/docker.sock:/var/run/docker.sock` **funciona** porque Docker Desktop expõe o daemon Linux do WSL2 nesse caminho.

Pegadinhas:
- Setar `DOCKER_GID` no `.env`. Em WSL2 com Docker Desktop, o socket e do grupo GID `999` por padrao. Se `make prewarm-check` mostrar 0 containers e os logs disserem "permission denied on /var/run/docker.sock", checar com:
  ```bash
  docker compose exec shift-backend stat -c '%g' /var/run/docker.sock
  ```
  e ajustar `DOCKER_GID` no `.env` pra esse valor.
- Bind mount de `./shift-backend:/app` (override.yml) pode ser lento em WSL2 se o codigo estiver em `C:\`. Mover o repo pra `\\wsl$\...` da reload mais rapido.

## Tracing — fluxo

```
shift-backend  ─OTLP/HTTP:4318─►  otel-collector  ─OTLP/gRPC:4317─►  tempo
                                                                       │
                                                                       └─► Grafana (datasource Tempo)
```

`SHIFT_TRACING_ENABLED=true` ativa o init do tracer ([shift-backend/app/core/observability.py](shift-backend/app/core/observability.py)). Logs JSON do backend incluem `trace_id` quando ha span ativo — correlacao directa com Grafana.

**Verificar**:
1. Disparar uma execucao de workflow pela UI.
2. Grafana → Explore → Tempo → Search → service.name=shift-backend.
3. Click no span pra ver a arvore.

Se nao aparecer nada:
- `docker compose logs otel-collector | grep -i error`
- `curl -s http://localhost:8000/metrics | grep otel_` — se houver export errors, o backend reporta como counter.

## Troubleshooting

**Backend nao fica healthy em 60s**
```bash
make logs-backend
```
Causas comuns:
- **Banco em nuvem inacessivel** — IP da sua maquina/host nao esta na whitelist do provider (RDS Security Group, Cloud SQL authorized networks, Neon, etc). Sintoma: `ConnectionRefusedError` ou `getaddrinfo failed` no log.
- **`DATABASE_URL` malformado** — falta `?sslmode=require`, ou trocou `+asyncpg` por outro driver. Testar fora do compose: `psql "$DATABASE_URL"` (depois de remover `+asyncpg`).
- **Bootstrap nao foi aplicado** — `make db-bootstrap` deve rodar antes do primeiro `make up` se a extensao `pgcrypto` ainda nao estiver no banco.
- Migration falhou — `alembic upgrade head` no log mostra o erro.
- Sandbox pre-warm falhou silenciosamente — backend continua subindo mas log avisa `sandbox.pool.startup_failed`. Cair no cold path nao impede o boot.

**Sandbox nao funciona**
- `docker compose exec shift-backend ls -la /var/run/docker.sock` — deve listar o socket.
- `make prewarm-check` — se 0 containers, ver `DOCKER_GID` (Windows/WSL2 acima).
- `docker images | grep shift-kernel-runtime` — se ausente, rodar `make build-kernel`.

**Metricas zeradas no Prometheus**
- Prometheus → http://localhost:9090/targets — todos os targets devem estar `UP`.
- `shift-backend` target down? `docker compose logs shift-backend | grep instrumentator`.

**Grafana sem dashboards**
- Provisioning roda no boot do Grafana, le `/etc/grafana/provisioning/dashboards.yml` que aponta pra `/etc/grafana/dashboards/` — montado de `ops/grafana/dashboards/`. Se voce trocar de branch, `make restart` (Grafana so re-le se restart).

**Webhooks: `WEBHOOK_ALLOW_INSECURE_HOSTS`**
- Em dev (override) vem `true` — anti-SSRF desligado pra permitir endpoints locais (`localhost`, `192.168.x.x`).
- Em prod-like (sem override) vem `false` — recusa hosts privados, bloqueia redirect, valida DNS. NUNCA habilite em prod.

## Operacoes comuns

```bash
make logs-backend                    # tail do backend
make shell                           # bash dentro do backend
make shell-db                        # psql contra o Postgres em nuvem
make db-bootstrap                    # aplica pgcrypto no banco em nuvem (uma vez)
make migrate                         # rodar migrations no banco em nuvem
make migrate-revision MSG="add x"    # gerar nova migration
make test-stack                      # smoke test rapido
make down                            # parar (preserva volumes locais)
make down-volumes                    # APAGA volumes locais (NAO toca o banco em nuvem)
make reset                           # nuke + rebuild + up + migrate
```

## Producao — o que NAO esta aqui

Esta config e pra **dev e staging single-host**. Antes de jogar em prod:

1. **Isolamento de sandbox**: trocar `/var/run/docker.sock` por **gVisor** ou **Sysbox**. Mount direto do socket = root no host se o codigo do usuario explorar o daemon.
2. **Postgres em nuvem**: ja resolvido (banco gerenciado). Verificar se o tier escolhido tem replicacao + PITR (point-in-time-recovery). Habilitar IAM auth se possivel em vez de senha em `.env`.
3. **Prometheus**: trocar por Mimir/Cortex se houver muitos workspaces (cardinalidade explode rapido).
4. **Tempo**: storage S3/GCS, nao local. Retencao alinhada com SLO de investigacao (7-14d).
5. **Secrets**: Vault, AWS Secrets Manager, GCP Secret Manager — nao `.env` em disco.
6. **TLS**: terminacao em reverse proxy (Caddy/Traefik/nginx) na frente. NUNCA expor o backend em `0.0.0.0:8000` sem TLS.
7. **Network policies**: em K8s, NetworkPolicy isolando os scrapes do Prometheus. No compose puro, considerar `network_mode: internal` em services que nao precisam falar com a internet.
8. **APScheduler escalando**: se for >1 replica de backend, garantir que `SQLAlchemyJobStore` esta usando `coalesce=True` e `max_instances=1` por job (verificar [shift-backend/app/services/scheduler_service.py](shift-backend/app/services/scheduler_service.py)).
9. **Image pinning**: pin de tag SHA-256 (`@sha256:...`) em vez de tags moviveis pra reproducibilidade.

## Estrutura de arquivos criados

```
shift-project/
├── docker-compose.yml                      ← stack principal
├── docker-compose.override.yml             ← overrides de dev (auto-load)
├── .env.example                            ← template (copie pra .env)
├── Makefile                                ← atalhos
├── README-DEPLOY.md                        ← este arquivo
├── shift-backend/
│   ├── Dockerfile                          ← Python 3.12-slim, multi-stage
│   └── docker-entrypoint.sh                ← acesso ao docker.sock
├── shift-frontend/
│   └── Dockerfile                          ← Node 22-alpine + pnpm
├── kernel-runtime/Dockerfile               ← (ja existia)
└── ops/
    ├── postgres/bootstrap.sql              ← aplicar manualmente no banco em nuvem (pgcrypto)
    ├── prometheus/prometheus.yml           ← (atualizado: targets via DNS interno)
    ├── alerts/                             ← (ja existia, montado)
    ├── grafana/
    │   ├── provisioning/datasources.yml    ← (atualizado: + Tempo)
    │   ├── provisioning/dashboards.yml     ← (ja existia)
    │   └── dashboards/                     ← (ja existia, 3 dashboards)
    ├── otel-collector/otel-collector-config.yml
    └── tempo/tempo.yml
```
