#!/usr/bin/env pwsh
# scripts/tauri-dev-backend.ps1 - Idempotently start the FastAPI dev backend for Tauri.

param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot

function Test-BackendReady {
    param([int]$ProbePort)
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$ProbePort/health" -TimeoutSec 2 -ErrorAction Stop
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-BackendReady -ProbePort $Port) {
    Write-Host "Palimind backend already running on http://127.0.0.1:$Port/ui/"
    exit 0
}

$Python = $null
foreach ($candidate in @("$RootDir\.venv\Scripts\python.exe", "python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $Python = $candidate
        break
    }
}
if (-not $Python) {
    Write-Host "ERROR: Python not found. Create/activate .venv or install Python." -ForegroundColor Red
    exit 1
}

Write-Host "Checking Python packages..."
& "$PSScriptRoot\ensure-python-deps.ps1" -Python $Python -RootDir $RootDir

Write-Host "Starting Palimind backend on http://127.0.0.1:$Port/ui/"
$BackendJob = Start-Process -PassThru -WindowStyle Hidden `
    -FilePath $Python `
    -ArgumentList "$RootDir\server_entry.py", "--host", "127.0.0.1", "--port", $Port `
    -WorkingDirectory $RootDir

for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if (Test-BackendReady -ProbePort $Port) {
        Write-Host "Palimind backend ready. PID: $($BackendJob.Id)"
        exit 0
    }
}

Write-Host "ERROR: Backend did not become healthy within 45 seconds." -ForegroundColor Red
Stop-Process -Id $BackendJob.Id -Force -ErrorAction SilentlyContinue
exit 1
