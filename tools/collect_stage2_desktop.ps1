# Stage-2 collect: desktop apps (Office, Hancom Hangul, VS Code) — no browser history.
#
# Usage (repo root):
#   powershell -ExecutionPolicy Bypass -File tools\collect_stage2_desktop.ps1
#   powershell -ExecutionPolicy Bypass -File tools\collect_stage2_desktop.ps1 -DryRun
#
# Requires: venv, Office/HWP installed, VOICE_UI_DATASET_LOG (set below).

param(
    [switch]$DryRun,
    [switch]$SkipExport,
    [switch]$FullExport
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "venv not found: $Python"
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

if ($DryRun) {
    $collectArgs += "--dry-run"
}

Write-Host "=== Stage-2 desktop collect (Office + Hangul + VS Code, no history) ===" -ForegroundColor Cyan
Write-Host "Targets: configs/collect_targets.json (Chrome/Edge disabled; Word/Excel/PPT/Outlook/HWP enabled)"
Write-Host "Args: $($collectArgs -join ' ')"
Write-Host ""

& $Python @collectArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($DryRun -or $SkipExport) {
    Write-Host "Done (no export)." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
if ($FullExport) {
    Write-Host "=== Export pairs_stage2.jsonl (all languages) ===" -ForegroundColor Cyan
    & $Python training_data/icons_material/export_stage2_pairs.py
} else {
    Write-Host "=== Export pairs_stage2_en.jsonl (English labels only) ===" -ForegroundColor Cyan
    & $Python training_data/icons_material/export_stage2_en_experiment.py
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done. Check dataset/events.jsonl and training_data/icons_material/pairs_stage2*.jsonl" -ForegroundColor Green
