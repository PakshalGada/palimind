# dev.ps1 — PaliMind dev launcher
# Run this from e:\palimind-backup\ with: .\dev.ps1

# 1. Kill any stale palimind.exe (releases the exe lock)
Write-Host "[dev] Killing stale palimind process..." -ForegroundColor Yellow
Stop-Process -Name "palimind" -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600

# 2. Start Python backend in background (venv python, correct CWD)
Write-Host "[dev] Starting Python backend..." -ForegroundColor Yellow
$backend = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "core.api_server" `
    -WorkingDirectory $PSScriptRoot `
    -PassThru -WindowStyle Hidden
Write-Host "[dev] Backend PID: $($backend.Id)"

# 3. Launch cargo tauri dev
Write-Host "[dev] Starting cargo tauri dev..." -ForegroundColor Green
Set-Location src-tauri
cargo tauri dev

# 4. Cleanup backend on exit
Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
Write-Host "[dev] Backend stopped."
