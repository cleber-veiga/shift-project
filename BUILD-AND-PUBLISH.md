# Build & publicar imagens no Docker Hub

Guia para publicar a stack do Shift no Docker Hub (`cleberveiga/*`) e
mandar pro tester.

> Para visão geral de TODOS os arquivos `.env*` e como cada um se
> encaixa, ver [docs/configuration.md](docs/configuration.md).

## TL;DR (caminho rápido)

**Configurar uma vez:**

```powershell
# PowerShell
Copy-Item .env.build.example .env.build
# editar .env.build com as chaves reais (LLM_API_KEY, GOOGLE_CLIENT_ID, etc)
docker login
```

```bash
# bash / Git Bash / WSL
cp .env.build.example .env.build
docker login
```

**Buildar e publicar** — escolha o script do seu shell:

```powershell
# PowerShell (Windows nativo)
.\scripts\build-and-publish.ps1
.\scripts\build-and-publish.ps1 -Tag 0.2.0
.\scripts\build-and-publish.ps1 -SkipPush       # build local sem push
```

```bash
# bash / Git Bash / WSL / Linux / macOS
bash scripts/build-and-publish.sh
TAG=0.2.0 bash scripts/build-and-publish.sh
SKIP_PUSH=1 bash scripts/build-and-publish.sh   # build local sem push
```

`.env.build` está no `.gitignore` — guarde backup em password manager.

O resto do documento detalha o que os scripts fazem por baixo dos panos,
caso precise rodar passo a passo.

## 1. Login (uma vez)

```bash
docker login
# usuario: cleberveiga
# senha: token de https://hub.docker.com/settings/security
```

> Crie um **Access Token** em https://hub.docker.com/settings/security
> e use como senha — não use sua senha de conta.

## 2. Definir versão

```powershell
# PowerShell
$env:TAG = "0.1.0"
```

```bash
# bash
export TAG=0.1.0
```

## 3. Build das 3 imagens (na raiz do repo)

> ⚠️ **Sintaxe de continuação de linha**: bash usa `\`, PowerShell usa `` ` ``
> (backtick). Os blocos abaixo estão em **duas variantes** — use a que
> bate com seu shell.

### 3a. Sandbox (kernel-runtime)

**PowerShell:**
```powershell
docker build `
  -t cleberveiga/shift-kernel-runtime:$env:TAG `
  -t cleberveiga/shift-kernel-runtime:latest `
  ./kernel-runtime
```

**bash:**
```bash
docker build \
  -t cleberveiga/shift-kernel-runtime:$TAG \
  -t cleberveiga/shift-kernel-runtime:latest \
  ./kernel-runtime
```

### 3b. Backend (FastAPI) — com segredos da Shift

> **IMPORTANTE**: passe os segredos como `--build-arg`. Eles vão para
> `/etc/shift/embedded.env` dentro da imagem. O cliente NUNCA edita nem
> vê esses valores.

**PowerShell** — carrega `.env.build` e builda:
```powershell
# Carrega vars de .env.build no escopo atual
Get-Content .env.build | ForEach-Object {
    if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*)$') {
        Set-Item -Path "Env:$($matches[1].Trim())" -Value $matches[2].Trim()
    }
}

docker build `
  --build-arg LLM_API_KEY="$env:LLM_API_KEY" `
  --build-arg LLM_REASONING_MODEL="$env:LLM_REASONING_MODEL" `
  --build-arg GOOGLE_CLIENT_ID="$env:GOOGLE_CLIENT_ID" `
  --build-arg RESEND_API_KEY="$env:RESEND_API_KEY" `
  --build-arg EMAIL_FROM="$env:EMAIL_FROM" `
  --build-arg LANGSMITH_API_KEY="$env:LANGSMITH_API_KEY" `
  -t cleberveiga/shift-backend:$env:TAG `
  -t cleberveiga/shift-backend:latest `
  ./shift-backend
```

**bash** — `set -a` exporta tudo de `.env.build` automaticamente:
```bash
set -a; source .env.build; set +a

docker build \
  --build-arg LLM_API_KEY="$LLM_API_KEY" \
  --build-arg LLM_REASONING_MODEL="$LLM_REASONING_MODEL" \
  --build-arg GOOGLE_CLIENT_ID="$GOOGLE_CLIENT_ID" \
  --build-arg RESEND_API_KEY="$RESEND_API_KEY" \
  --build-arg EMAIL_FROM="${EMAIL_FROM:-noreply@shift.app}" \
  --build-arg LANGSMITH_API_KEY="$LANGSMITH_API_KEY" \
  -t cleberveiga/shift-backend:$TAG \
  -t cleberveiga/shift-backend:latest \
  ./shift-backend
```

### 3c. Frontend (Next.js)

> `NEXT_PUBLIC_API_BASE_URL` é **burned no build**. Para teste local,
> fixe em `http://localhost:8000/api/v1`. Para deploy em domínio real,
> rebuild com a URL pública.

**PowerShell:**
```powershell
docker build `
  --build-arg NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api/v1" `
  -t cleberveiga/shift-frontend:$env:TAG `
  -t cleberveiga/shift-frontend:latest `
  ./shift-frontend
```

**bash:**
```bash
docker build \
  --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1 \
  -t cleberveiga/shift-frontend:$TAG \
  -t cleberveiga/shift-frontend:latest \
  ./shift-frontend
```

## 4. Push

**PowerShell:**
```powershell
docker push cleberveiga/shift-kernel-runtime:$env:TAG
docker push cleberveiga/shift-kernel-runtime:latest
docker push cleberveiga/shift-backend:$env:TAG
docker push cleberveiga/shift-backend:latest
docker push cleberveiga/shift-frontend:$env:TAG
docker push cleberveiga/shift-frontend:latest
```

**bash:**
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

Zipe e envie a pasta `tester-package/` (4 arquivos):

```
tester-package/
├── docker-compose.yml             # base — Cenarios B e C
├── docker-compose.firebird.yml    # opcional — Cenario A (FB bundled)
├── .env.example
└── README.md
```

E mande **separadamente** (chat direto, não no zip):
- a `DATABASE_URL` do Postgres em nuvem que você provisionou pra ele.

> Antes de mandar, **rode um teste você mesmo** seguindo o
> `tester-package/README.md` — confirma que as imagens publicadas
> sobem limpas com a `DATABASE_URL` real.

## 6. Banco de dados — preparar antes

No Postgres em nuvem (Neon/Supabase/RDS), antes do primeiro `up`:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

(As migrations Alembic rodam automaticamente no startup do backend.)

## 7. Atualizar uma versão depois

```powershell
$env:TAG = "0.1.1"      # PowerShell
# ou
export TAG=0.1.1         # bash
# repete passos 3 e 4
```

O tester atualiza com:
```bash
docker compose pull && docker compose up -d
```

## Observações

- **Repos públicos no Docker Hub são grátis** e ilimitados.
- **A imagem do backend embute segredos da Shift** (`LLM_API_KEY`,
  `LLM_REASONING_MODEL`, `GOOGLE_CLIENT_ID`, `RESEND_API_KEY`,
  `LANGSMITH_API_KEY`) via `--build-arg` no build. Eles vão para
  `/etc/shift/embedded.env` dentro da imagem. **Trate o repo como
  privado se contém chaves de prod** — qualquer um que faça
  `docker pull` pode extrair os arquivos. Para Docker Hub público,
  builde sem os build-args (ou com chaves de uma conta dedicada com
  rate-limit).
- **Não tem segredos do CLIENTE nas imagens** — `DATABASE_URL` chega
  via `.env` em runtime. `SECRET_KEY` e `ENCRYPTION_KEY` são geradas
  automaticamente no primeiro `up` e persistidas no volume Docker
  `shift_secrets`.
- **`NEXT_PUBLIC_API_BASE_URL` fixo em `localhost:8000`** funciona
  pra teste local. Pra deploy em servidor com domínio real, vai
  precisar rebuildar o frontend com a URL pública.
- A stack de observabilidade (Prometheus/Grafana/Tempo/OTel) **foi
  removida** do compose do tester pra economizar memória/complexidade —
  `SHIFT_TRACING_ENABLED=false` evita erros de conexão.

## Rotação de chave LLM

Se precisar trocar a `LLM_API_KEY` (chave comprometida ou rotação periódica):

1. Gere nova chave no provider (Anthropic Console).
2. Edite `.env.build` com a nova chave.
3. Rode `.\scripts\build-and-publish.ps1` (ou `bash scripts/build-and-publish.sh`).
4. Cliente faz `docker compose pull && docker compose up -d` —
   atualiza para a imagem nova com a chave nova. Sem downtime além
   do restart do container.

A `SHIFT_LICENSE_KEY` (gateway de LLM por cliente) não existe ainda —
todos os clientes compartilham a mesma `LLM_API_KEY`. Se vazar via
extração da imagem por um cliente malicioso, todos são afetados até
o próximo rebuild com chave nova. Aceitável hoje (poucos clientes,
relação de confiança); revisar quando escalar.
