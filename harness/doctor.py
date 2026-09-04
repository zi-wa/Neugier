"""`python -m harness doctor [--offline] [--json]` — environment and wiring checks (Round-1 Step 12).

Reports, with a fix command for each failure: the project venv interpreter, UTF-8
mode, Python version, tectonic, hook registrations in both ``hooks/hooks.json``
(plugin mode) and ``.claude/settings.json`` (project mode) pointing at existing
scripts, agent-frontmatter hooks resolving under both root variables, the
``.claude/agents|skills`` links, ``claude`` and ``git`` on PATH, engine
reachability (skipped with ``--offline``), ``library/`` and ``campaigns/ACTIVE``
sanity, and informational lines (Lean lane deferred, plugin evals early-access).
Exit 1 when a hard check fails.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import harness

HOOK_EVENTS = ("PreToolUse", "SessionStart", "UserPromptSubmit", "Stop", "SubagentStop")
ENGINES = {
    "arxiv": "https://export.arxiv.org/api/query?search_query=all:test&max_results=1",
    "openalex": "https://api.openalex.org/works?search=test&per-page=1",
    "oeis": "https://oeis.org/search?q=id:A000045&fmt=json",
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    hard: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _venv_python(root: Path) -> Path | None:
    for cand in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if cand.exists():
            return cand
    return None


def _hook_scripts(text: str) -> list[str]:
    return sorted(set(re.findall(r"hooks/([A-Za-z0-9_]+\.py)", text)))


def check_venv(root: Path) -> Check:
    py = _venv_python(root)
    if py is None:
        return Check("venv", False, ".venv interpreter not found", "run scripts/bootstrap.ps1 (or bootstrap.sh)")
    inside = Path(sys.executable).resolve().as_posix().lower().startswith((root / ".venv").resolve().as_posix().lower())
    return Check("venv", True, f"{py}{'' if inside else ' (doctor is running under a different interpreter)'}")


def check_utf8() -> Check:
    ok = bool(getattr(sys.flags, "utf8_mode", 0)) or os.environ.get("PYTHONUTF8") == "1"
    return Check("utf8", ok, "PYTHONUTF8=1" if ok else "UTF-8 mode is off (host default may be cp949)",
                 "" if ok else "set PYTHONUTF8=1 (bootstrap and .claude/settings.json do this)", hard=False)


def check_python() -> Check:
    ok = sys.version_info >= (3, 11)
    return Check("python", ok, sys.version.split()[0], "" if ok else "use Python >= 3.11 in .venv")


def check_tectonic(root: Path) -> Check:
    try:
        from harness.paper.build import find_tectonic

        t = find_tectonic()
    except Exception:
        t = None
    if t is None:
        return Check("tectonic", False, "not found in bin/ or PATH", "run scripts/bootstrap.ps1 (downloads bin/tectonic.exe)", hard=False)
    try:
        out = subprocess.run([str(t), "--version"], capture_output=True, encoding="utf-8", errors="replace", timeout=20).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        out = f"cannot run ({exc})"
    return Check("tectonic", True, f"{t} — {out.splitlines()[0] if out else '?'}", hard=False)


def check_hook_registrations(root: Path) -> list[Check]:
    out: list[Check] = []
    for rel in ("hooks/hooks.json", ".claude/settings.json"):
        path = root / rel
        if not path.exists():
            out.append(Check(f"hooks:{rel}", False, "missing", "restore the file from git"))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            out.append(Check(f"hooks:{rel}", False, f"invalid JSON: {exc}", "fix the JSON"))
            continue
        hooks = data.get("hooks") or {}
        missing_events = [e for e in HOOK_EVENTS if e not in hooks]
        text = json.dumps(hooks)
        missing_scripts = [s for s in _hook_scripts(text) if not (root / "hooks" / s).exists()]
        var = "${CLAUDE_PLUGIN_ROOT}" if rel.startswith("hooks/") else "${CLAUDE_PROJECT_DIR}"
        wrong_var = var not in text
        ok = not missing_events and not missing_scripts and not wrong_var
        detail = []
        if missing_events:
            detail.append(f"events not registered: {missing_events}")
        if missing_scripts:
            detail.append(f"scripts missing: {missing_scripts}")
        if wrong_var:
            detail.append(f"commands should use {var}")
        out.append(Check(f"hooks:{rel}", ok, "; ".join(detail) or f"{len(_hook_scripts(text))} scripts, all events registered",
                         "" if ok else "compare with hooks/hooks.json in git"))
    return out


def check_agent_frontmatter(root: Path) -> Check:
    problems = []
    n = 0
    for p in sorted((root / "agents").glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            continue
        fm = text.split("\n---", 1)[0]
        if "hooks:" not in fm:
            continue
        n += 1
        for s in _hook_scripts(fm):
            if not (root / "hooks" / s).exists():
                problems.append(f"{p.name}: hooks/{s} missing")
        if "${CLAUDE_PROJECT_DIR}" not in fm and "${CLAUDE_PLUGIN_ROOT}" not in fm:
            problems.append(f"{p.name}: hook command has no root variable")
    return Check("agent-hooks", not problems, "; ".join(problems) or f"{n} agents with frontmatter hooks resolve",
                 "" if not problems else "fix the agent frontmatter hooks: block")


def check_links(root: Path) -> list[Check]:
    out = []
    for d in ("agents", "skills"):
        link = root / ".claude" / d
        target = root / d
        ok = link.exists() and any(link.iterdir()) and any(target.iterdir())
        out.append(Check(f"link:.claude/{d}", ok, str(link) if ok else f"{link} missing or empty",
                         "" if ok else f"scripts/bootstrap.ps1 (creates the junction .claude/{d} -> {d})", hard=False))
    return out


def check_tool(name: str, args: list[str], hard: bool = False) -> Check:
    path = shutil.which(name) or shutil.which(name + ".cmd")
    if not path:
        return Check(name, False, "not on PATH", f"install {name}", hard=hard)
    try:
        out = subprocess.run([path] + args, capture_output=True, encoding="utf-8", errors="replace", timeout=30).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        out = f"cannot run ({exc})"
    return Check(name, True, out.splitlines()[0] if out else path, hard=hard)


def check_engines(timeout: float = 6.0) -> list[Check]:
    out = []
    try:
        import requests
    except ImportError:
        return [Check("engines", False, "requests not installed", "uv pip install --python .venv/Scripts/python.exe requests", hard=False)]
    for name, url in ENGINES.items():
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "Neugier/0.2 doctor"})
            ok = r.status_code < 500
            out.append(Check(f"engine:{name}", ok, f"HTTP {r.status_code}", "" if ok else "check network/proxy", hard=False))
        except Exception as exc:  # noqa: BLE001
            out.append(Check(f"engine:{name}", False, f"{type(exc).__name__}", "check network/proxy", hard=False))
    return out


def check_library_and_active(root: Path) -> list[Check]:
    out = []
    lib = Path(harness.LIBRARY)
    out.append(Check("library", lib.is_dir() or not lib.exists(), str(lib), "" if lib.is_dir() or not lib.exists() else "library/ is not a directory", hard=False))
    active = Path(harness.CAMPAIGNS) / "ACTIVE"
    if active.exists():
        slug = active.read_text(encoding="utf-8").strip()
        ok = bool(slug) and (Path(harness.CAMPAIGNS) / slug / "campaign.json").exists()
        out.append(Check("campaigns/ACTIVE", ok, f"-> {slug or '(empty)'}", "" if ok else f"`harness campaign activate <slug>` or delete {active}", hard=False))
    else:
        out.append(Check("campaigns/ACTIVE", True, "no active campaign", hard=False))
    return out


def run_all(root: Path | None = None, offline: bool = False) -> list[Check]:
    root = Path(root or harness.ROOT)
    checks: list[Check] = [check_venv(root), check_utf8(), check_python(), check_tectonic(root)]
    checks += check_hook_registrations(root)
    checks.append(check_agent_frontmatter(root))
    checks += check_links(root)
    checks.append(check_tool("claude", ["--version"]))
    checks.append(check_tool("git", ["--version"]))
    if not offline:
        checks += check_engines()
    checks += check_library_and_active(root)
    checks.append(Check("lean", True, "deferred (formalization lane not shipped; `formalized` is a reserved status)", hard=False))
    checks.append(Check("plugin-evals", True, "`claude plugin eval` is early access; use `harness evals run` meanwhile", hard=False))
    return checks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness doctor", description="environment and wiring checks")
    p.add_argument("--offline", action="store_true", help="skip engine reachability")
    p.add_argument("--json", action="store_true")
    p.add_argument("--root", default=None)
    args = p.parse_args(argv)
    checks = run_all(Path(args.root) if args.root else None, offline=args.offline)
    hard_fail = [c for c in checks if not c.ok and c.hard]
    soft_fail = [c for c in checks if not c.ok and not c.hard]
    if args.json:
        print(json.dumps({"ok": not hard_fail, "checks": [c.to_dict() for c in checks]}, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            mark = "OK " if c.ok else ("FAIL" if c.hard else "WARN")
            line = f"[{mark}] {c.name:<26} {c.detail}"
            if not c.ok and c.fix:
                line += f"\n       fix: {c.fix}"
            print(line)
        print(f"doctor: {len(hard_fail)} hard failure(s), {len(soft_fail)} warning(s)")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
