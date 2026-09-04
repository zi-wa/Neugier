"""Deterministic graders shared by the in-house eval runner (mirrors the case graders' intent)."""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path


def file_exists(workspace: Path, pattern: str) -> tuple[float, str]:
    hits = glob.glob(str(workspace / pattern), recursive=True)
    return (1.0, f"found {hits[0]}") if hits else (0.0, f"no file matches {pattern}")


def file_regex(workspace: Path, pattern: str, regex: str, flags: int = re.IGNORECASE | re.MULTILINE) -> tuple[float, str]:
    hits = glob.glob(str(workspace / pattern), recursive=True)
    if not hits:
        return 0.0, f"no file matches {pattern}"
    for h in hits:
        text = Path(h).read_text(encoding="utf-8", errors="replace")
        if re.search(regex, text, flags):
            return 1.0, f"{Path(h).name} matches /{regex}/"
    return 0.0, f"no match for /{regex}/ in {len(hits)} file(s)"


def json_path_not_null(workspace: Path, pattern: str, key: str) -> tuple[float, str]:
    hits = glob.glob(str(workspace / pattern), recursive=True)
    for h in hits:
        try:
            data = json.loads(Path(h).read_text(encoding="utf-8"))
        except ValueError:
            continue
        if data.get(key) not in (None, "", []):
            return 1.0, f"{Path(h).name}[{key}] = {str(data.get(key))[:60]}"
    return 0.0, f"no {pattern} with non-null {key}"


def access_log_has_deny(workspace: Path, pattern: str, target_regex: str) -> tuple[float, str]:
    for h in glob.glob(str(workspace / pattern), recursive=True):
        for ln in Path(h).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if row.get("decision") == "deny" and re.search(target_regex, str(row.get("target", "")), re.IGNORECASE):
                return 1.0, f"deny logged for {row.get('target')}"
    return 0.0, "no matching deny row in access.log"
