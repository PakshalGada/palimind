#!/usr/bin/env pwsh
# scripts/ensure-python-deps.ps1 - Check project Python imports and install missing packages together.

param(
    [Parameter(Mandatory = $true)]
    [string]$Python,

    [Parameter(Mandatory = $true)]
    [string]$RootDir,

    [switch]$IncludeBuild,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    Write-Host "  ERROR: Python not found: $Python" -ForegroundColor Red
    exit 1
}

$includeBuildValue = if ($IncludeBuild) { "true" } else { "false" }
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$probeOutput = & $Python "$PSScriptRoot\check_python_deps.py" $RootDir $includeBuildValue 2>&1
$probeExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($probeExitCode -ne 0) {
    Write-Host "  ERROR: Could not inspect Python dependencies." -ForegroundColor Red
    foreach ($line in $probeOutput) {
        $text = [string]$line
        if ($text -and $text -notlike "*System.Management.Automation.RemoteException*") {
            Write-Host "         $text" -ForegroundColor DarkGray
        }
    }
    Write-Host "         Make sure the selected Python can run, or recreate .venv." -ForegroundColor DarkGray
    exit 1
}

$missingJson = ($probeOutput | Select-Object -Last 1)
$parsedMissing = $missingJson | ConvertFrom-Json
$missing = @()
foreach ($pkg in $parsedMissing) {
    $missing += [string]$pkg
}
if ($missing.Count -eq 0) {
    Write-Host "        Python packages OK" -ForegroundColor DarkGray
    exit 0
}

Write-Host "        Missing Python packages:" -ForegroundColor Yellow
foreach ($pkg in $missing) {
    Write-Host "          - $pkg" -ForegroundColor DarkGray
}

if ($DryRun) {
    Write-Host "        Dry run: skipping install." -ForegroundColor DarkGray
    exit 0
}

Write-Host "        Installing missing packages in one pip run..." -ForegroundColor Yellow
& $Python -m pip install @missing
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Failed to install one or more Python packages." -ForegroundColor Red
    Write-Host "         Re-run the command after checking your internet connection and compiler toolchain." -ForegroundColor DarkGray
    exit 1
}

Write-Host "        Python packages installed" -ForegroundColor Green
