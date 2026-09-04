# Neugier installer (Windows PowerShell 5.1+).
#
#   irm https://raw.githubusercontent.com/zi-wa/Neugier/main/install.ps1 | iex
#
# Clones the repository and runs its bootstrap. Everything it creates stays inside the clone:
# .venv, bin\tectonic.exe, .cache. Nothing is installed globally, no PATH, profile or registry key is
# modified, and nothing runs elevated. Read this file before piping it to a shell if you prefer.
#
# Environment:
#   NEUGIER_DIR           where to install        (default: $HOME\Neugier)
#   NEUGIER_REPO          clone source           (default: https://github.com/zi-wa/Neugier.git)
#   NEUGIER_REF           branch or tag          (default: main)
#   NEUGIER_NO_BOOTSTRAP  set to 1 to clone only (skip .venv and tectonic)
$ErrorActionPreference = "Stop"

function Say($m) { Write-Host "[neugier] $m" }
function Die($m) { Write-Host "[neugier] error: $m" -ForegroundColor Red; exit 1 }

$repo = if ($env:NEUGIER_REPO) { $env:NEUGIER_REPO } else { "https://github.com/zi-wa/Neugier.git" }
$ref  = if ($env:NEUGIER_REF)  { $env:NEUGIER_REF }  else { "main" }
$dir  = if ($env:NEUGIER_DIR)  { $env:NEUGIER_DIR }  else { Join-Path $HOME "Neugier" }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git is required (https://git-scm.com/downloads)" }
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Die "python 3.11+ is required (https://www.python.org/downloads/)" }
& $py.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { Die "python 3.11 or newer is required" }

if (Test-Path (Join-Path $dir ".git")) {
  Say "updating existing checkout at $dir"
  git -C $dir fetch --quiet origin $ref
  git -C $dir checkout --quiet $ref
  git -C $dir pull --quiet --ff-only origin $ref
  if ($LASTEXITCODE -ne 0) { Say "could not fast-forward; keeping the local branch" }
} elseif (Test-Path $dir) {
  Die "$dir exists and is not a git checkout; set NEUGIER_DIR to another path"
} else {
  Say "cloning into $dir"
  git clone --quiet --branch $ref --depth 1 $repo $dir
  if ($LASTEXITCODE -ne 0) { Die "git clone failed" }
}

if ($env:NEUGIER_NO_BOOTSTRAP -eq "1") {
  Say "skipping bootstrap (NEUGIER_NO_BOOTSTRAP=1)"
} else {
  Say "bootstrapping (.venv, tectonic, hooks) - this downloads a few hundred MB the first time"
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir "scripts\bootstrap.ps1")
  if ($LASTEXITCODE -ne 0) { Die "bootstrap failed; see the output above" }
}

Write-Host ""
Say "installed at $dir"
Write-Host ""
Write-Host "  cd `"$dir`""
Write-Host "  claude --plugin-dir ."
Write-Host ""
Write-Host "then, inside Claude Code:"
Write-Host ""
Write-Host "  /research auto     start a campaign on a target the scout picks"
Write-Host "  /status            phase, unmet criteria, budgets, questions"
Write-Host ""
Write-Host "Docs: $dir\README.md"
