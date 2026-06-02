# Full stage-2 dataset collection: installed apps + config targets + Chrome/Edge history + export.
#
# Usage (from repo root or any cwd):
#   powershell -ExecutionPolicy Bypass -File tools\collect_stage2_full.ps1
#
# Options:
#   -DryRun          Preview targets only (no dataset writes)
#   -HistoryLimit N   Cap history URLs (default 0 = no limit; uses config when omitted)
#   -SkipExport      Do not run export_stage2_pairs.py
#   -NoDiscover      Only config targets (no installed-app scan)
#   -NoHistory       Skip browser history traversal

param(
    [switch]$DryRun,
    [int]$HistoryLimit = 0,
    [switch]$SkipExport,
    [switch]$NoDiscover,
    [switch]$NoHistory
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "venv not found. Create venv and install requirements first: $Python"
}

$env:VOICE_UI_DATASET_LOG = "1"
$env:VOICE_UI_DATASET_EXTRA_NEGATIVES = "6"

$collectArgs = @(
    "tools/auto_collect_runner.py",
    "--config", "configs/collect_targets.json",
    "--auto-launch",
    "--add-hard-negs",
    "--force-enable-dataset-log",
    "--page-load-ms", "5000"
)

if ($HistoryLimit -gt 0) {
    $collectArgs += "--history-limit", "$HistoryLimit"
}

if (-not $NoDiscover) {
    $collectArgs += "--auto-discover"
}

if (-not $NoHistory) {
    $collectArgs += "--from-history", "both"
}

if ($DryRun) {
    $collectArgs += "--dry-run"
}

Write-Host "=== Stage-2 collect: installed apps + whitelist + Chrome/Edge history ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"
Write-Host "Python: $Python"
Write-Host "Args: $($collectArgs -join ' ')"
Write-Host ""

& $Python @collectArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($DryRun -or $SkipExport) {
    Write-Host ""
    Write-Host "Done (no export: DryRun or SkipExport)." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "=== Export pairs_stage2.jsonl ===" -ForegroundColor Cyan
& $Python training_data/icons_material/export_stage2_pairs.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done. Check dataset/ and training_data/icons_material/pairs_stage2.jsonl" -ForegroundColor Green
