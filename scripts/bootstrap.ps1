# Neugier bootstrap (Windows PowerShell 5.1+). Everything stays inside the project directory.
#   .venv  (uv)     bin/tectonic.exe     .cache/{uv,tectonic}     .claude/{agents,skills} junctions
param([switch]$SkipTectonic, [switch]$SkipDeps)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$env:PYTHONUTF8 = "1"
$env:UV_CACHE_DIR = Join-Path $Root ".cache\uv"
$env:PIP_CACHE_DIR = Join-Path $Root ".cache\pip"
$env:TECTONIC_CACHE_DIR = Join-Path $Root ".cache\tectonic"
New-Item -ItemType Directory -Force -Path (Join-Path $Root ".cache"), (Join-Path $Root "bin"), (Join-Path $Root "campaigns"), (Join-Path $Root "library") | Out-Null

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv not found on PATH. Install uv (https://docs.astral.sh/uv/) or run scripts/bootstrap.sh which falls back to python -m venv." }

# 1. virtual environment
if (-not (Test-Path (Join-Path $Root ".venv\Scripts\python.exe"))) {
  Write-Host "[bootstrap] creating .venv"
  uv venv (Join-Path $Root ".venv") --python 3.13
}
if (-not $SkipDeps) {
  Write-Host "[bootstrap] installing requirements into .venv"
  uv pip uninstall --python (Join-Path $Root ".venv\Scripts\python.exe") claudemath-harness 2>$null | Out-Null
  uv pip install --python (Join-Path $Root ".venv\Scripts\python.exe") -r (Join-Path $Root "requirements.txt")
  uv pip install --python (Join-Path $Root ".venv\Scripts\python.exe") -e $Root
}

# 2. tectonic (single-binary LaTeX engine), project-local
$Tectonic = Join-Path $Root "bin\tectonic.exe"
if (-not $SkipTectonic -and -not (Test-Path $Tectonic)) {
  Write-Host "[bootstrap] downloading tectonic"
  $rel = Invoke-RestMethod "https://api.github.com/repos/tectonic-typesetting/tectonic/releases/latest"
  $asset = $rel.assets | Where-Object { $_.name -like "*x86_64-pc-windows-msvc.zip" } | Select-Object -First 1
  if (-not $asset) { throw "no windows tectonic asset found in release $($rel.tag_name)" }
  $zip = Join-Path $Root ".cache\tectonic.zip"
  Invoke-WebRequest $asset.browser_download_url -OutFile $zip
  Expand-Archive $zip -DestinationPath (Join-Path $Root ".cache\tectonic-unzip") -Force
  Copy-Item (Get-ChildItem (Join-Path $Root ".cache\tectonic-unzip") -Recurse -Filter "tectonic.exe" | Select-Object -First 1).FullName $Tectonic
  Remove-Item $zip -Force
}

# 3. junctions so plain `claude` in this directory sees agents/ and skills/
foreach ($d in @("agents", "skills")) {
  $link = Join-Path $Root ".claude\$d"
  if (-not (Test-Path $link)) {
    New-Item -ItemType Junction -Path $link -Target (Join-Path $Root $d) | Out-Null
    Write-Host "[bootstrap] junction .claude\$d -> $d"
  }
}

# 4. smoke
& (Join-Path $Root ".venv\Scripts\python.exe") -c "import sympy, scipy, networkx, z3, pysat, fitz, pydantic, bibtexparser, requests, yaml, numpy; print('[bootstrap] python deps OK')"
if (Test-Path $Tectonic) { & $Tectonic --version }
& (Join-Path $Root ".venv\Scripts\python.exe") -m harness doctor --offline
Write-Host "[bootstrap] done. Launch with:  claude   (or: claude --plugin-dir .)"
