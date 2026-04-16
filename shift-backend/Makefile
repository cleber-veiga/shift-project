# =====================================================
#  Shift Backend - Makefile
#  Uso: make <target>
#  Requer: make (choco install make)
# =====================================================

.PHONY: help setup db migrate start stop api

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
	@echo   make api           - Inicia API FastAPI

setup:
	python -m venv $(VENV)
	$(PIP) install -e . --quiet
	@if not exist .env copy .env.example .env

db:
	$(ALEMBIC) upgrade head

migrate:
	$(ALEMBIC) revision --autogenerate -m "$(msg)"
	$(ALEMBIC) upgrade head

api:
	$(UVICORN) main:app --reload --port 8000

# Delega ao script PowerShell para abrir janelas separadas
start:
	powershell -ExecutionPolicy Bypass -File start.ps1

stop:
	powershell -ExecutionPolicy Bypass -File stop.ps1
