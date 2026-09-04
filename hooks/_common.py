"""Shared helpers for Neugier hooks. Stdlib only (hooks may run with the global interpreter).

The barrier-related helpers (``glob_match``, ``role_allowed``, ``verdict_block_min``) deliberately
re-implement the harness versions in :mod:`harness.review.barrier` / :mod:`harness.review.verdict`;
``tests/test_hooks_barrier.py`` asserts both agree so the hook and the gate never disagree on a path.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


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


def campaign_dir_of(root: Path, slug: str) -> Path:
    return root / "campaigns" / slug


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


def deny(event: str, reason: str) -> None:
    emit({"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": reason}})


# ------------------------------------------------------------------ agents --

ROLE_ALIASES = {"novelty-checker": "novelty", "novelty_checker": "novelty"}


def agent_role(data: dict) -> str | None:
    """Referee/agent role from the hook payload's ``agent_type`` (None outside subagents)."""
    t = data.get("agent_type") or data.get("agentType")
    if not t:
        return None
    t = str(t).strip().lower()
    return ROLE_ALIASES.get(t, t)


def claude_agent_id(data: dict) -> str:
    return str(data.get("agent_id") or data.get("agentId") or data.get("session_id") or "?")


# ------------------------------------------------------------------ paths --

def norm_path(p: str, cwd: str | Path | None = None) -> str:
    """Expand ``~``/env prefixes, make absolute (relative to ``cwd``), realpath, normcase, forward slashes."""
    s = str(p).strip().strip('"').strip("'")
    home = os.path.expanduser("~")
    for token in ("%USERPROFILE%", "$env:USERPROFILE", "${HOME}", "$HOME", "~"):
        if s.startswith(token):
            s = home + s[len(token):]
            break
    if not os.path.isabs(s):
        s = os.path.join(str(cwd or os.getcwd()), s)
    try:
        s = os.path.realpath(s)
    except Exception:
        s = os.path.abspath(s)
    return os.path.normcase(s).replace("\\", "/")


def rel_to(path: str, base: str | Path) -> str | None:
    """``path`` relative to ``base`` (both normalized) as POSIX, or None when outside."""
    b = norm_path(str(base)).rstrip("/") + "/"
    p = norm_path(path)
    if p == b.rstrip("/"):
        return ""
    if p.startswith(b):
        return p[len(b):]
    return None


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    pat = pattern.strip().replace("\\", "/").lstrip("./")
    out = []
    i = 0
    while i < len(pat):
        ch = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pat.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def glob_match(rel: str, pattern: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("./")
    return _pattern_regex(pattern).match(rel) is not None


def role_allowed(manifest: dict, role_key: str, rel: str) -> tuple[bool, str]:
    role = manifest.get("roles", {}).get(role_key)
    if role is None:
        return True, "unknown-role"
    if not role.get("barrier", True):
        return True, "no-barrier"
    allow = list(role.get("allow", []))
    if role.get("stage") == "B":
        allow += list(role.get("stage_b_allow", []))
    for pat in allow:
        if glob_match(rel, pat):
            return True, f"allow:{pat}"
    for pat in manifest.get("deny_always", []):
        if glob_match(rel, pat):
            return False, f"deny:{pat}"
    return False, "deny:not-in-allowlist"


def dir_allowed(manifest: dict, role_key: str, rel_dir: str) -> bool:
    """A directory prefix is acceptable for Glob/Grep when some allow pattern lives under it
    or the directory itself is under an allowed ``**`` pattern."""
    role = manifest.get("roles", {}).get(role_key)
    if role is None or not role.get("barrier", True):
        return True
    allow = list(role.get("allow", []))
    if role.get("stage") == "B":
        allow += list(role.get("stage_b_allow", []))
    rel_dir = rel_dir.replace("\\", "/").strip("/")
    for pat in allow:
        if glob_match(rel_dir, pat) or glob_match(rel_dir + "/x", pat):
            return True
        static = pat.split("*", 1)[0].rstrip("/")
        if rel_dir and static.lower().startswith(rel_dir.lower() + "/"):
            return True  # the directory contains allowed files; Glob/Grep results are filtered by Read anyway
    return False


# --------------------------------------------------------------- barrier --

def find_open_barrier(root: Path, slug: str) -> tuple[int, dict, Path] | str | None:
    """``(round, manifest, round_dir)``, the string ``"ambiguous"`` when >1 open, or None."""
    reviews = campaign_dir_of(root, slug) / "reviews"
    found: list[tuple[int, dict, Path]] = []
    if not reviews.is_dir():
        return None
    for p in reviews.iterdir():
        m = re.fullmatch(r"round(\d+)", p.name)
        if not m or not (p / "barrier.json").exists():
            continue
        try:
            data = json.loads((p / "barrier.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "open":
            found.append((int(m.group(1)), data, p))
    if not found:
        return None
    if len(found) > 1:
        return "ambiguous"
    return found[0]


def resolve_role_key(round_dir: Path, manifest: dict, role: str, agent: str) -> str | None:
    """Map a subagent (Claude ``agent_id``) to a manifest role key; claims a skeptic slot once."""
    roles = manifest.get("roles", {})
    candidates = [k for k in roles if k.split(":", 1)[0] == role]
    if not candidates:
        return None
    agents_dir = round_dir / ".agents"
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]+", "_", agent)[:80]
    mapping = agents_dir / f"{safe_agent}.json"
    try:
        if mapping.exists():
            key = json.loads(mapping.read_text(encoding="utf-8")).get("role_key")
            if key in roles:
                return key
    except Exception:
        pass
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        chosen = None
        for key in candidates:
            lock = agents_dir / f"slot-{re.sub(r'[^A-Za-z0-9_.-]+', '_', key)}.lock"
            try:
                agents_dir.mkdir(parents=True, exist_ok=True)
                with open(lock, "x", encoding="utf-8") as fh:
                    fh.write(agent)
                chosen = key
                break
            except FileExistsError:
                continue
            except Exception:
                continue
        if chosen is None:
            chosen = candidates[0]
    try:
        agents_dir.mkdir(parents=True, exist_ok=True)
        mapping.write_text(json.dumps({"role_key": chosen, "agent": agent, "ts": time.time()}), encoding="utf-8")
    except Exception:
        pass
    return chosen


def append_jsonl(path: Path, row: dict) -> None:
    """Append a JSON row; drop it when identical (ignoring ``ts``) to the last row (double registration)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        last = None
        if path.exists():
            with open(path, "rb") as fh:
                try:
                    fh.seek(-4096, os.SEEK_END)
                except OSError:
                    fh.seek(0)
                tail = fh.read().decode("utf-8", errors="replace").strip().splitlines()
                if tail:
                    try:
                        last = json.loads(tail[-1])
                    except Exception:
                        last = None
        if last is not None:
            a = {k: v for k, v in last.items() if k != "ts"}
            b = {k: v for k, v in row.items() if k != "ts"}
            if a == b:
                return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_hook_error(round_dir: Path | None, exc: BaseException, where: str) -> None:
    try:
        if round_dir is None:
            return
        round_dir.mkdir(parents=True, exist_ok=True)
        with open(round_dir / "hook_errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {where}: {type(exc).__name__}: {exc}\n")
    except Exception:
        pass


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"


# --------------------------------------------------------------- verdicts --

_FENCE_RE = re.compile(r"```(?:yaml|yml)[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL | re.IGNORECASE)
_VERDICT_LINE_RE = re.compile(r"^\s*VERDICT:\s*(PASS|REVISE_PROOF|REVISE_PLAN|REWRITE|PIVOT)\s*$", re.MULTILINE)
JUDGE_DECISIONS = ("PASS", "REVISE_PROOF", "REVISE_PLAN", "REWRITE", "PIVOT")


def verdict_block_min(text: str) -> dict | None:
    """Last fenced yaml block as a flat ``{key: value}`` dict (top-level scalars only)."""
    blocks = _FENCE_RE.findall(text or "")
    if not blocks:
        return None
    out: dict = {}
    for ln in blocks[-1].splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_ -]*):\s*(.*)$", ln)
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip().strip('"').strip("'")
            out[key] = val
    return out or None


def read_gate(path: Path) -> tuple[str, str | None]:
    """Parse a phase-gate marker: line 1 is the phase, an optional ``owner=<session id>`` line says
    which Claude Code session opened it. Legacy markers (phase only) have no owner."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return "", None
    phase, owner = "", None
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("owner="):
            owner = line.split("=", 1)[1].strip() or None
        elif i == 0 or not phase:
            phase = line
    return phase, owner


def session_slug(session_id: str) -> str:
    """Filesystem-safe short form of a session id (for per-session counter files)."""
    keep = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in "-_")
    return keep[:40] or "anon"



def verdict_block_looks_valid_min(block: dict | None, role: str | None = None) -> bool:
    if not block or not block.get("role") or not block.get("claim") or not block.get("verdict"):
        return False
    r = ROLE_ALIASES.get(str(block["role"]).lower(), str(block["role"]).lower())
    if role and r != role:
        return False
    v = str(block["verdict"])
    if r == "judge":
        return v.upper() in JUDGE_DECISIONS
    return v.lower() in ("pass", "fail", "revise", "n/a")


def judge_verdict_min(text: str) -> str | None:
    m = _VERDICT_LINE_RE.findall(text or "")
    return m[-1] if m else None
