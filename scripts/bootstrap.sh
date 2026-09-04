#!/usr/bin/env bash
# Neugier bootstrap (Linux / macOS / Git Bash). Everything stays inside the project directory.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONUTF8=1
export UV_CACHE_DIR="$ROOT/.cache/uv"
export PIP_CACHE_DIR="$ROOT/.cache/pip"
export TECTONIC_CACHE_DIR="$ROOT/.cache/tectonic"
mkdir -p .cache bin campaigns library

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OS=windows; PY=".venv/Scripts/python.exe"; ASSET="x86_64-pc-windows-msvc.zip";;
  Darwin) OS=mac; PY=".venv/bin/python"; ASSET="$( [ "$(uname -m)" = arm64 ] && echo aarch64 || echo x86_64 )-apple-darwin.tar.gz";;
  *) OS=linux; PY=".venv/bin/python"; ASSET="x86_64-unknown-linux-gnu.tar.gz";;
esac

# 1. virtual environment
if [ ! -x "$PY" ]; then
  if command -v uv >/dev/null 2>&1; then uv venv .venv --python 3.13; else python3 -m venv .venv; fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PY" -r requirements.txt
  uv pip install --python "$PY" -e "$ROOT"
else
  "$PY" -m pip install -r requirements.txt && "$PY" -m pip install -e "$ROOT"
fi

# 2. tectonic
if [ ! -x bin/tectonic ] && [ ! -x bin/tectonic.exe ]; then
  URL=$(curl -s https://api.github.com/repos/tectonic-typesetting/tectonic/releases/latest | python3 -c "import json,sys; print(next(a['browser_download_url'] for a in json.load(sys.stdin)['assets'] if a['name'].endswith('$ASSET')))")
  echo "[bootstrap] downloading $URL"
  curl -sL "$URL" -o ".cache/tectonic-archive"
  mkdir -p .cache/tectonic-unzip
  case "$ASSET" in
    *.zip) python3 -c "import zipfile; zipfile.ZipFile('.cache/tectonic-archive').extractall('.cache/tectonic-unzip')";;
    *) tar -xzf .cache/tectonic-archive -C .cache/tectonic-unzip;;
  esac
  find .cache/tectonic-unzip -name 'tectonic*' -type f -exec cp {} bin/ \;
  chmod +x bin/tectonic* || true
  rm -f .cache/tectonic-archive
fi

# 3. junctions / symlinks for .claude
for d in agents skills; do
  if [ ! -e ".claude/$d" ]; then
    if [ "$OS" = windows ]; then cmd //c mklink //J "$(cygpath -w "$ROOT/.claude/$d")" "$(cygpath -w "$ROOT/$d")" >/dev/null; else ln -s "../$d" ".claude/$d"; fi
    echo "[bootstrap] linked .claude/$d -> $d"
  fi
done

# 4. smoke
"$PY" -c "import sympy, scipy, networkx, z3, pysat, fitz; print('[bootstrap] python deps OK')"
ls bin/tectonic* >/dev/null 2>&1 && bin/tectonic* --version || true
echo "[bootstrap] done. Launch with:  claude   (or: claude --plugin-dir .)"
