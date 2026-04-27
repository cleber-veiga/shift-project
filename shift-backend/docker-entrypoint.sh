#!/bin/sh
# Entrypoint do shift-backend.
#
# Responsabilidades:
#   1. Garantir acesso ao /var/run/docker.sock quando montado (sandbox)
#   2. Espera curta pelo Postgres (depends_on cobre, mas defesa em profundidade)
#   3. Delegar para o CMD do Dockerfile (uvicorn)
#
# NAO roda migrations aqui — isso fica no CMD para que `docker compose run
# --rm shift-backend alembic ...` funcione sem aplicar upgrade automatico.

set -e

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
