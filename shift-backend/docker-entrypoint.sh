#!/bin/sh
# Entrypoint do shift-backend.
#
# Responsabilidades:
#   1. Bootstrap idempotente de SECRET_KEY/ENCRYPTION_KEY em /shift-secrets
#   2. Limpar env vars vazias (para que pydantic-settings caia no env_file)
#   3. Garantir acesso ao /var/run/docker.sock quando montado (sandbox)
#   4. Delegar para o CMD do Dockerfile (alembic + uvicorn)
#
# NAO roda migrations aqui — isso fica no CMD para que `docker compose run
# --rm shift-backend alembic ...` funcione sem aplicar upgrade automatico.

set -e

# --- Bootstrap de segredos (idempotente) ---
# Gera SECRET_KEY e ENCRYPTION_KEY em /shift-secrets/secrets.env na primeira
# subida. Se o arquivo ja existe, nao faz nada. Falha "soft" — apenas loga,
# nao bloqueia o boot (config.py cai no fallback de env vars).
python /usr/local/bin/bootstrap-secrets.py || true

# --- Limpa env vars vazias ---
# Compose com `${VAR:-}` injeta uma string vazia quando a var nao esta
# no .env do host. Pydantic-settings interpreta env vars setadas (mesmo
# vazias) como override do env_file, o que mascararia:
#   - /shift-secrets/secrets.env (gerado pelo bootstrap)
#   - /etc/shift/embedded.env (segredos da Shift embutidos no build)
# Unset garante que vazias nao dominem os arquivos.
for var in \
    SECRET_KEY ENCRYPTION_KEY \
    LLM_API_KEY LLM_REASONING_MODEL \
    GOOGLE_CLIENT_ID RESEND_API_KEY EMAIL_FROM LANGSMITH_API_KEY \
; do
    eval "val=\${$var:-}"
    [ -z "$val" ] && unset "$var" || true
done

# --- Acesso ao docker socket (sandbox) ---
# Quando o socket esta montado, descobrimos o GID do grupo dono e adicionamos
# o usuario 'shift' a esse grupo on-the-fly. Sem isso, a sandbox cai no cold
# path silenciosamente. Falha "soft" — apenas avisa, nao quebra o boot.
if [ -S /var/run/docker.sock ]; then
    SOCK_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo "")
    if [ -n "$SOCK_GID" ] && [ "$SOCK_GID" != "0" ]; then
        # Como o container ja iniciou como user shift, nao podemos mudar o
        # group. O fix real e: o compose ja sobe com group_add do host.
        # Aqui so sinalizamos no log se nao houver acesso.
        if ! [ -r /var/run/docker.sock ] || ! [ -w /var/run/docker.sock ]; then
            echo "[entrypoint] WARN: /var/run/docker.sock GID=$SOCK_GID nao legivel pelo user shift." >&2
            echo "[entrypoint] Sandbox cai no cold path. Configure 'group_add: [\"$SOCK_GID\"]' no compose." >&2
        fi
    fi
fi

exec "$@"
