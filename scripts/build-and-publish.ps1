<#
.SYNOPSIS
    Build & publish das imagens da Shift no Docker Hub (versao PowerShell).

.DESCRIPTION
    Equivalente do scripts/build-and-publish.sh para Windows nativo (sem
    precisar de Git Bash / WSL). Carrega segredos oficiais de .env.build
    e injeta como --build-arg no docker build do backend.

.PARAMETER Tag
    Tag das imagens. Default: data atual (yyyyMMdd).

.PARAMETER DockerHubUser
    Usuario do Docker Hub. Default: cleberveiga.

.PARAMETER SkipPush
    Se presente, builda localmente mas nao da push.

.EXAMPLE
    .\scripts\build-and-publish.ps1
    .\scripts\build-and-publish.ps1 -Tag 0.2.0
    .\scripts\build-and-publish.ps1 -SkipPush
#>
[CmdletBinding()]
param(
    [string]$Tag = (Get-Date -Format "yyyyMMdd"),
    [string]$DockerHubUser = "cleberveiga",
    [switch]$SkipPush
)

$ErrorActionPreference = 'Stop'

# cd para a raiz do repo (parent do diretorio deste script)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

# --- 1. Carrega .env.build ---
$EnvBuildPath = Join-Path $Root ".env.build"
if (-not (Test-Path $EnvBuildPath)) {
    Write-Error @"
$EnvBuildPath nao existe.
  Copy-Item .env.build.example .env.build
e edite .env.build com as chaves reais.
"@
    exit 1
}

# Parser KEY=VALUE simples (ignora linhas em branco e comentarios)
Get-Content $EnvBuildPath | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }
    if ($_ -match '^\s*([^=]+?)\s*=\s*(.*)$') {
        $key = $matches[1].Trim()
        $val = $matches[2].Trim()
        # Remove aspas circundantes (single ou double)
        if ($val -match '^"(.*)"$' -or $val -match "^'(.*)'$") { $val = $matches[1] }
        Set-Item -Path "Env:$key" -Value $val
    }
}

# Sanity check — pelo menos LLM_API_KEY deve estar setada
if (-not $env:LLM_API_KEY -or $env:LLM_API_KEY -eq "sk-ant-...") {
    Write-Error "LLM_API_KEY nao configurado em .env.build (valor placeholder)."
    exit 1
}

Write-Host "==> Build com TAG=$Tag (user=$DockerHubUser)" -ForegroundColor Cyan

# --- 2. kernel-runtime ---
Write-Host "==> Building kernel-runtime" -ForegroundColor Cyan
docker build `
    -t "$DockerHubUser/shift-kernel-runtime:$Tag" `
    -t "$DockerHubUser/shift-kernel-runtime:latest" `
    (Join-Path $Root "kernel-runtime")
if ($LASTEXITCODE -ne 0) { throw "Build kernel-runtime falhou ($LASTEXITCODE)" }

# --- 3. backend (com segredos embutidos) ---
Write-Host "==> Building shift-backend (segredos embutidos via build-arg)" -ForegroundColor Cyan
$emailFrom = if ($env:EMAIL_FROM) { $env:EMAIL_FROM } else { "noreply@shift.app" }

docker build `
    --build-arg LLM_API_KEY="$env:LLM_API_KEY" `
    --build-arg LLM_REASONING_MODEL="$env:LLM_REASONING_MODEL" `
    --build-arg GOOGLE_CLIENT_ID="$env:GOOGLE_CLIENT_ID" `
    --build-arg RESEND_API_KEY="$env:RESEND_API_KEY" `
    --build-arg EMAIL_FROM="$emailFrom" `
    --build-arg LANGSMITH_API_KEY="$env:LANGSMITH_API_KEY" `
    -t "$DockerHubUser/shift-backend:$Tag" `
    -t "$DockerHubUser/shift-backend:latest" `
    (Join-Path $Root "shift-backend")
if ($LASTEXITCODE -ne 0) { throw "Build shift-backend falhou ($LASTEXITCODE)" }

# --- 4. frontend ---
$frontendApiUrl = if ($env:NEXT_PUBLIC_API_BASE_URL) { $env:NEXT_PUBLIC_API_BASE_URL } else { "http://localhost:8000/api/v1" }
Write-Host "==> Building shift-frontend (NEXT_PUBLIC_API_BASE_URL=$frontendApiUrl)" -ForegroundColor Cyan
docker build `
    --build-arg NEXT_PUBLIC_API_BASE_URL="$frontendApiUrl" `
    -t "$DockerHubUser/shift-frontend:$Tag" `
    -t "$DockerHubUser/shift-frontend:latest" `
    (Join-Path $Root "shift-frontend")
if ($LASTEXITCODE -ne 0) { throw "Build shift-frontend falhou ($LASTEXITCODE)" }

# --- 5. Push ---
if ($SkipPush) {
    Write-Host "==> -SkipPush passado. Build local concluido." -ForegroundColor Yellow
    exit 0
}

Write-Host "==> Pushing imagens" -ForegroundColor Cyan
docker push "$DockerHubUser/shift-kernel-runtime:$Tag"
docker push "$DockerHubUser/shift-kernel-runtime:latest"
docker push "$DockerHubUser/shift-backend:$Tag"
docker push "$DockerHubUser/shift-backend:latest"
docker push "$DockerHubUser/shift-frontend:$Tag"
docker push "$DockerHubUser/shift-frontend:latest"

Write-Host "==> Concluido. Verifique em https://hub.docker.com/u/$DockerHubUser" -ForegroundColor Green
