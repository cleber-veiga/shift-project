# Build & publicar imagens no Docker Hub

Guia rapido pra publicar a stack do Shift no Docker Hub
(`cleberveiga/*`) e mandar pro tester.

## 1. Login (uma vez)

```bash
docker login
# usuario: cleberveiga
# senha: token de https://hub.docker.com/settings/security
```

> Crie um **Access Token** em https://hub.docker.com/settings/security
> e use como senha — nao use sua senha de conta.

## 2. Definir versao

```bash
export TAG=0.1.0   # ou date +%Y%m%d, ou git rev-parse --short HEAD
```

(No PowerShell: `$env:TAG="0.1.0"`)

## 3. Build das 3 imagens (na raiz do repo)

```bash
# Sandbox de execucao de codigo
docker build \
  -t cleberveiga/shift-kernel-runtime:$TAG \
  -t cleberveiga/shift-kernel-runtime:latest \
  ./kernel-runtime

# Backend (FastAPI)
docker build \
  -t cleberveiga/shift-backend:$TAG \
  -t cleberveiga/shift-backend:latest \
  ./shift-backend

# Frontend (Next.js)
# IMPORTANTE: NEXT_PUBLIC_API_BASE_URL e burned no build.
# Como o tester roda 100% local, fixe em http://localhost:8000/api/v1.
docker build \
  --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1 \
  -t cleberveiga/shift-frontend:$TAG \
  -t cleberveiga/shift-frontend:latest \
  ./shift-frontend
```

## 4. Push

```bash
docker push cleberveiga/shift-kernel-runtime:$TAG
docker push cleberveiga/shift-kernel-runtime:latest
docker push cleberveiga/shift-backend:$TAG
docker push cleberveiga/shift-backend:latest
docker push cleberveiga/shift-frontend:$TAG
docker push cleberveiga/shift-frontend:latest
```

Confira em https://hub.docker.com/u/cleberveiga.

## 5. Mandar pro tester

Zipe e envie a pasta `tester-package/` (apenas 3 arquivos):

```
tester-package/
├── docker-compose.yml
├── .env.example
└── README.md
```

E mande **separadamente** (chat direto, nao no zip):
- a `DATABASE_URL` do Postgres em nuvem que voce provisionou pra ele.

> Antes de mandar, **rode um teste voce mesmo** seguindo o
> `tester-package/README.md` — confirma que as imagens publicadas
> sobem limpas com a `DATABASE_URL` real.

## 6. Banco de dados — preparar antes

No Postgres em nuvem (Neon/Supabase/RDS), antes do primeiro `up`:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

(As migrations Alembic rodam automaticamente no startup do backend.)

## 7. Atualizar uma versao depois

```bash
export TAG=0.1.1
# repete passos 3 e 4
```

O tester atualiza com:
```bash
docker compose pull && docker compose up -d
```

## Observacoes

- **Repos publicos no Docker Hub sao gratis** e ilimitados.
- **Nao tem segredos nas imagens** — `DATABASE_URL`, `SECRET_KEY`,
  `ENCRYPTION_KEY` chegam via `.env` em runtime. Seguro publicar.
- **`NEXT_PUBLIC_API_BASE_URL` fixo em `localhost:8000`** funciona
  pra teste local. Pra deploy em servidor com dominio real, vai
  precisar rebuildar o frontend com a URL publica.
- A stack de observabilidade (Prometheus/Grafana/Tempo/OTel) **foi
  removida** do compose do tester pra economizar memoria/complexidade —
  `SHIFT_TRACING_ENABLED=false` evita erros de conexao.
