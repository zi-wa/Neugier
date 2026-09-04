"""Neugier harness runtime.

Python-side tooling for the Neugier research harness: literature clients,
the claim ledger, falsification/exact-arithmetic helpers, evolutionary search,
and the LaTeX build/check pipeline. All modules must use UTF-8 explicitly
(the host default encoding may be cp949).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__version__ = "0.2.0"

# Project root = directory containing this package's parent (repo root).
ROOT: Path = Path(__file__).resolve().parent.parent
CAMPAIGNS: Path = ROOT / "campaigns"
LIBRARY: Path = ROOT / "library"
CACHE: Path = ROOT / ".cache"
BIN: Path = ROOT / "bin"

# Force UTF-8 for stdio regardless of host locale (Windows cp949 by default).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - non-reconfigurable streams
        pass
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("TECTONIC_CACHE_DIR", str(CACHE / "tectonic"))
