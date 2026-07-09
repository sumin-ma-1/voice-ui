# User study launcher (Windows PowerShell) — free-form commands like es/sb participants.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\run_study.ps1 -Participant sm -Input text -Ratings
#   powershell -ExecutionPolicy Bypass -File tools\run_study.ps1 -Participant U2 -Input voice
#
# For automated task131 benchmark (latency/success only, no ratings):
#   powershell -ExecutionPolicy Bypass -File tools\run_task131_bench.ps1
#
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("U1", "U2", "U3", "es", "sb", "sm")]
    [string]$Participant,

    [ValidateSet("uia", "ocr", "vision", "both", "all")]
    [string]$Mode = "all",

    [ValidateSet("text", "voice")]
    [string]$InputMode = "text",

    [switch]$Ratings
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (!(Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv..."
    py -3.12 -m venv venv
}

.\venv\Scripts\Activate.ps1

$env:VOICE_UI_STUDY = "1"
$env:VOICE_UI_STUDY_USER = $Participant
$env:VOICE_UI_STUDY_SESSION_TYPE = "user_study"
$env:VOICE_UI_DATASET_LOG = "1"
$env:VOICE_UI_DATASET_DIR = "dataset_$Participant"
$env:VOICE_UI_DATASET_EXTRA_NEGATIVES = "0"
$env:VOICE_UI_INPUT_MODE = $InputMode
# Text mode: no grace delay. Voice keeps default ~0.85s cancel window.
if ($InputMode -eq "text") {
    $env:VOICE_UI_GRACE_SECONDS = "0"
}

if ($Ratings) {
    $env:VOICE_UI_STUDY_RATINGS = "1"
} else {
    Remove-Item Env:VOICE_UI_STUDY_RATINGS -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "=== Voice UI user study ==="
Write-Host "Participant : $Participant"
Write-Host "Dataset dir : $env:VOICE_UI_DATASET_DIR"
Write-Host "Mode        : $Mode"
Write-Host "Input       : $InputMode"
Write-Host "Ratings     : $(if ($Ratings) { 'on (1-5 popup after success)' } else { 'off' })"
Write-Host "Session type: user_study (free commands; aim for ~130+ like es/sb)"
Write-Host "Latency     : events.jsonl -> study.latency_ms.pipeline (primary)"
Write-Host "Hardware    : see configs/STUDY_HARDWARE.md"
Write-Host ""
Write-Host "Logs:"
Write-Host "  $env:VOICE_UI_DATASET_DIR\events.jsonl"
Write-Host "  $env:VOICE_UI_DATASET_DIR\study_manifest.json"
if ($Ratings) {
    Write-Host "  $env:VOICE_UI_DATASET_DIR\study_ratings.jsonl"
}
Write-Host ""

python main.py --mode $Mode --input $InputMode
