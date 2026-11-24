# dev.ps1 — PaliMind dev launcher (Windows)
# Run from the repo root with: .\dev.ps1

# 1. Kill any stale palimind.exe (releases the exe lock)
Write-Host "[dev] Killing stale palimind process..." -ForegroundColor Yellow
Stop-Process -Name "palimind" -Force -ErrorAction SilentlyContinue
# Also reap orphaned Python backends from a previous crashed session.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*palimind.api_server*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 600

# Cap glibc-equivalent arena growth for the threaded backend.
$env:MALLOC_ARENA_MAX = "4"

# 2. Start Python backend in background (venv python, correct CWD)
$backendRoot = Join-Path $PSScriptRoot "packages\backend"
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
Write-Host "[dev] Starting Python backend..." -ForegroundColor Yellow
$backend = Start-Process -FilePath $python `
    -ArgumentList "-m", "palimind.api_server" `
    -WorkingDirectory $backendRoot `
    -PassThru -WindowStyle Hidden
Write-Host "[dev] Backend PID: $($backend.Id)"

# 3. Launch tauri dev and always clean up, even if it exits non-zero.
try {
    Write-Host "[dev] Starting tauri dev..." -ForegroundColor Green
    npm run dev --prefix apps/desktop
} finally {
    if ($backend -and -not $backend.HasExited) {
        # /T kills the whole tree; Python may have spawned workers.
        & taskkill /T /F /PID $backend.Id 2>$null | Out-Null
    }
    Write-Host "[dev] Backend stopped."
}
