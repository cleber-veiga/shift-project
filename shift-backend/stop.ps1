# Shift Backend - Encerra todos os servicos
# Uso: .\stop.ps1

Write-Host ""
Write-Host "  SHIFT BACKEND - Encerrando servicos..." -ForegroundColor Cyan
Write-Host ""

$stopped = 0

function Stop-ByCommandLine {
    param([string]$Label, [string]$Pattern)

    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $Pattern
    }

    if ($processes) {
        foreach ($proc in $processes) {
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
                Write-Host "  [OK] $Label encerrado (PID $($proc.ProcessId))" -ForegroundColor Green
                $script:stopped++
            } catch {
                Write-Host "  [ERRO] Nao foi possivel encerrar $Label (PID $($proc.ProcessId))" -ForegroundColor Red
            }
        }
    }
}

# Uvicorn (FastAPI)
Stop-ByCommandLine -Label "FastAPI / uvicorn" -Pattern "uvicorn"

# Prefect worker (serve_worker.py)
Stop-ByCommandLine -Label "Prefect Worker" -Pattern "serve_worker"

# Prefect server
Stop-ByCommandLine -Label "Prefect Server" -Pattern "prefect.*server|prefect_server"

# Processos Python restantes do projeto (fallback)
Stop-ByCommandLine -Label "Python (shift-backend)" -Pattern "shift-backend.*python|python.*shift-backend"

Write-Host ""
if ($stopped -gt 0) {
    Write-Host "  $stopped processo(s) encerrado(s)." -ForegroundColor Green
} else {
    Write-Host "  Nenhum servico do Shift estava rodando." -ForegroundColor Yellow
}
Write-Host ""
