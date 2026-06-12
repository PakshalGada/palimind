# scripts/dev.ps1 - Start Palimind in development mode
#
# This script starts both the Python backend and the Tauri dev shell.
# No PyInstaller build needed for development.
#
# Usage:  .\scripts\dev.ps1
#         .\scripts\dev.ps1 -Port 8001

param(
    [int]$Port = 8000,
    [switch]$NoTauri   # Use this to only start the backend (for browser testing)
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$VcVars = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

function Test-WindowsNativeToolchain {
    if (-not (Test-Path $VcVars)) {
        Write-Host "  ERROR: Visual Studio Build Tools C++ workload is not installed." -ForegroundColor Red
        Write-Host "         Install 'Desktop development with C++' for Tauri/Rust builds." -ForegroundColor DarkGray
        exit 1
    }

    $KernelLib = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\Lib" `
        -Recurse -Filter kernel32.* -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -ilike "*\um\x64\kernel32.lib" } |
        Select-Object -First 1

    if (-not $KernelLib) {
        Write-Host "  ERROR: Windows 10/11 SDK libraries were not found (kernel32.lib missing)." -ForegroundColor Red
        Write-Host "         Install the Windows SDK component in Visual Studio Build Tools." -ForegroundColor DarkGray
        exit 1
    }
}

Write-Host ""
Write-Host "  Palimind Dev Mode" -ForegroundColor Cyan
Write-Host "  -----------------" -ForegroundColor DarkGray
Write-Host ""

# ── 1. Find Python ────────────────────────────────────────────────────────────
$Python = $null
foreach ($candidate in @("$RootDir\.venv\Scripts\python.exe", "python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $Python = $candidate
        break
    }
}
if (-not $Python) {
    Write-Host "  ERROR: Python not found. Activate your venv first." -ForegroundColor Red
    exit 1
}

Write-Host "  [1/4] Checking Python packages..." -ForegroundColor Green
& "$PSScriptRoot\ensure-python-deps.ps1" -Python $Python -RootDir $RootDir

Write-Host "  [2/4] Starting FastAPI backend on port $Port..." -ForegroundColor Green
$env:PALIMIND_DEV_PORT = $Port
$BackendJob = Start-Process -PassThru -NoNewWindow `
    -FilePath $Python `
    -ArgumentList "$RootDir\server_entry.py", "--host", "127.0.0.1", "--port", $Port `
    -WorkingDirectory $RootDir

Write-Host "        PID: $($BackendJob.Id)" -ForegroundColor DarkGray

# ── 2. Wait for backend to be healthy ────────────────────────────────────────
Write-Host "  [3/4] Waiting for backend..." -ForegroundColor Green
$healthUrl = "http://127.0.0.1:$Port/health"
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Write-Host "        Waiting... ($($i+1)/30)" -ForegroundColor DarkGray
}

if (-not $ready) {
    Write-Host "  ERROR: Backend did not start within 30 seconds." -ForegroundColor Red
    Stop-Process -Id $BackendJob.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "        Backend ready at http://127.0.0.1:$Port/ui/" -ForegroundColor DarkGray

# ── 3. Start Tauri dev (or just open browser) ─────────────────────────────────
if ($NoTauri) {
    Write-Host "  [4/4] Opening browser (no Tauri mode)..." -ForegroundColor Green
    Start-Process "http://127.0.0.1:$Port/ui/"
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop the backend." -ForegroundColor Yellow
    Wait-Process -Id $BackendJob.Id
} else {
    Write-Host "  [4/4] Starting Tauri dev shell..." -ForegroundColor Green
    Write-Host "        (Hot reload active for Rust changes)" -ForegroundColor DarkGray
    Write-Host ""

    Set-Location "$RootDir"
    try {
        # Pass the port so Tauri dev knows where the backend is
        Test-WindowsNativeToolchain
        & cmd.exe /d /s /c "`"$VcVars`" >NUL && npx @tauri-apps/cli dev"
    } finally {
        # Cleanup backend when Tauri exits
        Write-Host "`n  Stopping backend..." -ForegroundColor Yellow
        Stop-Process -Id $BackendJob.Id -Force -ErrorAction SilentlyContinue
    }
}
