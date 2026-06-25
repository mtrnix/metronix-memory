# LongMemEval benchmark setup (Windows PowerShell)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = if ($env:PYTHON) { $env:PYTHON } else { "py" }
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$EnvBenchmark = Join-Path $Root ".env.benchmark"
$EnvExample = Join-Path $Root ".env.benchmark.example"
$LegacyEnv = Join-Path $Root ".env"

Write-Host "==> LongMemEval setup"

if (-not (Test-Path $EnvBenchmark)) {
    if (Test-Path $LegacyEnv) {
        Copy-Item $LegacyEnv $EnvBenchmark
        Write-Host 'Migrated benchmarks/longmemeval/.env -> .env.benchmark'
    } else {
        Copy-Item $EnvExample $EnvBenchmark
        Write-Host 'Created .env.benchmark from .env.benchmark.example - edit it before running.'
    }
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating virtual environment"
    & $Python -3.11 -m venv $Venv
    if (-not (Test-Path $VenvPython)) {
        & $Python -m venv $Venv
    }
}

& $VenvPython -m pip install -q --upgrade pip
& $VenvPython -m pip install -q -r requirements-bench.txt

Write-Host "==> Downloading datasets (oracle + s)"
& $VenvPython scripts/run_benchmark.py download --variant oracle
& $VenvPython scripts/run_benchmark.py download --variant s

Write-Host '==> Preflight (health, env, workspace MABENCH)'
& $VenvPython scripts/preflight.py --ensure-workspace

Write-Host ""
Write-Host "Setup complete."
Write-Host 'Next: edit benchmarks/longmemeval/.env.benchmark if needed, then run .\run.ps1 -Smoke'
