# Headless (overnight) campaign driver: repeats `claude -p "/research --resume --slug <slug>"` with checkpoints.
#   scripts\run_campaign.ps1 -Slug my-campaign [-MaxIterations 20] [-MaxTurns 200] [-PermissionMode acceptEdits] [-Command /research]
param(
  [Parameter(Mandatory = $true)][string]$Slug,
  [int]$MaxIterations = 20,
  [int]$MaxTurns = 200,
  [string]$PermissionMode = "acceptEdits",
  [string]$Command = "/research",
  [string]$Model = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$env:PYTHONUTF8 = "1"
$argv = @("-m", "harness", "headless", $Slug, "--max-iterations", $MaxIterations, "--max-turns", $MaxTurns, "--permission-mode", $PermissionMode, "--command", $Command)
if ($Model) { $argv += @("--model", $Model) }
& (Join-Path $Root ".venv\Scripts\python.exe") @argv
exit $LASTEXITCODE
