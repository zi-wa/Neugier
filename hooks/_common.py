"""Shared helpers for Neugier hooks. Stdlib only (hooks may run with the global interpreter)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def read_input() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def project_root(data: dict) -> Path:
    for key in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT"):
        v = os.environ.get(key)
        if v and Path(v).exists():
            return Path(v)
    cwd = data.get("cwd")
    if cwd:
        return Path(cwd)
    return Path(__file__).resolve().parent.parent


def venv_python(root: Path) -> Path | None:
    for cand in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if cand.exists():
            return cand
    return None


def active_campaign(root: Path) -> str | None:
    f = root / "campaigns" / "ACTIVE"
    try:
        slug = f.read_text(encoding="utf-8").strip()
        return slug or None
    except Exception:
        return None


def run_harness(root: Path, args: list[str], timeout: int = 30) -> tuple[int, str]:
    py = venv_python(root)
    if py is None:
        return 127, ""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(
            [str(py), "-m", "harness", *args],
            cwd=str(root), capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # pragma: no cover
        return 1, f"harness call failed: {e}"


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()
