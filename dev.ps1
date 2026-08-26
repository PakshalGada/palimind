# dev.ps1 — PaliMind dev launcher (Windows)
# Run from the repo root with: .\dev.ps1

# 1. Kill any stale palimind.exe (releases the exe lock)
Write-Host "[dev] Killing stale palimind process..." -ForegroundColor Yellow
Stop-Process -Name "palimind" -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600

# 2. Start Python backend in background (venv python, correct CWD)
$backendRoot = Join-Path $PSScriptRoot "packages\backend"
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
Write-Host "[dev] Starting Python backend..." -ForegroundColor Yellow
$backend = Start-Process -FilePath $python `
    -ArgumentList "-m", "palimind.api_server" `
    -WorkingDirectory $backendRoot `
    -PassThru -WindowStyle Hidden
Write-Host "[dev] Backend PID: $($backend.Id)"

# 3. Launch tauri dev
Write-Host "[dev] Starting tauri dev..." -ForegroundColor Green
npm run dev --prefix apps/desktop

# 4. Cleanup backend on exit
Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
Write-Host "[dev] Backend stopped."
