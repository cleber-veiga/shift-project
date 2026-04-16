# Shift Backend - Script de inicializacao completa
# Uso: .\start.ps1 [-Setup] [-Migrate]

param(
    [switch]$Setup,
    [switch]$Migrate
)

$Root    = $PSScriptRoot
$Venv    = Join-Path $Root "venv"
$Python  = Join-Path $Venv "Scripts\python.exe"
$Pip     = Join-Path $Venv "Scripts\pip.exe"
$Alembic = Join-Path $Venv "Scripts\alembic.exe"

Write-Host ""
Write-Host "  SHIFT BACKEND" -ForegroundColor Cyan
Write-Host ""

# --- Setup ---
if ($Setup) {
    Write-Host "[1/2] Criando ambiente virtual..." -ForegroundColor Yellow
    python -m venv $Venv

    Write-Host "[2/2] Instalando projeto..." -ForegroundColor Yellow
    & $Pip install -e $Root --quiet

    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $Root ".env.example") $envFile
        Write-Host "  .env criado - configure suas credenciais!" -ForegroundColor Yellow
    }

    Write-Host "Setup concluido! Rode .\start.ps1 -Migrate e depois .\start.ps1" -ForegroundColor Green
    exit 0
}

# --- Migrate ---
if ($Migrate) {
    if (-not (Test-Path $Python)) {
        Write-Host "ERRO: venv nao encontrado. Rode .\start.ps1 -Setup primeiro." -ForegroundColor Red
        exit 1
    }
    Write-Host "Aplicando migracoes Alembic..." -ForegroundColor Yellow
    Set-Location $Root
    & $Alembic upgrade head
    Write-Host "Banco de dados atualizado!" -ForegroundColor Green
    exit 0
}

# --- Validacoes ---
if (-not (Test-Path $Python)) {
    Write-Host "ERRO: venv nao encontrado. Rode .\start.ps1 -Setup primeiro." -ForegroundColor Red
    exit 1
}

$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Root ".env.example") $envFile
    Write-Host ".env criado a partir do .env.example - configure as credenciais!" -ForegroundColor Yellow
}

# --- FastAPI ---
Write-Host "Iniciando API FastAPI..." -ForegroundColor Yellow
$cmd = "Set-Location '$Root'; .\venv\Scripts\Activate.ps1; uvicorn main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd -WindowStyle Normal

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  Servico iniciado!" -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  API Docs    -> http://localhost:8000/docs" -ForegroundColor White
Write-Host "  API Health  -> http://localhost:8000/health" -ForegroundColor White
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""
