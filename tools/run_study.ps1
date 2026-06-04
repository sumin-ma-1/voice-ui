# User study launcher (Windows PowerShell)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\run_study.ps1 -Participant U1
#   powershell -ExecutionPolicy Bypass -File tools\run_study.ps1 -Participant U2 -Input voice
#
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("U1", "U2", "U3")]
    [string]$Participant,

    [ValidateSet("uia", "ocr", "vision", "both", "all")]
    [string]$Mode = "all",

    [ValidateSet("text", "voice")]
    [string]$Input = "voice",

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
$env:VOICE_UI_DATASET_LOG = "1"
$env:VOICE_UI_DATASET_DIR = "dataset_$Participant"
$env:VOICE_UI_DATASET_EXTRA_NEGATIVES = "0"
$env:VOICE_UI_INPUT_MODE = $Input

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
Write-Host "Input       : $Input"
Write-Host "Ratings     : $(if ($Ratings) { 'on (1-5 popup after success)' } else { 'off' })"
Write-Host ""
Write-Host "Logs:"
Write-Host "  $env:VOICE_UI_DATASET_DIR\events.jsonl"
Write-Host "  $env:VOICE_UI_DATASET_DIR\study_manifest.json"
if ($Ratings) {
    Write-Host "  $env:VOICE_UI_DATASET_DIR\study_ratings.jsonl"
}
Write-Host ""

python main.py --mode $Mode --input $Input
