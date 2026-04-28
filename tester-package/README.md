# Shift — teste local

Stack pra rodar a plataforma Shift na sua maquina via Docker.

## Pre-requisitos

- **Docker Desktop** (Windows/macOS) ou **Docker Engine + Compose plugin** (Linux).
  Versao do Compose >= 2.20.
- **8 GB de RAM livre** recomendado (backend + sandbox + frontend).
- A `DATABASE_URL` que o Cleber te enviou (Postgres em nuvem).

## Setup (uma unica vez)

1. **Copie o template de variaveis:**
   ```bash
   cp .env.example .env
   ```

2. **Edite o `.env`** preenchendo o unico campo `__FILL_ME__`:
   - `DATABASE_URL` — string de conexao recebida.

   `SECRET_KEY` e `ENCRYPTION_KEY` sao **geradas automaticamente** no
   primeiro `up` e persistidas em um volume Docker. Nao precisa gerar nada.

3. **Puxe as imagens do Docker Hub:**
   ```bash
   docker compose pull
   ```
   (~2-3 GB no total — backend, frontend e a imagem da sandbox de codigo.)

## Rodando

```bash
docker compose up -d
```

Aguarde ~30-60s na primeira vez (migrations Alembic + warm-up das sandboxes).
Acompanhe com:
```bash
docker compose logs -f shift-backend
```

Quando ver `Application startup complete`, abra:

- **Frontend:** http://localhost:3000
- **API/Docs:** http://localhost:8000/docs
- **Healthcheck:** http://localhost:8000/health

## Operacoes do dia-a-dia

| Acao                          | Comando                                    |
|-------------------------------|--------------------------------------------|
| Parar tudo                    | `docker compose down`                      |
| Parar e apagar dados          | `docker compose down -v`                   |
| Atualizar para versao mais nova | `docker compose pull && docker compose up -d` |
| Ver logs do backend           | `docker compose logs -f shift-backend`     |
| Ver logs do frontend          | `docker compose logs -f shift-frontend`    |
| Status dos containers         | `docker compose ps`                        |

## Conectar a um Firebird (3 cenarios)

### Cenario A — voce tem so o arquivo `.fdb`

Use os Firebird bundled da Shift (containers FB 2.5 e 3.0). **Este cenario
exige um compose adicional** (`docker-compose.firebird.yml`) que sobe os
servidores e adiciona o bind dos arquivos.

1. Crie uma pasta no host para os arquivos (ex: `C:\Shift\Data` ou `/opt/shift/data`).
2. Copie os `.fdb` para essa pasta.
3. Edite `.env` descomentando e preenchendo:
   ```
   FIREBIRD_LEGACY_DATA_DIR=C:/Shift/Data
   FIREBIRD_LEGACY_PASSWORD=masterkey
   ```
4. Suba combinando os dois compose files:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.firebird.yml up -d
   ```

   > Dica: para nao ter que repetir o `-f` em todo comando, use a env var
   > `COMPOSE_FILE`:
   > ```bash
   > # bash
   > export COMPOSE_FILE=docker-compose.yml:docker-compose.firebird.yml
   > # PowerShell
   > $env:COMPOSE_FILE = "docker-compose.yml;docker-compose.firebird.yml"
   > ```
   > Depois `docker compose up -d`, `down`, `logs`, etc usam os dois files.

5. Na UI, ao criar a Connection:
   - **Host:** `firebird25` (para ODS 11.x — FB 2.5) ou `firebird30` (para ODS 12+)
   - **Port:** `3050`
   - **Path:** `/firebird/data/<nome>.FDB`
   - **User/Password:** `SYSDBA` / `masterkey` (ou o que voce setou)

### Cenario B — Firebird Server ja roda no seu Windows/macOS

Sobe normal (so o compose base):
```bash
docker compose up -d
```

Na UI, ao criar a Connection:
- **Host:** `host.docker.internal`
- **Port:** `3050`
- **Path:** caminho do `.fdb` no seu host (ex: `C:\dados\base.fdb`)

### Cenario C — Firebird em servidor remoto na rede

Sobe normal (so o compose base). Conecte direto pelo IP/hostname do
servidor — nao precisa de nada especial.

## Problemas comuns

**Backend reinicia em loop / erro de conexao com o banco**
Verifique a `DATABASE_URL` no `.env`. Tem que comecar com
`postgresql+asyncpg://` e terminar com `?sslmode=require`.
O banco precisa ter a extensao `pgcrypto` habilitada — se for um banco
novo, rode uma vez:
```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

**Perdi as chaves auto-geradas (apaguei o volume com `down -v`)**
As credenciais de connections gravadas antes ficam ilegiveis. Recrie as
connections via UI — nao tem como recuperar a `ENCRYPTION_KEY` antiga.
Para evitar: use `docker compose down` (sem `-v`) sempre que possivel.

**Sandbox falha com `permission denied` em `/var/run/docker.sock` (Linux/WSL2)**
Ajuste `DOCKER_GID` no `.env` rodando:
```bash
getent group docker | cut -d: -f3
```
e use o numero retornado.

**Porta 3000 ou 8000 ja em uso**
Pare o que estiver usando a porta, ou edite o `docker-compose.yml`
mudando o lado esquerdo do mapeamento (ex: `"3001:3000"`).

## Suporte

Manda print + saida de `docker compose logs --tail=200 shift-backend`
pro Cleber.
