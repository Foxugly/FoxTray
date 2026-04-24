$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python virtualenv not found: $python"
}

Write-Host "Cleaning build artifacts..."
if (Test-Path "build") {
    Remove-Item "build" -Recurse -Force
}
if (Test-Path "dist") {
    Remove-Item "dist" -Recurse -Force
}

Write-Host "Running tests..."
& $python -m pytest

Write-Host "Building executable..."
& $python -m PyInstaller "foxtray.spec" -y

$distDir = Join-Path $repoRoot "dist"
$configPath = Join-Path $distDir "config.yaml"
$exampleConfig = Join-Path $repoRoot "config.example.yaml"
if (-not (Test-Path $configPath) -and (Test-Path $exampleConfig)) {
    Copy-Item $exampleConfig $configPath
}

Write-Host ""
Write-Host "Build complete."
Write-Host "Executable : $distDir\FoxTray.exe"
Write-Host "Config     : $configPath"
Write-Host "Bootstrap log candidates:"
Write-Host "  1. $distDir\bootstrap.log"
Write-Host "  2. $env:APPDATA\foxtray\logs\bootstrap.log"
Write-Host "  3. $env:TEMP\foxtray\bootstrap.log"
