# Imagem do frontend Shift — Next.js 16 + React 19 + pnpm.
#
# Multi-stage:
#   - deps:    instala node_modules via pnpm com cache
#   - builder: gera .next/ via `pnpm build`
#   - runner:  imagem final minima com node + .next/ + node_modules prod
#
# Sem `output: standalone` no next.config — usamos start padrao.

# === Stage 1: deps ===
FROM node:22-alpine AS deps

# corepack vem com o node 22 — habilita pnpm na versao do package.json.
RUN corepack enable

WORKDIR /app

# Copia somente os arquivos de lock para maximizar cache.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# === Stage 2: builder ===
FROM node:22-alpine AS builder

RUN corepack enable
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Garante /app/public — projeto pode nao ter (Next.js trata como opcional),
# mas o stage runner faz COPY incondicional. mkdir -p e idempotente.
RUN mkdir -p /app/public

# Variaveis NEXT_PUBLIC_* sao "burned" no build — precisam estar disponiveis
# como build-arg ou ambiente. Em dev use o override; em prod passe via --build-arg.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

RUN pnpm build

# === Stage 3: runner ===
FROM node:22-alpine AS runner

RUN corepack enable

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json
COPY --from=builder --chown=nextjs:nodejs /app/pnpm-lock.yaml ./pnpm-lock.yaml

USER nextjs

EXPOSE 3000

CMD ["pnpm", "start"]
