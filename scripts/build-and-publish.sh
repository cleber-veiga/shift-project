#!/usr/bin/env bash
# Build & publish das imagens da Shift no Docker Hub.
#
# Carrega segredos oficiais de .env.build (na raiz do repo) e injeta como
# --build-arg no docker build do backend. As chaves vao para
# /etc/shift/embedded.env dentro da imagem — cliente nunca ve.
#
# Pre-requisitos:
#   1) cp .env.build.example .env.build && editar com chaves reais
#   2) docker login (ja autenticado no cleberveiga)
#
# Uso:
#   ./scripts/build-and-publish.sh           # builda e da push (tag = $TAG ou data)
#   TAG=0.2.0 ./scripts/build-and-publish.sh # tag explicita
#   SKIP_PUSH=1 ./scripts/build-and-publish.sh  # so builda, nao da push

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# --- 1. Carrega .env.build ---
if [ ! -f "$ROOT/.env.build" ]; then
    echo "ERRO: $ROOT/.env.build nao existe."
    echo "       cp .env.build.example .env.build  e edite com as chaves reais."
    exit 1
fi

# `set -a` exporta todas as vars assignadas a partir daqui automaticamente.
set -a
# shellcheck disable=SC1091
source "$ROOT/.env.build"
set +a

# Sanity check — pelo menos LLM_API_KEY deve estar setada.
if [ -z "${LLM_API_KEY:-}" ] || [ "$LLM_API_KEY" = "sk-ant-..." ]; then
    echo "ERRO: LLM_API_KEY nao configurado em .env.build (valor placeholder)."
    exit 1
fi

# --- 2. Tag ---
TAG="${TAG:-$(date +%Y%m%d)}"
DOCKERHUB_USER="${DOCKERHUB_USER:-cleberveiga}"
echo "==> Build com TAG=$TAG (user=$DOCKERHUB_USER)"

# --- 3. Build kernel-runtime ---
echo "==> Building kernel-runtime"
docker build \
    -t "$DOCKERHUB_USER/shift-kernel-runtime:$TAG" \
    -t "$DOCKERHUB_USER/shift-kernel-runtime:latest" \
    "$ROOT/kernel-runtime"

# --- 4. Build backend (com segredos embutidos) ---
echo "==> Building shift-backend (com segredos embutidos via build-arg)"
docker build \
    --build-arg LLM_API_KEY="${LLM_API_KEY:-}" \
    --build-arg LLM_REASONING_MODEL="${LLM_REASONING_MODEL:-}" \
    --build-arg GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}" \
    --build-arg RESEND_API_KEY="${RESEND_API_KEY:-}" \
    --build-arg EMAIL_FROM="${EMAIL_FROM:-noreply@shift.app}" \
    --build-arg LANGSMITH_API_KEY="${LANGSMITH_API_KEY:-}" \
    -t "$DOCKERHUB_USER/shift-backend:$TAG" \
    -t "$DOCKERHUB_USER/shift-backend:latest" \
    "$ROOT/shift-backend"

# --- 5. Build frontend ---
# NEXT_PUBLIC_API_BASE_URL e burned no build. Default OK pra teste local.
FRONTEND_API_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000/api/v1}"
echo "==> Building shift-frontend (NEXT_PUBLIC_API_BASE_URL=$FRONTEND_API_URL)"
docker build \
    --build-arg NEXT_PUBLIC_API_BASE_URL="$FRONTEND_API_URL" \
    -t "$DOCKERHUB_USER/shift-frontend:$TAG" \
    -t "$DOCKERHUB_USER/shift-frontend:latest" \
    "$ROOT/shift-frontend"

# --- 6. Push (a menos que SKIP_PUSH=1) ---
if [ "${SKIP_PUSH:-0}" = "1" ]; then
    echo "==> SKIP_PUSH=1 — nao dando push. Build local concluido."
    exit 0
fi

echo "==> Pushing imagens"
docker push "$DOCKERHUB_USER/shift-kernel-runtime:$TAG"
docker push "$DOCKERHUB_USER/shift-kernel-runtime:latest"
docker push "$DOCKERHUB_USER/shift-backend:$TAG"
docker push "$DOCKERHUB_USER/shift-backend:latest"
docker push "$DOCKERHUB_USER/shift-frontend:$TAG"
docker push "$DOCKERHUB_USER/shift-frontend:latest"

echo "==> Concluido. Verifique em https://hub.docker.com/u/$DOCKERHUB_USER"
