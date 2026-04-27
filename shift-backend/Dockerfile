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
        "sqlalchemy-firebird>=2.0" \
        "firebird-driver>=2.0" \
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
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
        libfbclient2 \
        unixodbc \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 shift \
    && useradd --uid 1000 --gid shift --shell /bin/bash --create-home shift

# Copia o virtualenv pronto do builder.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Diretorios persistentes que o codigo espera existir.
# Owners apropriados — o usuario shift escreve nos volumes montados.
RUN mkdir -p /var/lib/shift/checkpoints \
             /var/lib/shift/extract-cache \
             /var/lib/shift/uploads \
             /tmp/streaming-spill \
    && chown -R shift:shift /var/lib/shift /tmp/streaming-spill /app

# IMPORTANTE: o usuario shift precisa ser membro do grupo 'docker' do HOST
# para acessar /var/run/docker.sock. O GID do grupo docker varia por distro
# (Ubuntu=999, Debian=998, etc). Usamos 'docker' como nome e mapeamos no
# entrypoint via lookup do GID do socket.
COPY --chown=shift:shift docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Codigo da aplicacao — copiado por ultimo para nao invalidar cache acima.
COPY --chown=shift:shift . /app

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
