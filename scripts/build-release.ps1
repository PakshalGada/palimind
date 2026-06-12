#!/usr/bin/env pwsh
# scripts/build-release.ps1 - Build the sidecar and Tauri desktop bundle.

param(
    [switch]$SkipSidecar
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$VcVars = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

function Test-WindowsNativeToolchain {
    if (-not (Test-Path $VcVars)) {
        Write-Host "ERROR: Visual Studio Build Tools C++ workload is not installed." -ForegroundColor Red
        Write-Host "Install 'Desktop development with C++' for Tauri/Rust builds." -ForegroundColor DarkGray
        exit 1
    }

    $KernelLib = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\Lib" `
        -Recurse -Filter kernel32.* -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -ilike "*\um\x64\kernel32.lib" } |
        Select-Object -First 1

    if (-not $KernelLib) {
        Write-Host "ERROR: Windows 10/11 SDK libraries were not found (kernel32.lib missing)." -ForegroundColor Red
        Write-Host "Install the Windows SDK component in Visual Studio Build Tools." -ForegroundColor DarkGray
        exit 1
    }
}

Write-Host ""
Write-Host "  Palimind Desktop Release Build" -ForegroundColor Cyan
Write-Host "  ------------------------------" -ForegroundColor DarkGray
Write-Host ""

Test-WindowsNativeToolchain

if (-not $SkipSidecar) {
    & "$PSScriptRoot\build-sidecar.ps1"
}

Set-Location "$RootDir"
& cmd.exe /d /s /c "`"$VcVars`" >NUL && npx @tauri-apps/cli build"
