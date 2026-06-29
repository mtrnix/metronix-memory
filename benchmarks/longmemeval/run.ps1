# LongMemEval benchmark run (Windows PowerShell)
param(
    [switch]$Smoke,
    [switch]$RunOnly,
    [int]$MaxQuestions = 0,
    [ValidateSet("oracle", "s")]
    [string]$Variant = "s",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found. Run .\setup.ps1 first."
}

if ($Smoke) {
    $Variant = "oracle"
    if ($MaxQuestions -eq 0) { $MaxQuestions = 3 }
}

Write-Host "==> Preflight"
& $VenvPython scripts/preflight.py --ensure-workspace

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$Output = Join-Path $Root "results\${Timestamp}_${Variant}.jsonl"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "results") | Out-Null

$RunArgs = @("scripts/run_benchmark.py", "run", "--variant", $Variant, "--output", $Output)
if ($MaxQuestions -gt 0) {
    $RunArgs += @("--max-questions", $MaxQuestions)
}
if ($Force) {
    $RunArgs += "--force"
}

Write-Host "==> Running benchmark -> $Output"
& $VenvPython @RunArgs

if (-not (Test-Path $Output)) {
    Write-Error "Expected output file not found: $Output"
}

Write-Host ""
Write-Host "Results: $Output"

if (-not $RunOnly) {
    Write-Host "==> Evaluation (LLM judge)"
    & $VenvPython scripts/evaluate_results.py --results $Output --variant $Variant
}

Write-Host "Done."
