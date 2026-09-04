#!/bin/sh
# Neugier installer (Linux / macOS / WSL / Git Bash).
#
#   curl -fsSL https://raw.githubusercontent.com/zi-wa/Neugier/main/install.sh | sh
#
# Clones the repository and runs its bootstrap. Everything it creates stays inside the clone:
# .venv, bin/tectonic, .cache. Nothing is installed globally, no PATH or profile is modified,
# and nothing runs with sudo. Read this file before piping it to a shell if you prefer.
#
# Environment:
#   NEUGIER_DIR           where to install        (default: $HOME/Neugier)
#   NEUGIER_REPO          clone source           (default: https://github.com/zi-wa/Neugier.git)
#   NEUGIER_REF           branch or tag          (default: main)
#   NEUGIER_NO_BOOTSTRAP  set to 1 to clone only (skip .venv and tectonic)
set -eu

REPO="${NEUGIER_REPO:-https://github.com/zi-wa/Neugier.git}"
REF="${NEUGIER_REF:-main}"
DIR="${NEUGIER_DIR:-$HOME/Neugier}"

say()  { printf '[neugier] %s\n' "$*"; }
die()  { printf '[neugier] error: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

have git || die "git is required (https://git-scm.com/downloads)"
have python3 || have python || die "python 3.11+ is required (https://www.python.org/downloads/)"

PY_BIN=python3
have python3 || PY_BIN=python
"$PY_BIN" - <<'EOF' || die "python 3.11 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
EOF

if [ -d "$DIR/.git" ]; then
  say "updating existing checkout at $DIR"
  git -C "$DIR" fetch --quiet origin "$REF"
  git -C "$DIR" checkout --quiet "$REF"
  git -C "$DIR" pull --quiet --ff-only origin "$REF" || say "could not fast-forward; keeping the local branch"
elif [ -e "$DIR" ]; then
  die "$DIR exists and is not a git checkout; set NEUGIER_DIR to another path"
else
  say "cloning into $DIR"
  git clone --quiet --branch "$REF" --depth 1 "$REPO" "$DIR"
fi

if [ "${NEUGIER_NO_BOOTSTRAP:-0}" = "1" ]; then
  say "skipping bootstrap (NEUGIER_NO_BOOTSTRAP=1)"
else
  say "bootstrapping (.venv, tectonic, hooks) — this downloads a few hundred MB the first time"
  sh "$DIR/scripts/bootstrap.sh"
fi

cat <<EOF

[neugier] installed at $DIR

  cd "$DIR"
  claude --plugin-dir .

then, inside Claude Code:

  /research auto     start a campaign on a target the scout picks
  /status            phase, unmet criteria, budgets, questions

Docs: $DIR/README.md
EOF
