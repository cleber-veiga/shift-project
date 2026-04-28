# Imagem do backend Shift — FastAPI + APScheduler in-process.
#
# Multi-stage:
#   - builder: instala deps em virtualenv isolado
#   - runtime: copia o venv pronto + codigo, roda uvicorn
#
# Notas de tamanho/superficie:
#   - Python 3.12 (mesma do kernel-runtime) para consistencia
#   - libpq5 / libaio1 / libfbclient2 sao runtime-only (drivers de DBs externos)
#   - build-essential, libpq-dev e libaio1 ficam SOMENTE no builder
#   - usuario nao-root 'shift' uid 1000

# === Stage 1: builder ===
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# build-essential   -> compila wheels nativos (cryptography, asyncpg fallback, etc)
# libpq-dev         -> headers do Postgres p/ psycopg/asyncpg
# libfbclient2      -> Firebird (firebird-driver)
# unixodbc-dev      -> headers ODBC p/ pyodbc
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libfbclient2 \
        unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# Instala deps em /opt/venv para isolar do system Python.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copia somente os arquivos de dependencias para maximizar cache.
COPY pyproject.toml ./

# Instala em modo "deps only" — codigo entra no proximo stage.
# pip install . falha sem o codigo, entao usamos pyproject extracted deps.
RUN pip install --upgrade pip setuptools wheel \
    && pip install \
        "fastapi[standard]>=0.115,<1.0" \
        "pydantic>=2.9,<2.11" \
        "pydantic-settings>=2.6,<3.0" \
        "sqlalchemy[asyncio]>=2.0.36,<2.1" \
        "asyncpg>=0.30,<1.0" \
        "alembic>=1.14,<2.0" \
        "dlt[postgres]>=1.4,<2.0" \
        "duckdb>=1.1,<2.0" \
        "langchain>=0.3,<1.0" \
        "langchain-core>=0.3,<1.0" \
        "langchain-community>=0.3,<1.0" \
        "langchain-openai>=0.2,<1.0" \
        "langchain-anthropic>=0.3,<1.0" \
        "langgraph>=0.2,<1.0" \
        "pwdlib[argon2]>=0.2,<1.0" \
        "pyjwt>=2.9,<3.0" \
        "python-multipart>=0.0.12" \
        "httpx>=0.28" \
        "cryptography>=43.0" \
        "pyodbc>=5.0" \
        "oracledb>=2.0,<3.0" \
        "sqlalchemy-firebird>=2.0" \
        "firebird-driver>=2.0" \
        "fdb>=2.0" \
        "openpyxl>=3.1" \
        "google-auth[requests]>=2.38,<3.0" \
        "litellm>=1.40,<2.0" \
        "structlog>=24.0,<25.0" \
        "tenacity>=9.0,<10.0" \
        "apscheduler>=3.10,<4.0" \
        "prometheus-fastapi-instrumentator>=7.0,<8.0" \
        "slowapi>=0.1.9,<1.0" \
        "langgraph-checkpoint-postgres>=2.0,<3.0" \
        "psycopg[binary,pool]>=3.2,<4.0" \
        "psycopg2-binary>=2.9" \
        "langsmith>=0.1.100,<1.0" \
        "opentelemetry-api>=1.27,<2.0" \
        "opentelemetry-sdk>=1.27,<2.0" \
        "opentelemetry-exporter-otlp-proto-http>=1.27,<2.0" \
        "opentelemetry-instrumentation-fastapi>=0.48b0,<1.0" \
        "opentelemetry-instrumentation-sqlalchemy>=0.48b0,<1.0" \
        "opentelemetry-instrumentation-httpx>=0.48b0,<1.0" \
        "psutil>=5.9,<7.0"

# === Stage 2: runtime ===
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

# Apenas runtime libs — sem -dev, sem build-essential.
# curl: usado pelo healthcheck do compose.
# libfbclient2 (Debian) e Firebird 4.0 — usado pelo firebird-driver (FB 3.0+).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
        libfbclient2 \
        unixodbc \
        curl \
        gnupg \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 shift \
    && useradd --uid 1000 --gid shift --shell /bin/bash --create-home shift

# Microsoft ODBC Driver 17 for SQL Server.
# Necessario para conectar em SQL Server via pyodbc — connection_service.py
# injeta automaticamente "driver=ODBC Driver 17 for SQL Server" na URL.
# A imagem base e Debian 13 (trixie); a Microsoft ainda nao publica pacote
# para trixie, mas o pacote do bookworm (Debian 12) funciona — depende
# apenas de unixodbc e libssl que sao ABI-compativeis.
# ACCEPT_EULA=Y aceita os termos da Microsoft (necessario non-interactive).
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && rm -rf /var/lib/apt/lists/*

# Firebird 2.5 client library — para conectar em servidores legados (ERPs
# antigos tipo Viasoft, Linx ainda rodam FB 2.5). firebird-driver so suporta
# FB 3.0+; para FB 2.5 o app usa o driver fdb (Python) carregando esta lib
# via fb_library_name. A lib traz ICU 3.0 bundled (libicu*.so.30) — nao
# conflita com o ICU moderno do sistema (SONAMEs diferentes).
# RPATH setado via patchelf garante que a lib ache suas deps internas SEM
# precisar de LD_LIBRARY_PATH (que mascararia a libfbclient 4.0 do sistema).
RUN apt-get update && apt-get install -y --no-install-recommends patchelf \
    && curl -fL --retry 3 -o /tmp/fb25.tar.gz \
        "https://github.com/FirebirdSQL/firebird/releases/download/R2_5_9/FirebirdCS-2.5.9.27139-0.amd64.tar.gz" \
    && cd /tmp \
    && tar xzf fb25.tar.gz \
    && cd FirebirdCS-2.5.9.27139-0.amd64 \
    && tar xzf buildroot.tar.gz \
    && mkdir -p /opt/firebird-2.5/lib \
    && cp -d opt/firebird/lib/lib*.so* /opt/firebird-2.5/lib/ \
    && for f in /opt/firebird-2.5/lib/*.so*; do \
         if [ ! -L "$f" ]; then \
             patchelf --set-rpath '/opt/firebird-2.5/lib' "$f" 2>/dev/null || true; \
         fi; \
       done \
    && ln -sf /usr/lib/x86_64-linux-gnu/libncursesw.so.6 /opt/firebird-2.5/lib/libncurses.so.5 \
    && apt-get purge -y patchelf \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/fb25.tar.gz /tmp/FirebirdCS-2.5.9.27139-0.amd64

# Shim para libncurses.so.5 — a libfbclient 2.5 foi compilada na era CentOS
# 5 e linkou contra ncurses 5; Debian 13 so tem ncurses 6. O symlink acima
# (no mesmo RPATH /opt/firebird-2.5/lib) faz o loader achar libncursesw.so.6
# quando algo pede libncurses.so.5 — os simbolos basicos sao ABI-compativeis.

# Copia o virtualenv pronto do builder.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Diretorios persistentes que o codigo espera existir.
# Owners apropriados — o usuario shift escreve nos volumes montados.
#
# /shift-secrets — volume nomeado onde o bootstrap-secrets.py grava
# SECRET_KEY e ENCRYPTION_KEY na primeira subida. Persiste entre
# `docker compose down` e `up` (so e apagado com `down -v`).
RUN mkdir -p /var/lib/shift/checkpoints \
             /var/lib/shift/extract-cache \
             /var/lib/shift/uploads \
             /tmp/streaming-spill \
             /shift-secrets \
    && chown -R shift:shift /var/lib/shift /tmp/streaming-spill /shift-secrets /app

# IMPORTANTE: o usuario shift precisa ser membro do grupo 'docker' do HOST
# para acessar /var/run/docker.sock. O GID do grupo docker varia por distro
# (Ubuntu=999, Debian=998, etc). Usamos 'docker' como nome e mapeamos no
# entrypoint via lookup do GID do socket.
COPY --chown=shift:shift docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --chown=shift:shift bootstrap-secrets.py /usr/local/bin/bootstrap-secrets.py
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/bootstrap-secrets.py

# Codigo da aplicacao — copiado por ultimo para nao invalidar cache acima.
COPY --chown=shift:shift . /app

# --- Segredos embutidos (CI da Shift) ---
# Esses valores sao IGUAIS para todos os clientes (chave da Shift, OAuth
# Client ID da Shift, etc). A CI da Shift recebe-os via secrets do GitHub
# Actions e injeta como --build-arg. O cliente final NUNCA edita nem ve
# essas variaveis no .env — config.py le de /etc/shift/embedded.env como
# uma das fontes de env_file (ver app/core/config.py).
#
# Valores default vazios — em dev local, builds sem secrets resultam em
# arquivo vazio (defaults do config.py prevalecem). Em prod, a CI passa
# todos os build-args.
#
# Build com:
#   docker build \
#     --build-arg LLM_API_KEY="sk-ant-..." \
#     --build-arg GOOGLE_CLIENT_ID="..." \
#     --build-arg RESEND_API_KEY="re_..." \
#     --build-arg EMAIL_FROM="noreply@shift.app" \
#     -t shift-backend:tag .
ARG LLM_API_KEY=""
ARG LLM_REASONING_MODEL=""
ARG GOOGLE_CLIENT_ID=""
ARG RESEND_API_KEY=""
ARG EMAIL_FROM=""
ARG LANGSMITH_API_KEY=""

RUN mkdir -p /etc/shift \
    && printf '# Segredos e configs embutidos no build pela CI da Shift. NAO editar.\n' > /etc/shift/embedded.env \
    && [ -z "$LLM_API_KEY" ]          || printf 'LLM_API_KEY=%s\n'          "$LLM_API_KEY"          >> /etc/shift/embedded.env \
    && [ -z "$LLM_REASONING_MODEL" ]  || printf 'LLM_REASONING_MODEL=%s\n'  "$LLM_REASONING_MODEL"  >> /etc/shift/embedded.env \
    && [ -z "$GOOGLE_CLIENT_ID" ]     || printf 'GOOGLE_CLIENT_ID=%s\n'     "$GOOGLE_CLIENT_ID"     >> /etc/shift/embedded.env \
    && [ -z "$RESEND_API_KEY" ]       || printf 'RESEND_API_KEY=%s\n'       "$RESEND_API_KEY"       >> /etc/shift/embedded.env \
    && [ -z "$EMAIL_FROM" ]           || printf 'EMAIL_FROM=%s\n'           "$EMAIL_FROM"           >> /etc/shift/embedded.env \
    && [ -z "$LANGSMITH_API_KEY" ]    || printf 'LANGSMITH_API_KEY=%s\n'    "$LANGSMITH_API_KEY"    >> /etc/shift/embedded.env \
    && chown -R shift:shift /etc/shift \
    && chmod 640 /etc/shift/embedded.env

EXPOSE 8000

USER shift

# tini reaps zumbis (importante quando o backend spawna sandboxes via Docker API).
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]

# Default: roda migrations e sobe uvicorn em single-worker.
# IMPORTANTE: --workers > 1 quebra APScheduler (cada worker tentaria
# iniciar o scheduler e disparar webhooks duplicados). Para escalar
# horizontalmente, suba multiplos containers — APScheduler+SQLAlchemyJobStore
# coordena via locks no Postgres.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
