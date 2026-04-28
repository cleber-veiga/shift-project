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

2. **Edite o `.env`** preenchendo os campos `__FILL_ME__`:
   - `DATABASE_URL` — string de conexao recebida.
   - `SECRET_KEY` e `ENCRYPTION_KEY` — instrucoes de geracao no proprio arquivo.
   - `LLM_API_KEY` (opcional, so se for testar IA).

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

## Problemas comuns

**Backend reinicia em loop / erro de conexao com o banco**
Verifique a `DATABASE_URL` no `.env`. Tem que comecar com
`postgresql+asyncpg://` e terminar com `?sslmode=require`.
O banco precisa ter a extensao `pgcrypto` habilitada — se for um banco
novo, rode uma vez:
```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

**`ENCRYPTION_KEY obrigatorio` no startup**
Voce esqueceu de gerar a chave. Veja `.env.example` para o comando.

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
