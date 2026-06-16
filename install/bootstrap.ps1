#Requires -Version 5.1
<#
.SYNOPSIS
    Metatron Core installer entry point for Windows (PowerShell).

.DESCRIPTION
    Windows counterpart to bootstrap.sh. Installs uv if missing,
    then launches the Python installer from the installer/ directory.

.EXAMPLE
    .\install\bootstrap.ps1
    .\install\bootstrap.ps1 --dry-run
    .\install\bootstrap.ps1 --non-interactive
    .\install\bootstrap.ps1 --config answers.yaml
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

Push-Location $InstallerDir
try {
    uv run --project . python -m metatron_installer @args
} finally {
    Pop-Location
}
