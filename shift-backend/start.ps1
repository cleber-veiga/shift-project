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
    Write-Host "[1/3] Criando ambiente virtual..." -ForegroundColor Yellow
    python -m venv $Venv

    Write-Host "[2/3] Instalando dependencias base..." -ForegroundColor Yellow
    & $Pip install "prefect==3.0.4" "pydantic==2.10.6" --quiet

    Write-Host "[3/3] Instalando projeto..." -ForegroundColor Yellow
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

# --- 1. Prefect Server ---
Write-Host "[1/3] Iniciando Prefect Server..." -ForegroundColor Yellow
$cmd1 = "Set-Location '$Root'; .\venv\Scripts\Activate.ps1; prefect server start"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd1 -WindowStyle Normal

Write-Host "  Aguardando Prefect subir (12s)..." -ForegroundColor DarkGray
Start-Sleep -Seconds 12

# --- 2. Prefect Worker ---
Write-Host "[2/3] Iniciando Prefect Worker..." -ForegroundColor Yellow
$workerScript = Join-Path $Root "scripts\serve_worker.py"
$cmd2 = "Set-Location '$Root'; .\venv\Scripts\Activate.ps1; prefect config set PREFECT_API_URL=http://127.0.0.1:4200/api; python '$workerScript'"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd2 -WindowStyle Normal

Write-Host "  Aguardando worker registrar (6s)..." -ForegroundColor DarkGray
Start-Sleep -Seconds 6

# --- 3. FastAPI ---
Write-Host "[3/3] Iniciando API FastAPI..." -ForegroundColor Yellow
$cmd3 = "Set-Location '$Root'; .\venv\Scripts\Activate.ps1; uvicorn main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd3 -WindowStyle Normal

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  Todos os servicos iniciados!" -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  Prefect UI  -> http://localhost:4200" -ForegroundColor White
Write-Host "  API Docs    -> http://localhost:8000/docs" -ForegroundColor White
Write-Host "  API Health  -> http://localhost:8000/health" -ForegroundColor White
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""
