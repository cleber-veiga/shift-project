# =====================================================
#  Shift Backend - Makefile
#  Uso: make <target>
#  Requer: make (choco install make)
# =====================================================

.PHONY: help setup db migrate start stop prefect init-prefect worker api

VENV     = venv
PYTHON   = $(VENV)/Scripts/python
PIP      = $(VENV)/Scripts/pip
ALEMBIC  = $(VENV)/Scripts/alembic
UVICORN  = $(VENV)/Scripts/uvicorn

help:
	@echo Shift Backend - Comandos disponiveis:
	@echo   make setup         - Cria venv e instala dependencias
	@echo   make db            - Aplica migracoes Alembic
	@echo   make migrate       - Gera nova migracao (msg="descricao")
	@echo   make start         - Inicia todos os servicos
	@echo   make stop          - Encerra todos os servicos
	@echo   make prefect       - Inicia servidor Prefect
	@echo   make init-prefect  - Cria pool e deployment (rodar uma vez)
	@echo   make worker        - Inicia worker Prefect
	@echo   make api           - Inicia API FastAPI

setup:
	python -m venv $(VENV)
	$(PIP) install "prefect==3.0.4" "pydantic==2.10.6" --quiet
	$(PIP) install -e . --quiet
	@if not exist .env copy .env.example .env

db:
	$(ALEMBIC) upgrade head

migrate:
	$(ALEMBIC) revision --autogenerate -m "$(msg)"
	$(ALEMBIC) upgrade head

prefect:
	$(VENV)/Scripts/prefect server start

init-prefect:
	$(PYTHON) scripts/init_prefect.py

worker:
	$(PYTHON) scripts/serve_worker.py

api:
	$(UVICORN) main:app --reload --port 8000

# Delega ao script PowerShell para abrir janelas separadas
start:
	powershell -ExecutionPolicy Bypass -File start.ps1

stop:
	powershell -ExecutionPolicy Bypass -File stop.ps1
