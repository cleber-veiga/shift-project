#!/usr/bin/env bash
# Roda a suite de testes Firebird (-m firebird) em ambiente local.
#
# Substitui CI: este projeto nao tem GitHub Actions, entao este script
# centraliza o comando que valida regressoes na camada Firebird antes de
# merge na main.
#
# Pre-requisitos:
#   - Docker daemon acessivel
#   - Imagens jacobalberty/firebird:2.5-ss e :v3.0.10 (puxadas
#     automaticamente pela primeira execucao)
#   - Python 3.12+ com extras [dev] do shift-backend instalados
#
# Uso:
#   ./scripts/run-firebird-tests.sh                # toda a suite
#   ./scripts/run-firebird-tests.sh -k bundled     # subset
#   ./scripts/run-firebird-tests.sh --pdb          # debug em falhas

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/shift-backend"

if [[ ! -d "$BACKEND_DIR" ]]; then
    echo "Erro: shift-backend/ nao encontrado em $REPO_ROOT" >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "Erro: 'docker' nao encontrado no PATH." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Erro: daemon Docker nao esta acessivel (verifique se Docker Desktop esta rodando)." >&2
    exit 1
fi

cd "$BACKEND_DIR"

# Instala deps de dev (idempotente — pip detecta que ja esta instalado).
echo "==> Instalando dependencias [dev]..."
pip install -e ".[dev]" --quiet

echo "==> Rodando suite Firebird (-m firebird)..."
echo
exec pytest -m firebird --tb=short -v "$@"
