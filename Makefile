# Atalhos operacionais para o stack Docker Compose do Shift.
#
# Uso:
#   make help           lista alvos
#   make build          builda kernel-runtime + backend + frontend
#   make up             sobe tudo
#   make logs           logs combinados
#   make migrate        roda alembic upgrade head
#   make shell          shell no backend
#   make test-stack     smoke test (health, metrics, prom, grafana)

SHELL := /bin/bash
COMPOSE := docker compose

# Carrega .env automaticamente para alvos que precisam ler vars
# (ex: $(DATABASE_URL) em shell-db / db-bootstrap).
ifneq (,$(wildcard ./.env))
	include .env
	export
endif

.DEFAULT_GOAL := help
# Wrapper para o modo prod-like (ignora docker-compose.override.yml).
COMPOSE_PROD := docker compose -f docker-compose.yml

.PHONY: help build build-kernel up up-fg up-prod down down-prod down-volumes \
        restart logs logs-backend logs-frontend logs-prod ps ps-prod \
        migrate migrate-revision shell shell-db db-bootstrap \
        prewarm-check test-stack clean reset

help: ## Lista comandos disponiveis
	@echo Shift — comandos disponiveis:
	@echo   --- Build ---
	@echo   make build           Build de todas as imagens (kernel + backend + frontend)
	@echo   make build-kernel    Build apenas da imagem da sandbox
	@echo   --- Up / Down (DEV) ---
	@echo   make up              Sobe stack em DEV (carrega override.yml — hot-reload)
	@echo   make up-fg           Sobe em foreground (Ctrl+C derruba)
	@echo   make down            Para containers DEV (preserva volumes)
	@echo   make down-volumes    Para tudo E APAGA volumes locais
	@echo   make restart         Restart rapido
	@echo   --- Up / Down (PROD-like) ---
	@echo   make up-prod         Sobe sem override.yml + rebuild
	@echo   make down-prod       Para o stack prod-like
	@echo   make logs-prod       Tail dos logs do stack prod-like
	@echo   make ps-prod         Status (modo prod-like)
	@echo   --- Logs / Status ---
	@echo   make logs            Tail dos logs de todos os services
	@echo   make logs-backend    Tail do backend
	@echo   make logs-frontend   Tail do frontend
	@echo   make ps              Status (modo DEV)
	@echo   --- Banco em nuvem ---
	@echo   make db-bootstrap    Aplica pgcrypto no banco em nuvem (UMA vez)
	@echo   make migrate         Roda alembic upgrade head
	@echo   make migrate-revision MSG="..."  Cria nova revisao Alembic
	@echo   make shell-db        psql contra o Postgres em nuvem
	@echo   --- Diagnostico ---
	@echo   make shell           Bash dentro do backend
	@echo   make prewarm-check   Verifica sandbox pool
	@echo   make test-stack      Smoke test (health, prom, grafana)
	@echo   --- Manutencao ---
	@echo   make clean           Remove imagens dangling
	@echo   make reset           Nuke + rebuild + up + migrate

build: build-kernel ## Build de todas as imagens (kernel-runtime + backend + frontend)
	$(COMPOSE) build

build-kernel: ## Builda apenas a imagem da sandbox (shift-kernel-runtime:latest)
	$(COMPOSE) --profile build build kernel-runtime-builder

up: ## Sobe o stack em DEV (carrega docker-compose.override.yml — hot-reload)
	$(COMPOSE) up -d
	@echo Stack subindo em modo DEV (override.yml ativo).
	@echo Verifique com: make ps
	@echo Acompanhe o boot com: make logs-backend

up-fg: ## Sobe em foreground modo DEV (Ctrl+C derruba)
	$(COMPOSE) up

up-prod: ## Sobe o stack em PROD-like (ignora override.yml, rebuilda)
	$(COMPOSE_PROD) up -d --build
	@echo Stack subindo em modo PROD-like (override.yml ignorado).
	@echo Verifique com: make ps-prod
	@echo Acompanhe o boot com: make logs-prod

down: ## Para containers DEV (preserva volumes)
	$(COMPOSE) down

down-prod: ## Para containers PROD-like
	$(COMPOSE_PROD) down

down-volumes: ## Para tudo E APAGA volumes locais (Grafana/Prom/Tempo). NAO toca o banco em nuvem.
	$(COMPOSE) down -v

restart: ## Restart rapido de todos os services
	$(COMPOSE) restart

logs: ## Tail dos logs de todos os services
	$(COMPOSE) logs -f --tail=200

logs-backend: ## Tail dos logs do backend
	$(COMPOSE) logs -f --tail=200 shift-backend

logs-frontend: ## Tail dos logs do frontend
	$(COMPOSE) logs -f --tail=200 shift-frontend

logs-prod: ## Tail dos logs do stack PROD-like
	$(COMPOSE_PROD) logs -f --tail=200

ps: ## Status dos containers (modo DEV)
	$(COMPOSE) ps

ps-prod: ## Status dos containers (modo PROD-like)
	$(COMPOSE_PROD) ps

migrate: ## Roda alembic upgrade head
	$(COMPOSE) exec shift-backend alembic upgrade head

migrate-revision: ## Cria nova revisao Alembic (use MSG="descricao")
	$(COMPOSE) exec shift-backend sh -c 'test -n "$(MSG)" || { echo "Use: make migrate-revision MSG=\"descricao\""; exit 1; }; alembic revision --autogenerate -m "$(MSG)"'

shell: ## Shell no container do backend
	$(COMPOSE) exec shift-backend bash

shell-db: ## psql contra o Postgres em nuvem (usa DATABASE_URL do .env)
	$(COMPOSE) exec shift-backend sh -c 'test -n "$$DATABASE_URL" || { echo "DATABASE_URL nao setado dentro do container"; exit 1; }; psql "$$(echo $$DATABASE_URL | sed "s|postgresql+asyncpg://|postgresql://|")"'

db-bootstrap: ## Aplica ops/postgres/bootstrap.sql no banco em nuvem (UMA vez)
	docker run --rm -v "$(CURDIR)/ops/postgres:/bootstrap:ro" -e DATABASE_URL="$(DATABASE_URL)" postgres:16-alpine sh -c 'test -n "$$DATABASE_URL" || { echo "DATABASE_URL nao setado em .env"; exit 1; }; psql "$$(echo $$DATABASE_URL | sed "s|postgresql+asyncpg://|postgresql://|")" -f /bootstrap/bootstrap.sql'

prewarm-check: ## Verifica se o sandbox pool esta pre-aquecido
	@echo Containers warm de sandbox:
	docker ps --filter "ancestor=shift-kernel-runtime:latest" --format "  {{.ID}}  {{.Status}}"
	@echo Metrica sandbox_pool_*:
	$(COMPOSE) exec -T shift-backend sh -c "curl -sf http://localhost:8000/metrics | grep -E '^sandbox_pool_(idle|in_use|max_size)' || echo '(metrica ausente — pool desabilitado ou cold path)'"

test-stack: ## Smoke test (variaveis vem do .env via include no topo deste Makefile)
	@echo Backend health:
	curl -fsS http://localhost:$(BACKEND_PORT)/health
	@echo .
	@echo Backend docs (HTTP code):
	curl -sI http://localhost:$(BACKEND_PORT)/docs
	@echo Prometheus:
	curl -fsS http://localhost:$(PROMETHEUS_PORT)/-/healthy
	@echo .
	@echo Grafana:
	curl -fsS http://localhost:$(GRAFANA_PORT)/api/health
	@echo .

clean: ## Remove imagens dangling e build cache
	docker image prune -f
	docker builder prune -f

reset: down-volumes build up migrate ## Reset full: down -v, rebuild, up, migrate
	@echo ""
	@echo "ATENCAO: o banco em NUVEM nao e tocado por este reset."
	@echo "Para apagar dados no banco, faca via console do provider."
