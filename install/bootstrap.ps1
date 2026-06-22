#Requires -Version 5.1
<#
.SYNOPSIS
    Metronix Core installer entry point for Windows (PowerShell).

.DESCRIPTION
    Windows counterpart to bootstrap.sh. Installs uv if missing,
    checks Docker availability, then launches the Python installer
    from the installer/ directory.

.EXAMPLE
    .\install\bootstrap.ps1
    .\install\bootstrap.ps1 -NonInteractive
    .\install\bootstrap.ps1 -DryRun
    .\install\bootstrap.ps1 -Config answers.yaml
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$InstallerDir = Join-Path $RepoRoot "installer"

# Install uv if not present.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# --- Docker pre-check: detect, offer to download, verify daemon ---

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "Docker is required to run Metronix Core but was not found." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Docker Desktop can be downloaded from:" -ForegroundColor White
    Write-Host "  https://www.docker.com/products/docker-desktop/" -ForegroundColor Cyan
    Write-Host ""
    $reply = Read-Host "Open the download page in your browser? [Y/n]"
    if ($reply -eq "" -or $reply -match "^[Yy]") {
        Start-Process "https://www.docker.com/products/docker-desktop/"
        Write-Host ""
        Write-Host "After installation:" -ForegroundColor White
        Write-Host "  1. Launch Docker Desktop (Start Menu -> Docker Desktop)"
        Write-Host "  2. Accept the license agreement"
        Write-Host "  3. Wait for the whale icon in the system tray (status: 'Engine running')"
        Write-Host "  4. Re-run: .\install\bootstrap.ps1"
    } else {
        Write-Host "Download Docker Desktop from https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
        Write-Host "Install, launch, and wait for the whale icon in the system tray."
    }
    exit 1
}

# Check if Docker daemon is reachable
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Docker daemon is not reachable." -ForegroundColor Red
    Write-Host ""
    Write-Host "Make sure Docker Desktop is running:" -ForegroundColor White
    Write-Host "  1. Launch Docker Desktop from the Start Menu"
    Write-Host "  2. Wait for the whale icon in the system tray"
    Write-Host "  3. Icon tooltip should say 'Engine running'"
    Write-Host "  4. Re-run: .\install\bootstrap.ps1"
    Write-Host ""
    Write-Host "First launch after install can take 1-2 minutes."
    exit 1
}

Push-Location $InstallerDir
try {
    uv run --project . python -m metatron_installer @args
} finally {
    Pop-Location
}
