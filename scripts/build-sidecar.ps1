#!/usr/bin/env pwsh
# scripts/build-sidecar.ps1 - Build the PyInstaller sidecar binary
#
# Run this before `cargo tauri build` to produce the sidecar .exe
# Output: dist/palimind-server/ + copied to src-tauri/binaries/
#
# Usage:  .\scripts\build-sidecar.ps1
 
param(
    [switch]$Clean   # Force clean build (removes dist/ first)
)
 
$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
 
Write-Host ""
Write-Host "  Palimind Sidecar Build" -ForegroundColor Cyan
Write-Host "  ----------------------" -ForegroundColor DarkGray
Write-Host ""

# ──────────────────────────────────────────────────────────────────────────────
$TargetTriple = (rustc -Vv | Select-String "host:").ToString().Split(":")[1].Trim()
Write-Host "  Target triple: $TargetTriple" -ForegroundColor DarkGray

# ── Find Python ───────────────────────────────────────────────────────────────
$Python = $null
foreach ($candidate in @("$RootDir\.venv\Scripts\python.exe", "python")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $Python = $candidate; break
    }
}
if (-not $Python) {
    Write-Host "  ERROR: Python not found. Activate your venv first." -ForegroundColor Red
    exit 1
}

# ── Ensure Python dependencies are installed ─────────────────────────────────
Write-Host "  [1/4] Checking Python packages..." -ForegroundColor Green
& "$PSScriptRoot\ensure-python-deps.ps1" -Python $Python -RootDir $RootDir -IncludeBuild

# ── Clean previous build ──────────────────────────────────────────────────────
if ($Clean -and (Test-Path "$RootDir\dist\palimind-server")) {
    Write-Host "  [2/4] Cleaning previous build..." -ForegroundColor Green
    Remove-Item -Recurse -Force "$RootDir\dist\palimind-server"
}

# ── Run PyInstaller ───────────────────────────────────────────────────────────
Write-Host "  [2/4] Running PyInstaller (this takes 2-5 minutes)..." -ForegroundColor Green
Set-Location $RootDir
& $Python -m PyInstaller palimind.spec --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: PyInstaller build failed." -ForegroundColor Red; exit 1
}

# ── Copy to src-tauri/binaries/ ───────────────────────────────────────────────
Write-Host "  [3/4] Copying sidecar to src-tauri/binaries/..." -ForegroundColor Green
$SrcExe  = "$RootDir\dist\palimind-server.exe"
$DestDir = "$RootDir\src-tauri\binaries"
$DestExe = "$DestDir\palimind-server-$TargetTriple.exe"

New-Item -ItemType Directory -Path $DestDir -Force | Out-Null

if (-not (Test-Path $SrcExe)) {
    Write-Host "  ERROR: Built exe not found at $SrcExe" -ForegroundColor Red; exit 1
}
Copy-Item $SrcExe $DestExe -Force

# ── Verify ────────────────────────────────────────────────────────────────────
Write-Host "  [4/4] Verifying binary..." -ForegroundColor Green
$testOutput = & $DestExe --help 2>&1
if ($LASTEXITCODE -ne 0 -and -not ($testOutput -match "usage|port")) {
    Write-Host "  WARNING: Binary may not be functional. Check manually." -ForegroundColor Yellow
} else {
    Write-Host "  OK: Sidecar binary OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Sidecar ready: $DestExe" -ForegroundColor Cyan
Write-Host "  Next step: npm run build:tauri" -ForegroundColor DarkGray
Write-Host ""
