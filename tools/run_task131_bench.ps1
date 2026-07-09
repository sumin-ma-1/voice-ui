# Automated task131 benchmark on this PC (hardware + latency + success rate).
# No satisfaction ratings — use run_study.ps1 for free-form user study.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\run_task131_bench.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (!(Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv..."
    py -3.12 -m venv venv
}

.\venv\Scripts\Activate.ps1

Write-Host ""
Write-Host "=== task131 benchmark (sm PC, automated) ==="
Write-Host "Output: dataset_sm_task131\"
Write-Host "Ratings: off"
Write-Host ""

python tools/run_study_batch.py --participant sm --dataset-dir dataset_sm_task131 --fresh
