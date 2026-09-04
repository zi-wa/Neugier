"""Branding guard: the product name is Neugier; the legacy name must not appear in shipped text."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".tex", ".yaml", ".yml", ".js", ".ps1", ".sh", ".in", ".cfg", ".bib"}
SKIP_DIRS = {".venv", ".cache", ".git", "__pycache__", "node_modules", "bin", "campaigns", "library", "results"}
# docs/research keeps the historical design record and may mention the old name.
SKIP_PREFIXES = ("docs/research/",)
# Built from pieces so this file does not itself contain the legacy token; the old distribution name
# (`<legacy>-harness`) may still appear in the bootstrap uninstall guard.
LEGACY = re.compile("claude" + "math" + "(?!-harness)", re.IGNORECASE)


def _tracked_text_files():
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(ROOT).as_posix()
        parts = set(p.relative_to(ROOT).parts)
        if parts & SKIP_DIRS or any(part.endswith(".egg-info") for part in parts):
            continue
        if rel.startswith(SKIP_PREFIXES):
            continue
        yield p, rel


def test_no_legacy_brand_strings():
    hits = []
    for p, rel in _tracked_text_files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LEGACY.search(text):
            hits.append(rel)
    assert not hits, f"legacy brand string found in: {hits}"


def test_hook_messages_use_brand_prefix():
    hooks = sorted((ROOT / "hooks").glob("*.py"))
    assert hooks
    for h in hooks:
        if h.name.startswith("_"):
            continue
        text = h.read_text(encoding="utf-8")
        assert "[Neugier" in text, f"{h.name} has no [Neugier …] message prefix"


def test_plugin_manifest_is_branded():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "neugier"
    for key in ("name", "displayName", "description"):
        value = str(manifest.get(key, ""))
        # "runs on Claude Code" is allowed in prose; the product name itself must not contain the vendor's marks.
        if key in ("name", "displayName"):
            assert "claude" not in value.lower() and "anthropic" not in value.lower(), key
